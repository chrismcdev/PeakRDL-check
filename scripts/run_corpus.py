#!/usr/bin/env python3
"""Run the semantic-diff corpus and score results against expectations.

Each scenario directory contains:
    before.rdl / after.rdl        (or before/ after/ dirs with main.rdl)
    expected.json:
        {
          "title": "...",
          "category": "breaking|behavioural|compatible|neutral|difficult",
          "expect":   [{"ruleId": "...", "entityKey": "...",
                        "classification": "..."}, ...],
          "forbid":   ["RULE-ID", ...],          # must not appear at all
          "maxChanges": 0,                        # optional cap on total changes
          "top": "soc",                           # optional top component
          "minChanges": 5                         # optional lower bound
        }

The runner writes, per scenario: git.diff, semantic-diff.json,
semantic-diff.md — and a corpus-wide results.json + report.md.
Exit code 1 if any scenario fails.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from regreview.adapter import build_canonical            # noqa: E402
from regreview.diff import compile_failed_result, diff_models  # noqa: E402
from regreview.report import format_json, format_markdown      # noqa: E402


def find_input(scen: Path, which: str):
    single = scen / f"{which}.rdl"
    if single.is_file():
        return [single]
    d = scen / which
    if (d / "main.rdl").is_file():
        return [d / "main.rdl"]
    raise FileNotFoundError(f"{scen.name}: no {which}.rdl or {which}/main.rdl")


def run_git_diff(scen: Path) -> str:
    b, a = find_input(scen, "before")[0], find_input(scen, "after")[0]
    if b.parent != scen or a.parent != scen:
        # directory scenarios: diff the whole trees
        cmd = ["git", "diff", "--no-index", "--stat", "--patch",
               str(scen / "before"), str(scen / "after")]
    else:
        cmd = ["git", "diff", "--no-index", str(b), str(a)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout


def run_scenario(scen: Path) -> dict:
    expected = json.loads((scen / "expected.json").read_text())
    top = expected.get("top")
    record = {"scenario": scen.name, "title": expected.get("title", scen.name),
              "category": expected.get("category", "?")}

    git_text = run_git_diff(scen)
    (scen / "git.diff").write_text(git_text)
    record["gitDiffLines"] = len(git_text.splitlines())

    def compile_side(which):
        files = find_input(scen, which)
        return build_canonical(files, top=top, source_mode="all")

    t0 = time.perf_counter()
    from systemrdl import RDLCompileError
    try:
        base = compile_side("before")
    except RDLCompileError as e:
        result = compile_failed_result("base", str(e))
        base = None
    if base is not None:
        try:
            head = compile_side("after")
            result = diff_models(base, head)
        except RDLCompileError as e:
            result = compile_failed_result("head", str(e))
    record["diffSeconds"] = round(time.perf_counter() - t0, 3)

    (scen / "semantic-diff.json").write_text(format_json(result))
    (scen / "semantic-diff.md").write_text(format_markdown(result))

    changes = result.get("changes", [])
    record["totalChanges"] = len(changes)
    record["summary"] = result.get("summary", {})

    failures = []
    for exp in expected.get("expect", []):
        hits = [c for c in changes
                if c["ruleId"] == exp["ruleId"]
                and (exp.get("entityKey") is None
                     or c["entityKey"] == exp["entityKey"])]
        if not hits:
            failures.append(f"missing expected {exp['ruleId']} on "
                            f"{exp.get('entityKey', '<any>')}")
            continue
        want_cls = exp.get("classification")
        if want_cls and not any(c["classification"] == want_cls for c in hits):
            failures.append(
                f"{exp['ruleId']} on {exp.get('entityKey')}: classification "
                f"{hits[0]['classification']} != expected {want_cls}")
        want_conf = exp.get("confidence")
        if want_conf and not any(c.get("confidence") == want_conf for c in hits):
            failures.append(
                f"{exp['ruleId']} on {exp.get('entityKey')}: confidence "
                f"{hits[0].get('confidence')} != expected {want_conf}")
    for rule in expected.get("forbid", []):
        if any(c["ruleId"] == rule for c in changes):
            failures.append(f"forbidden rule {rule} appeared")
    if "maxChanges" in expected and len(changes) > expected["maxChanges"]:
        failures.append(f"{len(changes)} changes > maxChanges {expected['maxChanges']}")
    if "minChanges" in expected and len(changes) < expected["minChanges"]:
        failures.append(f"{len(changes)} changes < minChanges {expected['minChanges']}")
    # every change must carry rule id, message, classification, entity
    for c in changes:
        for req in ("ruleId", "message", "classification", "entityKey"):
            if not c.get(req):
                failures.append(f"change missing required '{req}': {c}")
                break

    record["failures"] = failures
    record["pass"] = not failures
    return record


def main() -> int:
    corpus = ROOT / "diff-corpus" / "scenarios"
    only = sys.argv[1] if len(sys.argv) > 1 else None
    records = []
    for scen in sorted(corpus.iterdir()):
        if not scen.is_dir() or not (scen / "expected.json").is_file():
            continue
        if only and only not in scen.name:
            continue
        try:
            rec = run_scenario(scen)
        except Exception as e:
            rec = {"scenario": scen.name, "pass": False,
                   "failures": [f"runner error: {type(e).__name__}: {e}"]}
        records.append(rec)
        mark = "PASS" if rec["pass"] else "FAIL"
        print(f"[{mark}] {scen.name}: {rec.get('totalChanges', '?')} changes, "
              f"git diff {rec.get('gitDiffLines', '?')} lines")
        for f in rec.get("failures", []):
            print(f"       - {f}")

    passed = sum(1 for r in records if r["pass"])
    out = {
        "total": len(records),
        "passed": passed,
        "failed": len(records) - passed,
        "records": records,
    }
    (ROOT / "diff-corpus" / "results.json").write_text(
        json.dumps(out, indent=2) + "\n")
    print(f"\n{passed}/{len(records)} scenarios passed")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    sys.exit(main())
