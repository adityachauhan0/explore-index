#!/usr/bin/env python3
"""
Phase 0 control: the deterministic repo map.

Aider's insight (https://aider.chat/docs/repomap.html) is that tree-sitter +
personalized PageRank delivers a codebase's architectural spine for a few hundred
tokens where reading the source costs orders of magnitude more.

This is the CONTROL ARM. It is what the explore-index must beat, and it is what
makes symbol->file entries in the index redundant. If you cannot beat this,
stop.

Usage:
  repomap.py <repo> [--budget 1024] [--json out.json]
"""
from __future__ import annotations
import argparse, json, re, sys
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".next", "coverage",
             "artifacts", ".pnpm-store", "__pycache__", ".venv", "vendor"}
CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".java", ".go", ".rs"}

# Definition-ish patterns. Deliberately regex, not AST: zero deps, runs anywhere,
# and the map is a *skeleton* -- it tells you where to look, not what the code says.
DEF_PATTERNS = [
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)"), "fn"),
    (re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)"), "class"),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s*)?\("), "fn"),
    (re.compile(r"^\s*(?:export\s+)?(?:interface|type)\s+(\w+)"), "type"),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:require\(|\{)"), "const"),
]
IDENT = re.compile(r"\b[A-Za-z_$][A-Za-z0-9_$]{2,}\b")


def iter_code_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in CODE_EXT:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def scan(root: Path) -> tuple[dict, dict]:
    """Returns (defs, refs). defs[name] = [(relpath, kind)], refs[(name, relpath)] = count."""
    defs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    refs: dict[tuple[str, str], int] = defaultdict(int)
    files = 0
    for p in iter_code_files(root):
        rel = str(p.relative_to(root))
        files += 1
        try:
            lines = p.read_text(errors="ignore").splitlines()
        except Exception:
            continue
        local: set[str] = set()
        for ln in lines:
            if len(ln) > 400:
                ln = ln[:400]
            for rx, kind in DEF_PATTERNS:
                m = rx.match(ln)
                if m:
                    defs[m.group(1)].append((rel, kind))
                    local.add(m.group(1))
                    break
            for ident in IDENT.findall(ln):
                refs[(ident, rel)] += 1
    return defs, refs, files


def build_file_graph(defs, refs, ambiguous_above: int = 3) -> dict[str, set[str]]:
    """Edge consumer -> producer. If file A mentions a symbol that file B defines,
    then A depends on B. This is the architectural spine: shared libraries and
    central modules accumulate in-degree; leaf apps stay leaves.

    `ambiguous_above` discards symbols defined in many files. A name like
    `identity` or `clock` is defined in both src and test code; treating that as a
    dependency edge makes every src file look like it depends on whichever test
    file also defines it, which drags test files to the top of the ranking.
    Ambiguous symbols carry no architectural signal, so drop rather than resolve."""
    producers: dict[str, set[str]] = defaultdict(set)
    for name, locs in defs.items():
        for rel, _ in locs:
            producers[name].add(rel)

    graph: dict[str, set[str]] = defaultdict(set)
    for (ident, rel), count in refs.items():
        if count < 1:
            continue
        targets = producers.get(ident)
        if not targets or len(targets) > ambiguous_above:
            continue
        for prod in targets:
            if prod != rel:
                graph[rel].add(prod)
    return graph


def pagerank(graph: dict[str, set[str]], damping=0.85, iters=40) -> dict[str, float]:
    """Personalized PageRank over file->file dependency edges.

    Rank flows toward what many files DEPEND ON (shared libraries, core modules),
    which is the opposite of the previous definition-count scoring that ranked
    self-contained leaf apps first. Deterministic: fixed init, fixed iteration
    count, no randomness, no tie-break on dict order."""
    nodes = set(graph) | {d for deps in graph.values() for d in deps}
    if not nodes:
        return {}
    n = len(nodes)
    rank = {node: 1.0 / n for node in nodes}

    for _ in range(iters):
        nxt: dict[str, float] = defaultdict(float)
        for node in nodes:
            deps = graph.get(node)
            if not deps:
                # Dangling mass redistributes uniformly rather than vanishing.
                share = rank[node] / n
                for other in nodes:
                    nxt[other] += share
                continue
            share = rank[node] / len(deps)
            for dep in deps:
                nxt[dep] += share
        base = (1.0 - damping) / n
        rank = {node: damping * nxt[node] + base for node in nodes}

    total = sum(rank.values()) or 1.0
    return {k: v / total for k, v in rank.items()}


