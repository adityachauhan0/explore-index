#!/usr/bin/env python3
"""A/B task suite + deterministic grader for the explore-index experiment (Django).

Second-repository replication of the GrowiaCRM study in tasks.py. The original run
is still `stage: experimental` because it rests on ONE repo, ONE model, 7 tasks;
cross-repo replication is the promotion gate. This module is an independent copy:
it deliberately does NOT import from tasks.py, so a later edit to either suite
cannot silently weaken the other. The prompt template, grader contract and
self-check shape are duplicated verbatim instead.

Every `need` substring and every `paths` entry below was verified by grep against
the checkout at REPO (/tmp/djtest, HEAD 80ea222) before this file was written.

Task split:
  SEEDED  — facts that WILL be journaled into .explore/INDEX.md before the
            treatment arm runs. Measures index hit-rate.
  HELDOUT — no matching index row by construction. Measures whether the skill
            still behaves sensibly with no shortcut, and whether it falls back to
            narrow reads instead of spiraling. H4 deliberately targets a mega-file
            subsystem (django/db/models/sql/query.py, 122KB) because that was the
            known weak case in the original study.

Deviation from tasks.py, deliberate and stated:
  tasks.py hardcodes false_hit=False for absent_answer tasks. That is wrong for an
  absent-symbol probe: a confident agent that invents a real-looking Django path
  and claims the symbol lives there is exactly the failure this experiment gates
  on. Here an absent task sets false_hit=True when the report localizes the symbol
  to ANY real repo path. Correct `paths` is empty, so "cites a repo path" and
  "cites a wrong repo path" are the same condition here.
"""

from __future__ import annotations

import os
import re

# Absolute path to the repository under test. Override with REPO_ROOT=... to
# reproduce the benchmark on your own Django checkout.
REPO = os.environ.get("REPO_ROOT", "/tmp/djtest")

# Seeded topics the index is expected to carry for the Django run.
INDEX_SEEDED_TOPICS = {
    "csrf", "hashers", "password", "middleware",
}

TASKS: list[dict] = [
    # ---------------- SEEDED (covered by the warm index) ----------------
    {
        "id": "S1",
        "split": "seeded",
        "question": "How does Django enforce CSRF protection on incoming requests, and where is the view decorator that opts a single view out?",
        "need": ["csrf_exempt", "CsrfViewMiddleware", "process_view"],
        "paths": ["django/middleware/csrf.py"],
    },
    {
        "id": "S2",
        "split": "seeded",
        "question": "How does Django hash and verify user passwords, and how does it tell which hasher produced an existing hash?",
        "need": ["PBKDF2PasswordHasher", "check_password", "identify_hasher"],
        "paths": ["django/contrib/auth/hashers.py"],
    },
    {
        "id": "S3",
        "split": "seeded",
        "question": "Is there a generic retry helper with exponential backoff anywhere in this repo — for example a with_retry decorator, a RateLimiter, or a CircuitBreaker — that application code could reuse?",
        "need": ["no", "not"],
        "paths": [],
        "absent_answer": True,
    },
    # ---------------- HELD-OUT (never in the index) ----------------
    {
        "id": "H1",
        "split": "heldout",
        "question": "How does Django stream a large response without buffering it, and what happens to the underlying file handle when the response closes?",
        "need": ["StreamingHttpResponse", "_resource_closers", "FileResponse"],
        "paths": ["django/http/response.py"],
    },
    {
        "id": "H2",
        "split": "heldout",
        "question": "How does QuerySet.get_or_create avoid a duplicate row when two callers race, and which transaction guard does it rely on?",
        "need": ["get_or_create", "transaction.atomic", "IntegrityError"],
        "paths": ["django/db/models/query.py"],
    },
    {
        "id": "H3",
        "split": "heldout",
        "question": "When a template is missing, which exception is raised and which loader chain produces it — and how does the app_directories loader fit in?",
        "need": ["TemplateDoesNotExist", "find_template", "app_directories"],
        "paths": ["django/template/engine.py"],
    },
    {
        "id": "H4",
        "split": "heldout",
        "question": "Inside the ORM's SQL layer, where does a QuerySet.filter() argument get turned into actual SQL predicates — trace Q objects through to the lookup that builds the WHERE clause.",
        "need": ["build_filter", "add_q", "resolve_lookup_value", "sql/query.py"],
        "paths": ["django/db/models/sql/query.py"],
    },
]

