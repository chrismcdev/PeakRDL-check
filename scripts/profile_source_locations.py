#!/usr/bin/env python3
"""Profile source-location resolution: upstream scan vs bisect line index.

Measures, on the 100k fixture:
  1. upstream: DirectSourceRef._extract_line_info — re-reads the file from
     position 0 for every lookup (systemrdl-compiler 1.32.2 behaviour);
  2. regreview: SourceLineIndex — one O(file) scan per file, then
     O(log lines) bisect per lookup.

Results feed docs/adr/0005-source-location-strategy.md and the prepared
upstream patch (patches/systemrdl-compiler-line-index.diff).
Raw output: benchmarks/raw-results/source-location-profile.json
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from regreview.lineindex import SourceLineIndex
    from systemrdl.source_ref import DirectSourceRef

    files = sorted((ROOT / "fixtures" / "generated").glob("100k_types_*.rdl"))
    if not files:
        print("run ./scripts/generate-fixtures first", file=sys.stderr)
        return 1

    rng = random.Random(7)
    # sample (file, char_offset) pairs across the type files
    samples = []
    for f in files:
        size = f.stat().st_size
        samples.extend((f, rng.randrange(0, size - 100)) for _ in range(500))
    rng.shuffle(samples)

    n = len(samples)

    # upstream behaviour: fresh DirectSourceRef per lookup, .line scans file
    t0 = time.perf_counter()
    for f, off in samples:
        sr = DirectSourceRef(str(f), off, off + 5)
        _ = sr.line
    upstream_s = time.perf_counter() - t0

    # regreview line index
    idx = SourceLineIndex()
    t0 = time.perf_counter()
    for f, off in samples:
        idx.resolve(str(f), off)
    indexed_s = time.perf_counter() - t0

    # correctness cross-check on a subsample
    mismatches = 0
    for f, off in samples[:200]:
        sr = DirectSourceRef(str(f), off, off + 5)
        line, _col = idx.resolve(str(f), off)
        if sr.line != line:
            mismatches += 1

    out = {
        "lookups": n,
        "files": [str(f.name) for f in files],
        "fileBytes": sum(f.stat().st_size for f in files),
        "upstreamSeconds": round(upstream_s, 3),
        "upstreamPerLookupMs": round(upstream_s / n * 1000, 3),
        "lineIndexSeconds": round(indexed_s, 3),
        "lineIndexPerLookupUs": round(indexed_s / n * 1e6, 2),
        "speedup": round(upstream_s / indexed_s, 1) if indexed_s else None,
        "correctnessMismatches": mismatches,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    raw = ROOT / "benchmarks" / "raw-results" / "source-location-profile.json"
    raw.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
