#!/usr/bin/env python3
"""GitHub Actions review driver.

Runs inside the composite action (or the local simulator with the same
environment variables). Requires no privileged token: it only reads the
repository worktree and writes workflow files.

Environment:
    BASE_REF / HEAD_REF   git refs to compare
    RDL_GLOB              entry-file glob (default **/*.rdl)
    FAIL_ON               breaking | behavioural | validation-error | none
    POLICY                optional policy JSON path
    GITHUB_STEP_SUMMARY   job summary sink (provided by Actions)
    GITHUB_OUTPUT         step outputs sink (provided by Actions)
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def changed_rdl_files(base: str, head: str, glob: str) -> list:
    out = sh("git", "diff", "--name-only", f"{base}...{head}").stdout
    files = [l for l in out.splitlines() if l.strip()]
    return [f for f in files if fnmatch.fnmatch(f, glob) or f.endswith(".rdl")]


def checkout_tree(ref: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    tar = sh("git", "archive", ref)
    p = subprocess.run(["git", "archive", ref], capture_output=True)
    subprocess.run(["tar", "-x", "-C", str(dest)], input=p.stdout, check=True)


def annotate(change: dict) -> None:
    """Emit a GitHub source annotation for a change."""
    loc = change.get("headLocation") or change.get("baseLocation")
    level = {"breaking": "error", "behavioural": "warning",
             "uncertain": "warning"}.get(change["classification"], "notice")
    if loc and loc.get("file"):
        print(f"::{level} file={loc['file']},line={loc.get('line') or 1},"
              f"title={change['ruleId']}::{change['message']}")


def main() -> int:
    base = os.environ["BASE_REF"]
    head = os.environ["HEAD_REF"]
    glob = os.environ.get("RDL_GLOB", "**/*.rdl")
    fail_on = os.environ.get("FAIL_ON", "breaking")
    policy = os.environ.get("POLICY") or None

    out_dir = Path("regreview-out")
    out_dir.mkdir(exist_ok=True)

    files = changed_rdl_files(base, head, glob)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    outputs_path = os.environ.get("GITHUB_OUTPUT")

    def emit_summary(text: str):
        if summary_path:
            with open(summary_path, "a") as f:
                f.write(text + "\n")
        else:
            print(text)

    if not files:
        emit_summary("### RegReview\n\nNo SystemRDL changes detected.")
        if outputs_path:
            with open(outputs_path, "a") as f:
                f.write("breaking-count=0\nreport-path=\n")
        return 0

    base_tree = out_dir / "base-tree"
    head_tree = out_dir / "head-tree"
    checkout_tree(base, base_tree)
    checkout_tree(head, head_tree)

    total_breaking = 0
    combined = []
    from regreview.cli import main as regreview_main

    for f in files:
        bfile, hfile = base_tree / f, head_tree / f
        report_json = out_dir / (f.replace("/", "__") + ".diff.json")
        report_md = out_dir / (f.replace("/", "__") + ".diff.md")
        argv = ["diff",
                "--base", str(bfile if bfile.exists() else hfile),
                "--head", str(hfile if hfile.exists() else bfile),
                "--format", "json", "--output", str(report_json)]
        if policy:
            argv += ["--policy", policy]
        rc = regreview_main(argv)
        result = json.loads(report_json.read_text())
        regreview_main(["diff",
                        "--base", str(bfile if bfile.exists() else hfile),
                        "--head", str(hfile if hfile.exists() else bfile),
                        "--format", "markdown", "--output", str(report_md)]
                       + (["--policy", policy] if policy else []))
        combined.append({"file": f, "summary": result.get("summary", {}),
                         "changes": result.get("changes", [])})
        total_breaking += result.get("summary", {}).get("breaking", 0)
        for c in result.get("changes", []):
            annotate(c)
        emit_summary(f"## `{f}`\n")
        emit_summary(report_md.read_text())

    (out_dir / "combined.json").write_text(json.dumps(combined, indent=2))
    if outputs_path:
        with open(outputs_path, "a") as f:
            f.write(f"breaking-count={total_breaking}\n")
            f.write(f"report-path={out_dir / 'combined.json'}\n")

    fail_sets = {"breaking": ("breaking",),
                 "behavioural": ("breaking", "behavioural", "uncertain"),
                 "validation-error": ("breaking",),
                 "none": ()}
    trigger = fail_sets.get(fail_on, ("breaking",))
    hits = sum(e["summary"].get(c, 0) for e in combined for c in trigger)
    if hits:
        print(f"regreview: {hits} change(s) at or above '{fail_on}' — failing",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