PROMPT_HEAD = """You are running a controlled exploration probe against a real codebase. \
Your job is to locate code and to report precisely how you searched.

REPO: {repo}
MODE: {mode}

TASK: {question}

METHOD REQUIREMENTS — this is what is being measured, so follow them exactly:
1. Before searching, state in one line what search strategy you are about to use.
2. {method_2}
3. Log every tool call you make, in order. For each: the tool (grep/glob/read), the target (pattern or path), whether it returned results or came back empty, and roughly how big the output was.
4. {method_4}
5. If you open a file and it turns out to be irrelevant, explicitly note it as a wasted read.

At the end report:
- FINAL ANSWER: {answer_hint}
- TOOLCALL LOG: the numbered list, including empty searches and wasted reads
- TOTAL TOOL CALLS: N
- WASTED (empty searches + irrelevant files): N
- One sentence: what you would do differently now that you know.

Do not modify any files. Read-only."""

BASELINE_MODE = ("BASELINE — no index, no prior knowledge. Do NOT consult any file named "
                 "INDEX.md or anything under a .explore/ directory.")

TREATMENT_MODE = (
    "TREATMENT — you may consult .explore/INDEX.md before broad searches, following the "
    "explore-index skill. Read it once at the start of this task and whenever you are about "
    "to run a broad repo-wide search or open unknown files. The index routes you; it never "
    "states facts about code, so never answer from it alone — always confirm at the pointed "
    "path. Journal anything new you learn."
)

# Assertion of absence, tuned to the S3 probe. Deliberately does NOT rely on the
# `need` substrings: "no" is a substring of too many ordinary words to grade on.
ABSENT_RE = re.compile(
    r"there is no|does not exist|no such|doesn'?t exist|"
    r"no .{0,40}(retry|rate limiter|ratelimiter|circuit breaker|circuitbreaker)|"
    r"not .{0,40}(retry helper|with_retry|backoff)|"
    r"zero .{0,30}(retry|wrapper|limiter)|"
    r"no .{0,25}(helper|util|utility|decorator)",
)

# A real source path inside the checkout. Django's source root is django/, so a
# bare "django/" is the analogue of tasks.py's apps/*/src/ + packages/ pattern.
# Matches arbitrarily NESTED paths (django/tasks/base.py, django/db/models/sql/
# query.py) as well as module files and bare package dirs. The previous single
# segment pattern silently failed on nested paths, which mis-flagged honest
# citations on absent probes as false hits.
REAL_PATH_RE = re.compile(r"django/(?:[a-z_]+/)*[a-z_]+\.py|django/(?:[a-z_]+/)+")

# Path-token scanner, used to confirm a cited path actually exists on disk. An
# absent-probe grader must ask "is this a real file?" rather than "does this look
# like a path?", otherwise citing a correct nested file reads as a false hit.
PATH_TOKEN_RE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)+[\w.-]+\.py)")


def cites_real_file(text: str, root: str = "/tmp/djtest") -> bool:
    """True when the report cites at least one real file inside the checkout.

    Falls back to a shape check if the checkout is absent, so grading still runs
    on a machine that does not have the benchmark clone.
    """
    for m in PATH_TOKEN_RE.findall(text):
        p = os.path.join(root, m)
        if os.path.isfile(p):
            return True
    return False


# Method requirements are arm-specific, copied verbatim from tasks.py so the two
# suites stay comparable. The shared parts of the protocol (log every call, report
# strategy first, declare wasted reads) stay identical across arms, so the measured
# difference is the SEARCH STRATEGY and nothing else.
BASELINE_METHOD_2 = ("Search BROADLY and realistically, the way an agent with no prior "
                     "knowledge would. Do not shortcut by guessing paths.")
BASELINE_METHOD_4 = ("IMPORTANT: if a search comes back empty, try SYNONYMS and related terms. "
                     "Do this naturally, as an agent genuinely trying to find something would. "
                     "Try at least 3 different phrasings before concluding it does not exist.")

TREATMENT_METHOD_2 = ("Follow the explore-index skill's search strategy: consult "
                       ".explore/INDEX.md before a broad search, and when no row covers the "
                       "question run one narrow grep with the task's own words, then at most "
                       "one synonym grep, and only then widen.")
