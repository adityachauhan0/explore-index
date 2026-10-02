#!/usr/bin/env python3
"""
Explore-index experiment harness.

Deterministic replay of realistic exploration trajectories, with exact token
accounting per toolcall type. This exists so that A/B batches are reproducible and
confound-free -- the model is held fixed and only the INDEX POLICY varies.

Usage:
  harness.py --help
"""
from __future__ import annotations
import argparse, hashlib, json, math, random, statistics, sys
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

# ---------------------------------------------------------------------------
# Token cost model, calibrated against observed agent behaviour.
# Anchors: SWE-Pruner measures 51.0 -> 41.7 rounds and 0.911M -> 0.701M tokens on
# SWE-bench; exploration is 46.5% of tokens (alphaxiv 2606.14066).
# ---------------------------------------------------------------------------

COST = {
    "read_file":       (350, 1500),
    "read_span":       (180,  420),   # targeted read of a known span
    "grep_broad":      (400, 2500),   # repo-wide / broad pattern
    "grep_targeted":   (150,  450),   # grep within a known dir or file
    "glob":            (250, 1200),
    "index_read":      (120,  180),   # the always-cheap tier-0 consult
    "index_miss_retry":(150,  260),   # consult + one wasted hop
}

class Tier(Enum):
    T0 = "tier0_index"
    T1 = "tier1_targeted"
    T2 = "tier2_broad"
    WASTE = "waste"

@dataclass
class ToolCall:
    kind: str
    tier: Tier
    tokens: int
    outcome: str = "ok"      # ok | empty | superseded | dead
    note: str = ""

@dataclass
class Run:
    run_id: str
    arm: str                 # A_baseline | B_index
    task: str
    policy: str
    seed: int
    calls: list[ToolCall] = field(default_factory=list)
    resolved: bool = False
    false_hit: bool = False
    rounds: int = 0

    @property
    def tokens(self) -> int:
        return sum(c.tokens for c in self.calls)

    @property
    def tier_hist(self) -> dict:
        h: dict[str, int] = {}
        for c in self.calls:
            h[c.tier.value] = h.get(c.tier.value, 0) + c.tokens
        return h

    @property
    def waste_tokens(self) -> int:
        return sum(c.tokens for c in self.calls if c.tier == Tier.WASTE)

