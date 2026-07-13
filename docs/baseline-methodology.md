# Baseline measurement methodology

How the peakrdl-html baseline (and every RegReview number compared against it)
is measured. The goal is a comparison that is fair, reproducible, and auditable
from raw files.

## Fixed environment

- **Same machine for everything**: Apple M4 Pro (14 cores), 24 GB, macOS 26.5.1.
- **Same virtualenv**: both tools import the same `systemrdl-compiler==1.32.2`,
  so parse/elaborate costs are identical by construction. Full pins:
  `docs/pinned-versions.txt`, plus per-run `runtimeVersions` in each raw record.
- **Identical inputs**: both tools consume the same generated fixture files.
  Every fixture ships a manifest (`fixtures/generated/<name>.manifest.json`)
  with sha256 checksums of each file, the generator parameters/seed, and the
  analytically expected entity counts. Each benchmark record embeds the
  fixture checksum it ran against (`fixtureChecksum`).

## Cache condition: cold-process / warm-fs

Every run is a **fresh subprocess** (no Python-level caching survives between
runs), executed after the OS file cache has already seen the fixture files.
This is recorded as `"cacheCondition": "cold-process/warm-fs"` in every raw
record.

Why not true cold-filesystem? Purging the macOS file cache requires
`sudo purge` per run, which is impractical for an unattended matrix and adds
its own variance. More importantly it would not change the comparison: the OS
cache is warm **for both tools equally**, and both read the same input bytes
through the same compiler. Warm-fs removes disk noise from the measurement
while keeping the process-level costs (interpreter start, import, parse,
elaborate, export) fully cold — which is what a CI job or a developer's first
build of the day actually pays.

## Timing and memory

- Wall time and peak RSS come from `/usr/bin/time -l` wrapping the subprocess
  (`maximum resident set size`, bytes on macOS). The harness also records its
  own wall clock and the tool's self-reported timings.
- **Staged timing for peakrdl-html** uses
  `benchmarks/scripts/peakrdl_driver.py`, which performs exactly what
  `peakrdl html <in> -o <out>` does (RDLCompiler + `HTMLExporter().export`
  with default options) but times compile / elaborate / export separately and
  emits a JSON record. Parity with the real CLI was verified by comparing wall
  time and output trees.
- **RegReview reports its own stage timings** (`parseSeconds`,
  `elaborateSeconds`, `traverseSeconds`, `writeRowsSeconds`,
  `createIndexSeconds`) in its build report, captured into the same record.

## Runs, aggregation, integrity

- **3 runs minimum** per (tool, fixture) cell; **medians** are reported, never
  best-of.
- **One raw JSON file per run** is written to `benchmarks/raw-results/`
  (timestamped, e.g. `20260713-131323-regreview-1k-run0.json`). These are the
  source of truth; report tables are generated from them and never hand-edited.
- **Timeouts are recorded as timeouts** (`"timeout": true`), not discarded.
  Default timeout 1800 s (`--timeout` on `bench.py`).
- Failures keep their exit code and a stderr tail in the record.
- **Report generation is strictly separate from execution**: the harness only
  writes raw records; anything summarised is derived afterwards from those
  files.

## Commands

```bash
# One cell of the matrix
.venv/bin/python benchmarks/scripts/bench.py \
    --fixture 100k --tools regreview,peakrdl-html --runs 3 --timeout 1800

# The whole matrix (sequential, so measurements never contend)
benchmarks/scripts/run_full_matrix.sh

# Interactive/query latency benchmark against a built index
.venv/bin/python benchmarks/scripts/bench_queries.py build/100k 100k 200
```

See [benchmarking.md](benchmarking.md) for the full flag reference and the raw
record format.
