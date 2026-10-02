#!/usr/bin/env python3
"""Extract per-turn provider token telemetry from MiniMax Code's local runtime store.

Reads ~/.minimax/v2/sqlite/runtime-state.sqlite (read-only) and emits, for each
session, a JSON record with:

  - providerTokens at each terminal turn (authoritative billed count)
  - billed_tokens_total = sum over turns of providerTokens
      (each turn's providerTokens is the FULL context that turn sent, so the
       sum approximates total prompt+completion volume across the trajectory)
  - uncached_input_total = sum of usage.input_tokens (fresh, non-cached input)
  - cache_read_total    = sum of usage.cache_read
  - output_total        = sum of usage.output_tokens
  - per-tool-call arguments/results, for waste analysis

Usage:
  python3 telemetry.py --session-id mvs_xxx  [--out out.json]
  python3 telemetry.py --all --since-ms 1790920000000
  python3 telemetry.py --session-id mvs_xxx --toolcalls
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any

DB = os.path.expanduser("~/.minimax/v2/sqlite/runtime-state.sqlite")


def connect() -> sqlite3.Connection:
    if not os.path.exists(DB):
        sys.exit(f"runtime store not found: {DB}")
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def list_sessions(since_ms: int = 0) -> list[tuple[str, int, str]]:
    con = connect()
    rows = con.execute(
        "SELECT session_id, updated_at_ms, agent_name "
        "FROM local_runtime_sessions WHERE updated_at_ms >= ? "
        "ORDER BY updated_at_ms ASC",
        (since_ms,),
    ).fetchall()
    con.close()
    return [(r[0], r[1], r[2] or "") for r in rows]


def extract(session_id: str, want_toolcalls: bool = False) -> dict[str, Any]:
    con = connect()
    rows = con.execute(
        "SELECT id, role, turn_id, data_json FROM local_runtime_message_rows "
        "WHERE session_id=? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    con.close()

    turns: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    provider_total = 0
    uncached_input = 0
    cache_read = 0
    output_total = 0
    final_result = ""
    user_prompt = ""

    for _id, role, turn_id, data_json in rows:
        try:
            d = json.loads(data_json)
        except json.JSONDecodeError:
            continue

        if role == "user" and not user_prompt:
            user_prompt = (d.get("msg_content") or "")[:4000]

        usage = d.get("usage") or {}
        tel = d.get("context_usage_telemetry") or {}
        comp = {
            c.get("kind"): c.get("tokens")
            for c in (d.get("context_usage") or {}).get("components", [])
        }

        pt = tel.get("providerTokens")
        if isinstance(pt, int):
            provider_total += pt

        if isinstance(usage.get("input_tokens"), int):
            uncached_input += usage["input_tokens"]
        if isinstance(usage.get("cache_read"), int):
            cache_read += usage["cache_read"]
        if isinstance(usage.get("output_tokens"), int):
            output_total += usage["output_tokens"]

        if pt is not None or usage:
            turns.append(
                {
                    "turn_id": turn_id,
                    "provider_tokens": pt,
                    "local_tokens": tel.get("localTokens"),
                    "divergence": tel.get("divergenceRate"),
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "cache_read": usage.get("cache_read"),
                    "ctx_used": (d.get("context_usage") or {}).get("usedTokens"),
                    "ctx_components": comp,
                    "finish_reason": d.get("finish_reason"),
                }
            )

        for tc in d.get("tool_calls") or []:
            args = tc.get("tool_call_args")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args[:200]}
            raw = tc.get("tool_call_result_data")
            result_bytes = len(raw) if isinstance(raw, str) else 0
            if raw and "matchLimitReached" in raw:
                result_bytes = 100_000  # saturated: effectively unbounded cost
            tool_calls.append(
                {
                    "turn_id": turn_id,
                    "tool": tc.get("tool_name"),
                    "args": args,
                    "result_bytes": result_bytes,
                    "empty": result_bytes == 0,
                }
            )

        if d.get("finish_reason") == "stop" and role == "assistant":
            final_result = d.get("msg_content") or final_result

    return {
        "session_id": session_id,
        "turns": len(turns),
        "provider_tokens_total": provider_total,
        "uncached_input_total": uncached_input,
        "cache_read_total": cache_read,
        "output_tokens_total": output_total,
        "tool_calls": len(tool_calls),
        "empty_tool_calls": sum(1 for t in tool_calls if t["empty"]),
        "tool_calls_detail": tool_calls if want_toolcalls else None,
        "final_result": final_result,
        "user_prompt": user_prompt,
        "turn_detail": turns,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--since-ms", type=int, default=0)
    ap.add_argument("--toolcalls", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()

    if args.all:
        out = [extract(s, args.toolcalls) for s, _, _ in list_sessions(args.since_ms)]
    elif args.session_id:
        out = extract(args.session_id, args.toolcalls)
    else:
        ap.error("need --session-id or --all")

    if args.summary and args.all:
        for r in out:
            print(
                f"{r['session_id']}  turns={r['turns']:>3}  "
                f"provider={r['provider_tokens_total']:>7}  "
                f"uncached={r['uncached_input_total']:>6}  "
                f"cache_r={r['cache_read_total']:>7}  "
                f"out={r['output_tokens_total']:>6}  "
                f"tools={r['tool_calls']:>3}  empty={r['empty_tool_calls']:>2}"
            )
    else:
        print(json.dumps(out, indent=2))

    if args.out:
        with open(args.out, "w") as f:
            json.dump(out, f, indent=2)
        print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()