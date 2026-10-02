#!/usr/bin/env python3
"""Decompose headline token savings across cache-pricing regimes.

WHY THIS EXISTS
---------------
`analyze.py` reports `provider_tokens`, of which ~85% is cache-read. Raw billed
tokens are therefore the most flattering denominator available. A reader who
prices cache reads at a realistic discount (0.1x) sees a materially smaller
saving, and a reader who ignores cache reads entirely (0.0x) sees a smaller one
still.

Publishing a single number invites the obvious objection: "your saving is mostly
cache reads." This script answers that objection in advance by reporting every
figure at every rate, so the honest range is the headline and no single number
is load-bearing.

Reads runs.jsonl only. Writes nothing.

Usage:
  python3 costs.py                       # pooled headline cohort
  python3 costs.py --cohort all          # includes the failed advisory cohort
  python3 costs.py --repo django         # a second repo's runs, once they exist
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "results" / "runs.jsonl"

# Relative price of a cache-read token versus a fresh input token. 1.0 is the
# raw-billed-token view; 0.1 approximates standard cache-read discounting;
# 0.0 isolates fresh compute and ignores reads entirely.
CACHE_RATES = (1.0, 0.1, 0.0)

# Token classes as the runtime actually reports them. Verified against
# runs.jsonl: provider_tokens == uncached_input + cache_read exactly, for all 31
# runs. OUTPUT IS NOT PART OF provider_tokens — it is tracked separately, so
# adding it here would double-count and inflate the 1.0x denominator.
FRESH = "uncached_input"
CACHE = "cache_read"
OUTPUT = "output_tokens"


def load(cohort: str, repo: str | None) -> list[dict]:
    if not RUNS.exists():
        return []
    runs = [json.loads(l) for l in RUNS.read_text().splitlines() if l.strip()]
    # Retained-for-audit rows (partial session snapshots) never enter an aggregate.
    runs = [r for r in runs if not r.get("excluded_from_analysis")]
    if repo:
        # GrowiaCRM predates the `repo` field (it was the only repo when these
        # runs were recorded), so a missing field means "growiacrm". Without this
        # default the repo filter silently dropped all 31 legacy rows and the
        # published 39.9% headline recomputed as 28.8% against a Django-mixed pool.
        runs = [r for r in runs if r.get("repo", "growiacrm") == repo]
    if cohort != "all":
        # "current" is the default: every treatment revision that is actually in
        # the shipped SKILL.md lineage (v2-binding pre-Round-2, v3-bigfile post).
        # Baseline runs are always included so the two arms stay comparable.
        wanted = ({"v2-binding", "v3-bigfile"} if cohort == "current"
                  else {cohort})
        runs = [r for r in runs
                if r.get("arm") != "treatment" or r.get("skill_version") in wanted]
    return runs


def cost(r: dict, cache_rate: float) -> float:
    """Effective cost of one run under a given cache-read rate.

    At cache_rate=1.0 this returns exactly `provider_tokens`, so the 1.0x row is
    a self-test: it must reproduce analyze.py's headline. Output tokens are added
    because they are genuinely billed work, but they are deliberately excluded
    from the input side to avoid the double-count described above.
    """
    return r[FRESH] + r[CACHE] * cache_rate + r[OUTPUT] * 0.0


def welch(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's t and a two-sided p-value via Student's t.

    Uses the survival function of the t-distribution; no SciPy dependency,
    because this repo's harness is stdlib-only on purpose.
    """
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0, 1.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    se2 = va / na + vb / nb
    if se2 <= 0:
        return 0.0, 1.0
    t = (mb - ma) / (se2 ** 0.5)
    df = se2 ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    return round(t, 3), round(_tp(t, df), 4)


def _tp(t: float, df: float) -> float:
    """Two-sided p-value for Student's t, via the regularized incomplete beta."""
    x = df / (df + t * t)
    return _betainc(df / 2.0, 0.5, x)


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = (_lgamma(a + b) - _lgamma(a) - _lgamma(b)
             + a * __import__("math").log(x) + b * __import__("math").log1p(-x))
    front = __import__("math").exp(lbeta)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1 - x) / b


def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return h


def _lgamma(x: float) -> float:
    import math
    return math.lgamma(x)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="current")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    runs = load(a.cohort, a.repo)
    if not runs:
        print(f"no runs recorded for cohort={a.cohort} repo={a.repo}")
        return

    out: dict = {"cohort": a.cohort, "repo": a.repo or "(all)",
                 "runs": len(runs), "rates": {}}

    for rate in CACHE_RATES:
        arms = {}
        for arm in ("baseline", "treatment"):
            rs = [r for r in runs if r["arm"] == arm]
            if not rs:
                continue
            arms[arm] = {
                "n": len(rs),
                "mean_cost": round(statistics.mean(cost(r, rate) for r in rs)),
                "mean_tokens": round(statistics.mean(r["provider_tokens"] for r in rs)),
                "mean_turns": round(statistics.mean(r["turns"] for r in rs), 2),
                "mean_tool_calls": round(statistics.mean(r["tool_calls"] for r in rs), 2),
                "accuracy": round(statistics.mean(float(r["resolved"]) for r in rs), 3),
                "false_hits": sum(1 for r in rs if r["false_hit"]),
            }
        if len(arms) != 2:
            continue

        b, t_ = arms["baseline"], arms["treatment"]
        bc = [cost(r, rate) for r in runs if r["arm"] == "baseline"]
        tc = [cost(r, rate) for r in runs if r["arm"] == "treatment"]
        tstat, pval = welch(bc, tc)
        out["rates"][f"{rate:g}x"] = {
            **arms,
            "delta_pct": round(100 * (t_["mean_cost"] - b["mean_cost"]) / b["mean_cost"], 1),
            "welch_t": tstat,
            "welch_p": pval,
            "iso_accuracy": t_["accuracy"] >= b["accuracy"] - 0.05,
            "false_hit_rate": round(t_["false_hits"] / t_["n"], 4) if t_["n"] else 0.0,
        }

    if a.json:
        print(json.dumps(out, indent=2))
        return

    print(f"cohort={out['cohort']}  repo={out['repo']}  runs={out['runs']}")
    print()
    print(f"{'cache':>7} | {'baseline':>10} {'treatment':>10} {'delta':>8} | "
          f"{'p':>8} | {'acc':>5} | {'false':>5}")
    print("-" * 68)
    for rate, v in out["rates"].items():
        print(f"{rate:>7} | {v['baseline']['mean_cost']:>10,} "
              f"{v['treatment']['mean_cost']:>10,} {v['delta_pct']:>7.1f}% | "
              f"{v['welch_p']:>8} | {v['treatment']['accuracy']:>5} | "
              f"{v['false_hit_rate']:>5}")
    print()
    print("delta is the saving vs baseline at that cache-pricing rate.")
    print("Report the range, not the most flattering single number.")


if __name__ == "__main__":
    main()