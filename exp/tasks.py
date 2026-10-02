#!/usr/bin/env python3
"""A/B task suite + deterministic grader for the explore-index experiment.

Each task declares the facts a correct answer MUST contain (need) and the files a
correct answer MUST point at (paths). The grader is purely mechanical: it reads
the subagent's final report and checks the contract. That keeps accuracy scoring
objective and identical across arms, so an accuracy drop voids the run.

Task split:
  SEEDED  — covered by facts already in .explore/INDEX.md (auth, retry/backoff).
            Measures lookup value.
  HELDOUT — deliberately NOT in the index (encryption, tenant scoping, the CRM
            offline store, migrations). Measures generalization and false-hit
            risk. A held-out task must NOT be answered from the index; if the
            agent claims an index row resolves it, that is a false hit.
"""

from __future__ import annotations

import os
import re

# Absolute path to the repository under test. Override with REPO_ROOT=... to
# reproduce the benchmark on your own checkout of GrowiaCRM.
REPO = os.environ.get("REPO_ROOT", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "GrowiaCRM"))

# Facts that only exist in .explore/INDEX.md right now.
INDEX_SEEDED_TOPICS = {
    "auth", "backoff", "retry", "session", "cookie", "middleware",
}

TASKS: list[dict] = [
    # ---------------- SEEDED (covered by the warm index) ----------------
    {
        "id": "S1",
        "split": "seeded",
        "question": "Where is the shared retry helper with exponential backoff implemented, and is it used repo-wide?",
        "need": ["backoff.ts", "computeBackoffMs", "jobs"],
        "paths": ["apps/api/src/modules/jobs/backoff.ts"],
    },
    {
        "id": "S2",
        "split": "seeded",
        "question": "How does authentication work in this API? Is it JWT or something else?",
        "need": ["identity", "session", "cookie"],
        "paths": ["apps/api/src/modules/identity"],
    },
    {
        "id": "S3",
        "split": "seeded",
        "question": "Is there a generic retry wrapper utility anywhere in this repo that HTTP or service calls can reuse?",
        "need": ["no", "not"],
        "paths": [],
        "absent_answer": True,
    },
    # ---------------- HELD-OUT (never in the index) ----------------
    {
        "id": "H1",
        "split": "heldout",
        "question": "How are attachments/files stored on disk for data operations, and what validates an upload?",
        "need": ["filesystem-storage", "assert"],
        "paths": ["apps/api/src/modules/data-operations/filesystem-storage.ts"],
    },
    {
        "id": "H2",
        "split": "heldout",
        "question": "How does row-level tenant scoping get applied to database queries?",
        "need": ["tenant", "scop"],
        "paths": ["apps/api/src/modules/tenancy/sql-scope.ts"],
    },
    {
        "id": "H3",
        "split": "heldout",
        "question": "Where is the CRM's offline IndexedDB encrypted store implemented and what does it manage?",
        "need": ["indexeddb", "offline", "store"],
        "paths": ["apps/crm/src/features/offline/storage/indexedDbEncryptedStore.ts"],
    },
    {
        "id": "H4",
        "split": "heldout",
        "question": "How are MySQL schema migrations tracked and applied at runtime?",
        "need": ["migration"],
        "paths": ["apps/api/src/runtime/mysql/migrations.ts"],
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

# Method requirements are arm-specific. Before 2026-10-02 both arms shared one
# template whose rule 2 ("search BROADLY... do not shortcut") and rule 4 ("try at
# least 3 different phrasings before concluding it does not exist") instructed the
# treatment arm to do precisely what the skill forbids. The treatment arm was
# being asked to ignore an ABSENT row and run the synonym family anyway, so a
# wording fix in SKILL.md alone could never have been the whole story.
#
# Fix: the shared parts of the protocol (log every call, report strategy first,
# declare wasted reads) stay identical across arms, so the measured difference is
# the SEARCH STRATEGY and nothing else. Accuracy remains mechanical and identical.
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
    names_real_paths = bool(
        re.search(r"apps/(api|crm|landing|owner)/src/|packages/", low))

    if task.get("absent_answer"):
        says_absent = bool(re.search(
            r"\bno\b.{0,60}\b(withretry|generic retry|retry wrapper)|"
            r"does not exist|no generic|there is no|zero .{0,30}wrapper", low))
        resolved = says_absent
        coverage = {"absent": float(says_absent)}
        false_hit = False
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
    print(f"{len(TASKS)} tasks: "
          f"{sum(1 for t in TASKS if t['split']=='seeded')} seeded, "
          f"{sum(1 for t in TASKS if t['split']=='heldout')} held-out")