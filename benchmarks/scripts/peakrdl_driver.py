#!/usr/bin/env python3
"""Staged PeakRDL-html driver for benchmarking.

Performs exactly what `peakrdl html <in> -o <out>` does (RDLCompiler +
peakrdl_html.HTMLExporter with default options) but times compile,
elaborate and export separately and emits a JSON record on stdout.

Parity with the CLI was verified by comparing wall time and output trees
(see docs/baseline-methodology.md).
"""

import json
import resource
import sys
import time
from pathlib import Path


def main() -> int:
    src, out = sys.argv[1], sys.argv[2]
    top = sys.argv[3] if len(sys.argv) > 3 else None

    from systemrdl import RDLCompiler
    from peakrdl_html import HTMLExporter
    from peakrdl_html import __about__ as peakrdl_html_about
    import systemrdl

    t0 = time.perf_counter()
    rdlc = RDLCompiler()
    rdlc.compile_file(src)
    t1 = time.perf_counter()
    root = rdlc.elaborate(top_def_name=top)
    t2 = time.perf_counter()
    HTMLExporter().export(root, out)
    t3 = time.perf_counter()

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        rss *= 1024

    out_path = Path(out)
    file_count = sum(1 for p in out_path.rglob("*") if p.is_file())
    out_bytes = sum(p.stat().st_size for p in out_path.rglob("*") if p.is_file())

    print(json.dumps({
        "tool": "peakrdl-html",
        "toolVersion": peakrdl_html_about.__version__,
        "systemrdlVersion": systemrdl.__version__,
        "parseMs": round((t1 - t0) * 1000),
        "elaborationMs": round((t2 - t1) * 1000),
        "generationMs": round((t3 - t2) * 1000),
        "wallClockMs": round((t3 - t0) * 1000),
        "peakRssBytes": rss,
        "outputBytes": out_bytes,
        "fileCount": file_count,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
