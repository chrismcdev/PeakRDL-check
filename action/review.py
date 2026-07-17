#!/usr/bin/env python3
"""GitHub Actions review driver.

Runs inside the composite action (or the local simulator with the same
environment variables). Requires no privileged token: it only reads the
repository worktree and writes workflow files.

Changed `include fragments are diffed through the entry files that include
them, never standalone: fragments usually don't elaborate on their own, and
the semantic change only exists in the context of a full register map.

Environment:
    BASE_REF / HEAD_REF   git refs to compare
    RDL_GLOB              entry-file glob (default **/*.rdl)
    FAIL_ON               breaking | behavioural | validation-error | none
    POLICY                optional policy JSON path
    MODE                  review (default) | prime — prime builds and caches
                          indexes for every entry at HEAD_REF without diffing
    PEAKRDL_CHECK_INDEX_CACHE  directory persisted by actions/cache
    GITHUB_STEP_SUMMARY   job summary sink (provided by Actions)
    GITHUB_OUTPUT         step outputs sink (provided by Actions)
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

# GitHub renders at most ~10 annotations per step and truncates huge logs;
# an 800k-register diff can produce tens of thousands of changes.
MAX_ANNOTATIONS = 30
# GITHUB_STEP_SUMMARY is rejected above 1 MiB; leave headroom.
SUMMARY_BUDGET = 800_000
_ANNOTATION_PRIORITY = {"breaking": 0, "behavioural": 1, "uncertain": 2}


_INCLUDE_RE = re.compile(r'^\s*`include\s+"([^"]+)"', re.MULTILINE)


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def changed_rdl_files(base: str, head: str) -> list:
    out = sh("git", "diff", "--name-only", f"{base}...{head}").stdout
    return [l for l in out.splitlines() if l.strip().endswith(".rdl")]


def matches_glob(rel: str, glob: str) -> bool:
    # fnmatch's "**/" does not match files at the repo root; accept both.
    return (fnmatch.fnmatch(rel, glob)
            or (glob.startswith("**/") and fnmatch.fnmatch(rel, glob[3:])))


def entry_closures(tree: Path) -> dict:
    """Map each entry .rdl (not `include`d by another) to its include closure.

    Paths are tree-relative POSIX strings. Includes are resolved relative to
    the including file, matching the compiler's behaviour.
    """
    tree = tree.resolve()
    files = {p.relative_to(tree).as_posix(): p for p in tree.rglob("*.rdl")}
    direct = {}
    for rel, p in files.items():
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            text = ""
        inc = set()
        for name in _INCLUDE_RE.findall(text):
            target = (p.parent / name).resolve()
            try:
                inc.add(target.relative_to(tree).as_posix())
            except ValueError:
                pass  # include outside the tree
        direct[rel] = inc
    included = set().union(*direct.values()) if direct else set()
    closures = {}
    for rel in files:
        if rel in included:
            continue
        seen, stack = {rel}, [rel]
        while stack:
            for nxt in direct.get(stack.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        closures[rel] = seen
    return closures


def affected_entries(base_tree: Path, head_tree: Path, changed: list,
                     glob: str) -> list:
    """Entry files whose include closure intersects the changed files."""
    base_c = entry_closures(base_tree)
    head_c = entry_closures(head_tree)
    changed_set = set(changed)
    out = []
    for rel in sorted(set(base_c) | set(head_c)):
        if not matches_glob(rel, glob):
            continue
        closure = base_c.get(rel, set()) | head_c.get(rel, set())
        if closure & changed_set:
            out.append(rel)
    return out


def checkout_tree(ref: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["git", "archive", ref], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(dest)], input=p.stdout, check=True)


def slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)


class SourceTree:
    """One scratch checkout reused for base and head builds.

    Index build manifests record absolute input paths, so the incremental
    splicer only works when the head sources occupy the same paths the base
    index was built from — hence a single tree that switches revisions.
    """

    def __init__(self, root: Path):
        self.root = root
        self._ref = None

    def at(self, ref: str) -> Path:
        if self._ref != ref:
            import shutil
            if self.root.exists():
                shutil.rmtree(self.root)
            checkout_tree(ref, self.root)
            self._ref = ref
        return self.root


def entry_diff(entry: str, base: str, head: str, tree: SourceTree,
               cache_root: Path, work_dir: Path, policy) -> dict:
    """Diff one entry file via prebuilt indexes.

    Base index: restored from cache_root (persisted across runs via
    actions/cache) or built once from the base tree. Head index: a copy of
    the base index incrementally re-spliced with the changed files — no full
    recompile unless the incremental invariants don't hold.
    """
    import shutil

    from systemrdl import RDLCompileError

    from peakrdl_check.cli import _diff_result, main as cli_main
    from peakrdl_check.diff import compile_failed_result
    from peakrdl_check.incremental import FullRebuildRequired, incremental_build

    slug = slugify(entry)
    base_idx = cache_root / f"{slug}@{slugify(base)}"
    if not (base_idx / "register-map.sqlite").is_file():
        print(f"peakrdl-check: base index cache miss for {entry}@{base}; building")
        try:
            rc = cli_main(["build", str(tree.at(base) / entry), "-o",
                           str(base_idx), "--source-locations", "all"])
        except RDLCompileError as e:
            return compile_failed_result("base", str(e))
        if rc:
            return compile_failed_result("base", f"build exited with {rc}")
    else:
        print(f"peakrdl-check: base index cache hit for {entry}@{base}")

    head_idx = work_dir / f"head-index--{slug}"
    head_idx.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base_idx / "register-map.sqlite",
                    head_idx / "register-map.sqlite")
    tree.at(head)
    try:
        report = incremental_build([str(tree.root / entry)], head_idx,
                                   None, "all")
        print(f"peakrdl-check: incremental head index: "
              f"{report.get('unitsRebuilt', 0)} unit(s) rebuilt, "
              f"{report.get('unitsReused', 0)} reused "
              f"in {report.get('totalSeconds')}s")
    except FullRebuildRequired as e:
        print(f"peakrdl-check: incremental splice unavailable ({e.reason}); "
              f"full head build")
        try:
            rc = cli_main(["build", str(tree.root / entry), "-o",
                           str(head_idx), "--source-locations", "all"])
        except RDLCompileError as err:
            return compile_failed_result("head", str(err))
        if rc:
            return compile_failed_result("head", f"build exited with {rc}")

    result, _ = _diff_result(SimpleNamespace(
        base=str(base_idx), head=str(head_idx), policy=policy))
    return result


def prime(head: str, glob: str, work_dir: Path, cache_root: Path,
          emit_summary) -> int:
    """Build and cache an index for every entry file at HEAD_REF.

    Run on pushes to the default branch (base-ref == head-ref == the pushed
    sha) so pull-request reviews always find a warm base index.
    """
    from systemrdl import RDLCompileError

    from peakrdl_check.cli import main as cli_main

    head_tree = work_dir / "prime-tree"
    checkout_tree(head, head_tree)
    entries = [e for e in sorted(entry_closures(head_tree))
               if matches_glob(e, glob)]
    tree = SourceTree(work_dir / "src-tree")
    lines = [f"### PeakRDL-check index prime for `{head}`", ""]
    failed = 0
    for entry in entries:
        idx_dir = cache_root / f"{slugify(entry)}@{slugify(head)}"
        if (idx_dir / "register-map.sqlite").is_file():
            lines.append(f"- `{entry}` — already cached")
            continue
        try:
            rc = cli_main(["build", str(tree.at(head) / entry), "-o",
                           str(idx_dir), "--source-locations", "all"])
        except RDLCompileError as e:
            rc = 1
            print(f"peakrdl-check: prime build of {entry} failed: {e}")
        if rc:
            failed += 1
            lines.append(f"- `{entry}` — **build failed**")
        else:
            lines.append(f"- `{entry}` — index built and cached")
    emit_summary("\n".join(lines))
    return 1 if failed else 0


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

    out_dir = Path("peakrdl-check-out")          # uploaded as the artifact
    out_dir.mkdir(exist_ok=True)
    work_dir = Path("peakrdl-check-work")        # scratch trees and indexes
    work_dir.mkdir(exist_ok=True)
    cache_root = Path(os.environ.get("PEAKRDL_CHECK_INDEX_CACHE")
                      or (work_dir / "index-cache"))

    changed = changed_rdl_files(base, head)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    outputs_path = os.environ.get("GITHUB_OUTPUT")

    def emit_summary(text: str):
        if summary_path:
            with open(summary_path, "a") as f:
                f.write(text + "\n")
        else:
            print(text)

    def emit_outputs(breaking: int, report: str):
        if outputs_path:
            with open(outputs_path, "a") as f:
                f.write(f"breaking-count={breaking}\n")
                f.write(f"report-path={report}\n")

    if os.environ.get("MODE", "review") == "prime":
        rc = prime(head, glob, work_dir, cache_root, emit_summary)
        emit_outputs(0, "")
        return rc

    if not changed:
        emit_summary("### PeakRDL-check\n\nNo SystemRDL changes detected.")
        emit_outputs(0, "")
        return 0

    base_tree = work_dir / "base-tree"
    head_tree = work_dir / "head-tree"
    checkout_tree(base, base_tree)
    checkout_tree(head, head_tree)

    files = affected_entries(base_tree, head_tree, changed, glob)
    if not files:
        emit_summary("### PeakRDL-check\n\nChanged SystemRDL files "
                     f"({', '.join(f'`{c}`' for c in changed)}) match no "
                     f"entry file for glob `{glob}`.")
        emit_outputs(0, "")
        return 0

    total_breaking = 0
    combined = []
    all_changes = []
    summary_used = 0
    tree = SourceTree(work_dir / "src-tree")
    from peakrdl_check.report import FORMATTERS

    for f in files:
        bfile, hfile = base_tree / f, head_tree / f
        # An added or removed register map has nothing to diff against:
        # compiling one side against itself costs two full compiles for a
        # guaranteed-empty result (minutes and ~10 GB on very large maps).
        if not (bfile.is_file() and hfile.is_file()):
            state = "added" if hfile.is_file() else "removed"
            combined.append({"file": f, "state": state, "summary": {},
                             "changes": []})
            entry = (f"## `{f}`\n\n**Register map {state}** — "
                     "no base revision to compare against.\n")
            summary_used += len(entry)
            emit_summary(entry)
            continue
        report_json = out_dir / (f.replace("/", "__") + ".diff.json")
        report_md = out_dir / (f.replace("/", "__") + ".diff.md")
        # Diff prebuilt indexes: the base index is cached across runs, the
        # head index is an incremental splice of the changed files onto it.
        # Compiling SystemRDL from scratch (minutes and ~10 GB at 800k
        # registers) only happens on a cold cache or when the incremental
        # invariants don't hold.
        result = entry_diff(f, base, head, tree, cache_root, work_dir, policy)
        report_json.write_text(FORMATTERS["json"](result))
        md = FORMATTERS["markdown"](result)
        report_md.write_text(md)
        combined.append({"file": f, "summary": result.get("summary", {}),
                         "changes": result.get("changes", [])})
        total_breaking += result.get("summary", {}).get("breaking", 0)
        all_changes.extend(result.get("changes", []))
        # The job summary has a hard 1 MiB cap: oversized reports degrade to
        # counts plus a pointer at the uploaded artifact.
        entry = f"## `{f}`\n\n"
        if summary_used + len(entry) + len(md) <= SUMMARY_BUDGET:
            entry += md
        else:
            counts = ", ".join(f"{v} {k}" for k, v in result.get("summary", {}).items())
            entry += (f"**{counts or 'no changes'}** — report too large for the "
                      "job summary; see the `peakrdl-check-report` artifact.\n")
        summary_used += len(entry)
        emit_summary(entry)

    all_changes.sort(key=lambda c: _ANNOTATION_PRIORITY.get(c["classification"], 3))
    for c in all_changes[:MAX_ANNOTATIONS]:
        annotate(c)
    if len(all_changes) > MAX_ANNOTATIONS:
        print(f"peakrdl-check: annotations capped at {MAX_ANNOTATIONS} "
              f"({len(all_changes) - MAX_ANNOTATIONS} more in the report artifact)")

    (out_dir / "combined.json").write_text(json.dumps(combined, indent=2))
    emit_outputs(total_breaking, str(out_dir / "combined.json"))

    fail_sets = {"breaking": ("breaking",),
                 "behavioural": ("breaking", "behavioural", "uncertain"),
                 "validation-error": ("breaking",),
                 "none": ()}
    trigger = fail_sets.get(fail_on, ("breaking",))
    hits = sum(e["summary"].get(c, 0) for e in combined for c in trigger)
    if hits:
        print(f"peakrdl-check: {hits} change(s) at or above '{fail_on}' — failing",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
