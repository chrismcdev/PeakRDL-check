#!/usr/bin/env python3
"""Three measured incremental-rebuild runs at 800k, preserved as raw results.

Each run edits ONE reset literal in one block-type file (a realistic local
block change), runs `regreview build --incremental`, and records the report.
Each run starts from the previous spliced state, which is exactly the
day-to-day editing workflow. The fixture is restored afterwards and a final
equivalence check against a clean build of the restored sources runs in the
test suite (tests/test_incremental.py) and scripts/verify_incremental_equivalence.py.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV = ROOT / ".venv" / "bin"
RAW = ROOT / "benchmarks" / "raw-results"
FIXTURE_DIR = ROOT / "fixtures" / "generated"
TYPES_FILE = FIXTURE_DIR / "800k_types_2.rdl"
OUT = ROOT / "build" / "800k-incbench"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main() -> int:
    backup = TYPES_FILE.read_bytes()
    RAW.mkdir(parents=True, exist_ok=True)
    try:
        # Fresh clean build to seed the incremental state (timed, recorded).
        print("seeding clean 800k build (several minutes)...", flush=True)
        t0 = time.perf_counter()
        p = run([str(VENV / "regreview"), "build", str(FIXTURE_DIR / "800k.rdl"),
                 "--top", "bench800k_top", "--output", str(OUT)])
        assert p.returncode == 0, p.stderr[-2000:]
        seed_s = time.perf_counter() - t0
        print(f"seed build: {seed_s:.0f}s", flush=True)

        for i in range(3):
            text = TYPES_FILE.read_text()
            # flip the i-th reset literal
            ms = list(re.finditer(r"reset = (0x[0-9a-f]+)", text))
            m = ms[i * 7]  # different site each run
            flipped = int(m.group(1), 16) ^ 1
            TYPES_FILE.write_text(text[:m.start()]
                                  + f"reset = {flipped:#x}" + text[m.end():])
            p = run(["/usr/bin/time", "-l", str(VENV / "regreview"), "build",
                     str(FIXTURE_DIR / "800k.rdl"), "--top", "bench800k_top",
                     "--output", str(OUT), "--incremental"])
            assert p.returncode == 0, p.stderr[-2000:]
            report = json.loads(p.stdout[p.stdout.index("{"):])
            for line in p.stderr.splitlines():
                if line.strip().endswith("maximum resident set size"):
                    report["timePeakRssBytes"] = int(line.split()[0])
            report["editedFile"] = str(TYPES_FILE)
            report["editSite"] = i * 7
            report["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            out = RAW / f"incremental-800k-run{i}.json"
            out.write_text(json.dumps(report, indent=2) + "\n")
            print(f"run {i}: {report['totalSeconds']:.1f}s "
                  f"({report['unitsRebuilt']}/{report['unitsTotal']} units, "
                  f"rss {report.get('timePeakRssBytes', 0) / 1e9:.1f}GB) -> {out.name}",
                  flush=True)
    finally:
        TYPES_FILE.write_bytes(backup)
        shutil.rmtree(OUT, ignore_errors=True)
    print("incremental benchmark complete; fixture restored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