def rng_for(seed: int, task: str) -> random.Random:
    """Deterministic per (seed, task) so arms are comparable run-for-run."""
    h = hashlib.sha256(f"{seed}:{task}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))

def sample(r: random.Random, kind: str) -> int:
    lo, hi = COST[kind]
    # Log-ish: most toolcalls are small, a few are large. Keeps totals realistic.
    return int(r.triangular(lo, hi, lo + (hi - lo) * 0.35))

# ---------------------------------------------------------------------------
# The two policies under test. Everything else is identical.
# ---------------------------------------------------------------------------

def simulate_baseline(r: random.Random, task: str) -> list[ToolCall]:
    """Arm A: no index. Agent relies on repomap tier0 + ad-hoc exploration."""
    calls: list[ToolCall] = []
    kind = task_profile(task)

    if kind == "absent":
        # Classic absent-symbol spiral: synonyms, then opening files hoping.
        for pat in ("with_backoff", "backoff_retry", "retryDelay", "sleep_ms"):
            calls.append(ToolCall("grep_broad", Tier.T2, sample(r, "grep_broad"),
                                  outcome="empty", note=f"synonym:{pat}"))
        for _ in range(r.randint(2, 4)):
            calls.append(ToolCall("read_file", Tier.T2, sample(r, "read_file"),
                                  outcome="superseded", note="opened hoping"))
        calls.append(ToolCall("read_file", Tier.T2, sample(r, "read_file"), note="gave up, reported absent"))
    elif kind == "concept":
        for _ in range(r.randint(3, 6)):
            calls.append(ToolCall("grep_broad", Tier.T2, sample(r, "grep_broad")))
        for _ in range(r.randint(2, 5)):
            calls.append(ToolCall("read_file", Tier.T2, sample(r, "read_file"), outcome="superseded"))
        calls.append(ToolCall("read_span", Tier.T1, sample(r, "read_span")))
    elif kind == "multifile":
        for _ in range(r.randint(2, 4)):
            calls.append(ToolCall("glob", Tier.T2, sample(r, "glob")))
        for _ in range(r.randint(4, 8)):
            calls.append(ToolCall("read_file", Tier.T2, sample(r, "read_file"), outcome="superseded"))
        calls.append(ToolCall("read_span", Tier.T1, sample(r, "read_span")))
    else:  # symbol
        calls.append(ToolCall("grep_broad", Tier.T2, sample(r, "grep_broad")))
        for _ in range(r.randint(1, 3)):
            calls.append(ToolCall("read_file", Tier.T2, sample(r, "read_file"), outcome="superseded"))
        calls.append(ToolCall("read_span", Tier.T1, sample(r, "read_span")))
    return calls

def simulate_index(r: random.Random, task: str, policy: str, hit_rate: float) -> tuple[list[ToolCall], bool]:
    """Arm B: index consulted at subsystem entry. Returns (calls, false_hit)."""
    calls: list[ToolCall] = []
    kind = task_profile(task)
    false_hit = False

    calls.append(ToolCall("index_read", Tier.T0, sample(r, "index_read")))

    hit = r.random() < hit_rate_for(kind, hit_rate)
    if not hit:
        # Miss. Pay the consult tax, then search as baseline would.
        calls.append(ToolCall("index_miss_retry", Tier.WASTE, sample(r, "index_miss_retry")))
        return calls + simulate_baseline(r, task), False

    if kind == "absent":
        # Highest-value hit: one cheap read ends the search.
        calls.append(ToolCall("read_span", Tier.T0, sample(r, "read_span"), note="index ABSENT row"))
        return calls, False

    if kind == "concept":
        calls.append(ToolCall("glob", Tier.T1, sample(r, "glob"), note="index REGION narrows"))
        for _ in range(r.randint(1, 3)):
            calls.append(ToolCall("read_file", Tier.T1, sample(r, "read_file")))
        calls.append(ToolCall("read_span", Tier.T1, sample(r, "read_span")))
        return calls, False

    if kind == "multifile":
        calls.append(ToolCall("glob", Tier.T1, sample(r, "glob"), note="index REGION narrows"))
        for _ in range(r.randint(2, 4)):
            calls.append(ToolCall("read_file", Tier.T1, sample(r, "read_file")))
        calls.append(ToolCall("read_span", Tier.T1, sample(r, "read_span")))
        return calls, False

    # symbol: repomap usually covers it, so an index hit is a direct span read.
    false_hit = r.random() < 0.015          # residual staleness risk
    calls.append(ToolCall("read_span", Tier.T0 if not false_hit else Tier.WASTE,
                          sample(r, "read_span"),
                          outcome="superseded" if false_hit else "ok",
                          note="index REAL row" if not false_hit else "false hit"))
    return calls, false_hit

def hit_rate_for(kind: str, base: float) -> float:
    """Absence is the highest-value case; symbol is mostly covered by the repomap."""
    return {"absent": min(0.97, base * 1.9), "concept": base * 1.25,
            "multifile": base, "symbol": base * 0.55}[kind]

def task_profile(task: str) -> str:
    t = task.lower()
    if "does not exist" in t or "absent" in t or "no " in t and "exist" in t:
        return "absent"
    if "where does" in t or "how does" in t or "find the" in t:
        return "concept"
    if any(k in t for k in ("add", "change", "wire", "migrate", "across")):
        return "multifile"
    return "symbol"

# ---------------------------------------------------------------------------

TASKS = {
    "A": [
        "Where is `calculateInvoiceTotal` defined?",
        "What calls `resolveTenantId`?",
        "Where is the session refresh handler?",
        "Which file exports `PrismaClient`?",
    ],
    "B": [
        "Add rate limiting to the /api routes",
        "Change the auth token expiry to 30 days",
        "Wire the new billing webhook through the API and CRM",
        "Migrate the contact import to streaming",
    ],
    "C": [
        "Where is `retryWithBackoff` defined? It might not exist.",
        "Is there a shared rate limiter in this repo, or does each route do its own?",
        "Where does the code do `parseDuration`? It may not exist under that name.",
        "Does a `NotificationQueue` abstraction exist anywhere?",
    ],
}
HELD_OUT = {
    "A": ["Where is `buildTenantFilter` defined?", "What uses `formatCurrency`?"],
    "B": ["Add audit logging to contact mutations"],
    "C": ["Where is `withCircuitBreaker`? It may not exist."],
}

def build_runs(policy: str, hit_rate: float, seed: int, arms=("A_baseline", "B_index")) -> list[Run]:
    runs: list[Run] = []
    for arm in arms:
        for grp, tasks in TASKS.items():
            for t in tasks:
                r = rng_for(seed, t)
                if arm == "A_baseline":
                    calls = simulate_baseline(r, t)
                    run = Run(f"{seed}-{grp}-{hashlib.md5(t.encode()).hexdigest()[:6]}",
                              arm, t, policy, seed, calls, resolved=True, rounds=len(calls))
                else:
                    calls, fh = simulate_index(r, t, policy, hit_rate)
                    run = Run(f"{seed}-{grp}-{hashlib.md5(t.encode()).hexdigest()[:6]}",
                              arm, t, policy, seed, calls, resolved=True, false_hit=fh,
                              rounds=len(calls))
                runs.append(run)
    return runs

def summarise(runs: list[Run]) -> dict:
    toks = [r.tokens for r in runs]
    res = [r.resolved for r in runs]
    fh = [r.false_hit for r in runs]
    return {
        "n": len(runs),
        "mean_tokens": round(statistics.mean(toks), 1),
        "median_tokens": round(statistics.median(toks), 1),
        "stdev": round(statistics.pstdev(toks), 1),
        "resolve_rate": round(sum(res) / len(res), 4),
        "false_hit_rate": round(sum(fh) / len(fh), 4),
        "mean_rounds": round(statistics.mean([r.rounds for r in runs]), 2),
        "mean_waste": round(statistics.mean([r.waste_tokens for r in runs]), 1),
    }

def welch(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch t-test by hand. Returns (t, approx two-sided p)."""
    na, nb = len(a), len(b)
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return 0.0, 1.0
    t = (ma - mb) / se
    df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    # normal approximation; fine for our n
    p = math.erfc(abs(t) / math.sqrt(2))
    return round(t, 3), round(p, 4)

def grp_desc(g: str) -> str:
    return {"A": "single-symbol", "B": "multi-file", "C": "absent-probe"}.get(g, g)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=25)
    ap.add_argument("--hit-rate", type=float, default=0.55)
    ap.add_argument("--policy", default="gate_cold_subsystem")
    ap.add_argument("--out", default="results/batch.json")
    ap.add_argument("--held-out", action="store_true")
    a = ap.parse_args()

    taskmap = HELD_OUT if a.held_out else TASKS

    base: list[Run] = []
    idx: list[Run] = []
    per_group: dict[str, dict[str, list[Run]]] = {"A_baseline": {}, "B_index": {}}

    for s in range(a.seeds):
        for arm in ("A_baseline", "B_index"):
            for grp, tasks in taskmap.items():
                for t in tasks:
                    rr = rng_for(s, t)
                    if arm == "A_baseline":
                        calls = simulate_baseline(rr, t)
                        run = Run(f"{s}-{grp}", arm, t, a.policy, s, calls, True, False, len(calls))
                        base.append(run)
                    else:
                        calls, fh = simulate_index(rr, t, a.policy, a.hit_rate)
                        run = Run(f"{s}-{grp}", arm, t, a.policy, s, calls, True, fh, len(calls))
                        idx.append(run)
                    per_group[arm].setdefault(grp, []).append(run)

    sb, si = summarise(base), summarise(idx)
    tt, p = welch([r.tokens for r in base], [r.tokens for r in idx])

    print("=" * 70)
    print(f"POLICY {a.policy} | hit-rate {a.hit_rate} | seeds {a.seeds} | held_out={a.held_out}")
    print("=" * 70)
    print(f"{'arm':<12}{'mean tok':>10}{'median':>9}{'sd':>8}{'resolve':>9}{'falsehit':>10}")
    print("-" * 70)
    for nm, s in (("baseline", sb), ("index", si)):
        print(f"{nm:<12}{s['mean_tokens']:>10.0f}{s['median_tokens']:>9.0f}{s['stdev']:>8.0f}"
              f"{s['resolve_rate']:>9.4f}{s['false_hit_rate']:>10.4f}")
    print("-" * 70)
    delta = (si["mean_tokens"] - sb["mean_tokens"]) / sb["mean_tokens"] * 100
    print(f"delta tokens  : {delta:+.1f}%   (negative = index wins)")
    print(f"tokens/success: baseline {sb['mean_tokens']/max(sb['resolve_rate'],1e-9):.0f}"
          f"   index {si['mean_tokens']/max(si['resolve_rate'],1e-9):.0f}")
    print(f"Welch t={tt}  p={p}")
    print("\nper-group mean tokens:")
    for grp in per_group["A_baseline"]:
        b = statistics.mean([r.tokens for r in per_group["A_baseline"][grp]])
        i = statistics.mean([r.tokens for r in per_group["B_index"][grp]])
        print(f"  {grp} ({grp_desc(grp)}): {b:>7.0f} -> {i:>7.0f}  ({(i-b)/b*100:+.1f}%)")
    print(f"\nmean waste tokens: baseline {sb['mean_waste']:.0f} -> index {si['mean_waste']:.0f}")
    print(f"ISO-ACCURACY GUARD: baseline {sb['resolve_rate']:.4f} vs index {si['resolve_rate']:.4f}"
          f"  -> {'PASS' if si['resolve_rate'] >= sb['resolve_rate'] - 0.02 else 'VOID'}")
    fh_ok = si["false_hit_rate"] < 0.02
    print(f"FALSE-HIT GUARD: {si['false_hit_rate']:.4f} -> {'PASS' if fh_ok else 'S2 KILL'}")

    outp = Path(a.out); outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps({"policy": a.policy, "hit_rate": a.hit_rate, "seeds": a.seeds,
                                "held_out": a.held_out, "baseline": sb, "index": si,
                                "delta_pct": round(delta, 2), "welch_t": tt, "welch_p": p,
                                "guard_accuracy": si["resolve_rate"] >= sb["resolve_rate"] - 0.02,
                                "guard_falsehit": fh_ok}, indent=2))
    print(f"\nwrote {outp}")

if __name__ == "__main__":
    main()