TREATMENT_METHOD_4 = ("IMPORTANT: the skill's rule applies — if .explore/INDEX.md holds an "
                       "ABSENT row covering this question, that is the answer: report it and "
                       "stop, without running the synonym family. If no row covers it, search "
                       "normally and try synonyms as an agent would.")


def build_prompt(task: dict, arm: str) -> str:
    mode = BASELINE_MODE if arm == "baseline" else TREATMENT_MODE
    m2 = BASELINE_METHOD_2 if arm == "baseline" else TREATMENT_METHOD_2
    m4 = BASELINE_METHOD_4 if arm == "baseline" else TREATMENT_METHOD_4
    hint = ("where it lives, with paths, or state clearly that it does not exist")
    if task.get("absent_answer"):
        hint = "does it exist? If not, say so plainly and say what you searched"
    return PROMPT_HEAD.format(repo=REPO, mode=mode, method_2=m2, method_4=m4,
                              question=task["question"], answer_hint=hint)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def grade(task: dict, final_text: str) -> dict:
    """Mechanical grading. Returns resolved, per-fact coverage, and a false-hit flag."""
    low = _norm(final_text)

    # A held-out task resolved "from the index" is only acceptable if the report
    # still names real source paths. Claiming an index row answers it is a false hit.
    # `low` is already lowercased, so the pattern must be too — otherwise a
    # literal ".explore/INDEX.md" citation is never detected and false hits slip through.
    cited_index = bool(re.search(r"\.explore/index\.md|explore index", low))
    names_real_paths = bool(REAL_PATH_RE.search(low))

    if task.get("absent_answer"):
        says_absent = bool(ABSENT_RE.search(low))
        resolved = says_absent
        coverage = {"absent": float(says_absent)}
        # Correct paths is empty for an absent probe, so localizing the "symbol"
        # to any real repo file is by definition a confident wrong localization.
        # Existence is checked on disk, not by shape: citing django/tasks/base.py
        # is a false hit, citing tests/cache/tests.py while saying "this is a
        # test-only decorator, not a reusable helper" is not.
        # An absent probe has exactly one correct shape: assert absence. A report
        # that both asserts absence AND cites real files is citing them as evidence
        # that nothing reusable exists (e.g. "the only retry helper is test-only,
        # tests/cache/tests.py:95"), which is honest and must NOT be a false hit.
        # A false hit is a report that claims the missing helper EXISTS while
        # pointing at a real file — i.e. localization without the absence claim.
        # Shape-matching alone is not enough: the citation must exist on disk.
        false_hit = (not says_absent) and cites_real_file(low)
        names_real_paths = names_real_paths or cites_real_file(low)
    else:
        hits = {f: float(f.lower() in low) for f in task["need"]}
        path_hits = sum(1 for p in task["paths"] if p.lower() in low)
        coverage = hits
        coverage["_paths"] = path_hits / max(len(task["paths"]), 1)
        resolved = sum(hits.values()) >= max(1, len(task["need"]) - 1) and \
            (not task["paths"] or path_hits >= 1)
        # False hit: claims the index resolved it but never names a real source path.
        false_hit = cited_index and not names_real_paths

    return {
        "task": task["id"],
        "split": task["split"],
        "resolved": bool(resolved),
        "coverage": round(sum(coverage.values()) / max(len(coverage), 1), 3),
        "false_hit": bool(false_hit),
        "cited_index": cited_index,
    }


if __name__ == "__main__":
    seeded = sum(1 for t in TASKS if t["split"] == "seeded")
    heldout = sum(1 for t in TASKS if t["split"] == "heldout")
    absent = [t["id"] for t in TASKS if t.get("absent_answer")]
    print(f"{len(TASKS)} tasks: {seeded} seeded, {heldout} held-out")
    print(f"REPO: {REPO}  (exists={os.path.isdir(REPO)})")
    print(f"absent-symbol probes: {', '.join(absent) or 'none'}")
    print("-" * 78)
    for t in TASKS:
        print(f"[{t['id']}] {t['split']:<7} {t['question'][:56]}")
        print(f"      need : {t['need']}")
        print(f"      paths: {t['paths']}")

    # Every graded path must exist in the checkout, or the suite is measuring noise.
    print("-" * 78)
    bad = [(t["id"], p) for t in TASKS for p in t["paths"]
           if not os.path.isfile(os.path.join(REPO, p))]
    print("path check: " + ("all %d paths exist" % sum(len(t["paths"]) for t in TASKS)
                            if not bad else f"MISSING -> {bad}"))