#!/usr/bin/env python3
"""RegReview vs PeakRDL-html build benchmark harness.

Every run is a fresh subprocess (cold process, warm OS file cache — identical
conditions for both tools; see docs/baseline-methodology.md). Each run's raw
record is preserved under benchmarks/raw-results/ as the source of truth;
reports are generated from those files, never hand-edited.

Usage:
  bench.py --fixture 1k,10k,100k --tools regreview,peakrdl-html --runs 3
  bench.py --fixture 800k --tools regreview --runs 3 --timeout 1800
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV = ROOT / ".venv" / "bin"
RAW = ROOT / "benchmarks" / "raw-results"
OUT = ROOT / "benchmarks" / "out"


def hardware() -> dict:
    def sysctl(k):
        try:
            return subprocess.run(["sysctl", "-n", k], capture_output=True,
                                  text=True).stdout.strip()
        except Exception:
            return None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": sysctl("machdep.cpu.brand_string"),
        "cores": sysctl("hw.ncpu"),
        "memBytes": sysctl("hw.memsize"),
        "python": platform.python_version(),
    }


def versions() -> dict:
    out = subprocess.run([str(VENV / "python"), "-c",
                          "import systemrdl, regreview;"
                          "from peakrdl_html.__about__ import __version__ as p;"
                          "print(systemrdl.__version__, p, regreview.__version__)"],
                         capture_output=True, text=True).stdout.split()
    return {"systemrdl-compiler": out[0], "peakrdl-html": out[1],
            "regreview": out[2]} if len(out) == 3 else {}


def run_one(tool: str, fixture: str, run_idx: int, timeout: int,
            source_mode: str) -> dict:
    rdl = ROOT / "fixtures" / "generated" / f"{fixture}.rdl"
    manifest = json.loads((ROOT / "fixtures" / "generated" /
                           f"{fixture}.manifest.json").read_text())
    out_dir = OUT / f"bench-{tool}-{fixture}"
    if out_dir.exists():
        shutil.rmtree(out_dir)

    if tool == "peakrdl-html":
        cmd = [str(VENV / "python"),
               str(ROOT / "benchmarks/scripts/peakrdl_driver.py"),
               str(rdl), str(out_dir), manifest["topComponent"]]
    elif tool == "regreview":
        cmd = [str(VENV / "regreview"), "build", str(rdl),
               "--top", manifest["topComponent"],
               "--source-locations", source_mode,
               "--output", str(out_dir)]
    else:
        raise ValueError(tool)

    time_cmd = ["/usr/bin/time", "-l"] + cmd
    record = {
        "tool": tool,
        "fixture": fixture,
        "fixtureChecksum": manifest["checksums"][f"{fixture}.rdl"],
        "registerCount": manifest["expected"]["registers"],
        "fieldCount": manifest["expected"]["fields"],
        "sourceMode": source_mode if tool == "regreview" else "default",
        "run": run_idx,
        "command": " ".join(cmd),
        "cacheCondition": "cold-process/warm-fs",
        "timeoutSeconds": timeout,
        "hardware": hardware(),
        "runtimeVersions": versions(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    t0 = time.perf_counter()
    try:
        p = subprocess.run(time_cmd, capture_output=True, text=True,
                           timeout=timeout)
        record["wallClockMs"] = round((time.perf_counter() - t0) * 1000)
        record["exitCode"] = p.returncode
        record["timeout"] = False
        # /usr/bin/time -l output on stderr
        for line in p.stderr.splitlines():
            line = line.strip()
            if line.endswith("maximum resident set size"):
                record["timePeakRssBytes"] = int(line.split()[0])
            elif " user " in f" {line} " and "real" in line:
                parts = line.split()
                record["cpuTimeMs"] = round(
                    (float(parts[2]) + float(parts[4])) * 1000)
        # tool's own JSON report: parse the trailing JSON object on stdout
        out = p.stdout.strip()
        start = out.rfind("\n{")
        candidate = out[start + 1:] if start != -1 else (
            out if out.startswith("{") else "")
        if candidate:
            try:
                record["toolReport"] = json.loads(candidate)
            except json.JSONDecodeError:
                pass
        record["stderrTail"] = p.stderr[-2000:] if p.returncode else ""
    except subprocess.TimeoutExpired:
        record["wallClockMs"] = round((time.perf_counter() - t0) * 1000)
        record["exitCode"] = None
        record["timeout"] = True

    if out_dir.exists():
        files = [f for f in out_dir.rglob("*") if f.is_file()]
        record["fileCount"] = len(files)
        record["outputBytes"] = sum(f.stat().st_size for f in files)
    else:
        record["fileCount"] = 0
        record["outputBytes"] = 0

    RAW.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{tool}-{fixture}-run{run_idx}.json"
    (RAW / name).write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True, help="comma-separated: 1k,10k,...")
    ap.add_argument("--tools", default="regreview,peakrdl-html")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--source-mode", default="registers")
    args = ap.parse_args()

    for fixture in args.fixture.split(","):
        for tool in args.tools.split(","):
            for i in range(args.runs):
                r = run_one(tool, fixture, i, args.timeout, args.source_mode)
                status = ("TIMEOUT" if r["timeout"] else
                          f"{r['wallClockMs'] / 1000:.1f}s"
                          + (f" rss={r.get('timePeakRssBytes', 0) / 1e9:.2f}GB"
                             f" files={r['fileCount']}"
                             if not r.get("exitCode") else
                             f" EXIT={r['exitCode']}"))
                print(f"[{tool} {fixture} run{i}] {status}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