def centrality(defs, graph) -> dict[str, float]:
    """Blend PageRank with raw in-degree (how many distinct files import you).

    PageRank alone is scale-sensitive and can be dominated by one dense cluster;
    in-degree alone over-rewards import hubs that are pure re-export barrels.
    The blend ranks a file high when it is central AND reachable from many peers."""
    in_deg: dict[str, int] = defaultdict(int)
    for deps in graph.values():
        for d in deps:
            in_deg[d] += 1
    pr = pagerank(graph)
    mx = max(pr.values()) if pr else 1.0
    md = max(in_deg.values()) if in_deg else 1
    files = set(pr) | set(in_deg)
    return {f: 0.65 * (pr.get(f, 0.0) / mx) + 0.35 * (in_deg.get(f, 0) / md) for f in files}


def is_test_file(rel: str) -> bool:
    """Test code is not the architectural spine an explorer needs first."""
    parts = rel.split("/")
    if "test" in parts or "tests" in parts or "__tests__" in parts:
        return True
    base = parts[-1]
    return ".test." in base or ".spec." in base or base.endswith("_test.py")


def render(root: Path, defs, scores, budget_tokens: int,
           per_file: int = 6, include_tests: bool = False) -> tuple[str, int, int]:
    """Render a token-budgeted skeleton of the most central files.

    `per_file` caps how many symbols any single file may contribute. Without it a
    single large central file dumps its whole symbol list and consumes the entire
    budget, so the map stops being a map of the repo and becomes a table of
    contents for one file. The cap forces breadth: many central files, a few
    representative symbols each."""
    rows: list[tuple[float, str, str, str]] = []
    for name, locs in defs.items():
        for rel, kind in locs:
            if not include_tests and is_test_file(rel):
                continue
            rows.append((scores.get(rel, 0.0), rel, name, kind))
    rows.sort(key=lambda r: (-r[0], r[1], r[2]))

    out, used, shown = [], 0, 0
    per_file_used: dict[str, int] = defaultdict(int)
    cur_file = None
    for sc, rel, name, kind in rows:
        if used >= budget_tokens:
            break
        if per_file_used[rel] >= per_file:
            continue
        if rel != cur_file:
            if cur_file is not None:
                out.append("")
            out.append(f"{rel}:")
            cur_file = rel
            used += len(rel) // 4 + 2
            if used >= budget_tokens:
                break
        line = f"  {name} ({kind})"
        out.append(line)
        used += len(line) // 4 + 1
        shown += 1
        per_file_used[rel] += 1
    return "\n".join(out), used, shown


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--budget", type=int, default=1024)
    ap.add_argument("--json")
    a = ap.parse_args()

    root = Path(a.repo).resolve()
    defs, refs, nfiles = scan(root)
    graph = build_file_graph(defs, refs)
    scores = centrality(defs, graph)
    text, used, shown = render(root, defs, scores, a.budget)

    all_src = 0
    for p in iter_code_files(root):
        try:
            all_src += len(p.read_text(errors="ignore"))
        except Exception:
            pass

    print(f"files scanned      : {nfiles}")
    print(f"symbols found      : {len(defs)}")
    print(f"map rendered       : {shown} symbols, ~{used} tokens (budget {a.budget})")
    print(f"reading all source : ~{all_src//4} tokens")
    if all_src:
        print(f"compression        : {all_src/4/max(used,1):.0f}x cheaper than reading source")
    print("-" * 60)
    print(text)

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({
            "repo": str(root), "files": nfiles, "symbols": len(defs),
            "map_tokens": used, "shown": shown,
            "full_source_tokens": all_src // 4,
            "top": [{"score": round(s, 5), "file": f, "symbol": n, "kind": k}
                    for s, f, n, k in sorted(
                        ((scores.get(r, 0.0), r, nm, kd) for nm, ls in defs.items() for r, kd in ls),
                        key=lambda x: -x[0])[:60]],
        }, indent=2))
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
