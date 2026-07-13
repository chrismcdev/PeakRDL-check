# Benchmarking

How to run the benchmark suite and what the outputs mean. The measurement
philosophy (cache condition, fairness, medians) is in
[baseline-methodology.md](baseline-methodology.md).

## Entry points

### `peakrdl-check benchmark`

Convenience wrapper around the harness:

```bash
peakrdl-check benchmark --fixture 1k --runs 3                    # peakrdl-check only
peakrdl-check benchmark --fixture 100k --compare peakrdl-html    # head-to-head
```

### `benchmarks/scripts/bench.py` — build benchmark

```bash
.venv/bin/python benchmarks/scripts/bench.py \
    --fixture 1k,10k,100k        # comma-separated fixture names
    --tools peakrdl-check,peakrdl-html
    --runs 3                     # runs per (tool, fixture) cell
    --timeout 1800               # seconds; expirations recorded as timeouts
    --source-mode registers      # peakrdl-check: none | registers | all
```

Each run: fresh subprocess wrapped in `/usr/bin/time -l`, output directory
wiped first, raw JSON record written to `benchmarks/raw-results/`.

### `benchmarks/scripts/bench_queries.py` — interactive benchmark

```bash
.venv/bin/python benchmarks/scripts/bench_queries.py <index-dir> <label> [reps]
# e.g.
.venv/bin/python benchmarks/scripts/bench_queries.py build/800k 800k 200
```

Measures, against a live `peakrdl-check serve` process:

- server-ready time (process spawn → `/api/ready`), 5 fresh processes;
- first usable viewer response (shell + metadata + first tree page);
- p50/p95/max for exact lookup, register detail, children page, search, and
  address range over N keep-alive requests with **seeded randomised
  parameters** — so results are not flattered by SQLite page-cache hits on a
  single hot row. All samples are preserved in the raw record.

### `benchmarks/scripts/run_full_matrix.sh` — the whole matrix

```bash
benchmarks/scripts/run_full_matrix.sh
```

Runs sequentially (measurements never contend): both tools at 1k/10k/100k/400k,
peakrdl-check and peakrdl-html at 800k (30-minute timeout each), the three
source-location modes at 100k, the unique-register profile at 10k, then the
interactive query benchmarks.

### `scripts/mutation_tests.py` — diff-engine accuracy

```bash
.venv/bin/python scripts/mutation_tests.py 240
```

Generates a seeded base spec with explicit addresses, applies one known
mutation per trial from a 12-entry catalogue (8 semantic, 4 neutral), and
scores recall / precision / neutral suppression against ground truth. Results:
`benchmarks/raw-results/mutation-results.json` (last run: 240 trials, recall
1.0, precision 1.0, neutral suppression 1.0).

### `scripts/run_corpus.py` — semantic-diff corpus

```bash
.venv/bin/python scripts/run_corpus.py            # all 47 scenarios
.venv/bin/python scripts/run_corpus.py rename     # substring filter
```

Scores every scenario in `diff-corpus/scenarios/` against its `expected.json`
and writes per-scenario `git.diff` / `semantic-diff.json` / `semantic-diff.md`
plus a corpus-wide `diff-corpus/results.json`. Exit 1 on any failure.

## Raw-results file format

One JSON file per run: `benchmarks/raw-results/<timestamp>-<tool>-<fixture>-run<N>.json`.

| Key | Meaning |
|---|---|
| `tool`, `fixture`, `run` | cell identity |
| `fixtureChecksum` | sha256 of the fixture entry file (ties the run to exact input bytes) |
| `registerCount`, `fieldCount` | expected entity counts from the manifest |
| `command` | exact command executed |
| `cacheCondition` | always `cold-process/warm-fs` |
| `timeoutSeconds`, `timeout`, `exitCode` | limits and outcome; timeouts kept, not discarded |
| `hardware` | platform, CPU, cores, memory, Python version |
| `runtimeVersions` | systemrdl-compiler / peakrdl-html / peakrdl-check versions |
| `wallClockMs`, `cpuTimeMs`, `timePeakRssBytes` | from the harness and `/usr/bin/time -l` |
| `toolReport` | the tool's own JSON (stage timings, db size, file count) |
| `fileCount`, `outputBytes` | measured from the output tree |
| `stderrTail` | preserved on failure |

Interactive records (`*-interactive-<label>.json`) carry startup trials, and
per-suite p50/p95/max plus **every individual sample**.

## Integrity rules

These were followed for every number quoted in this documentation set:

1. Same machine, same venv, pinned versions for all runs
   (`docs/pinned-versions.txt`).
2. Raw logs preserved — including failures and timeouts. A timeout is a
   result, not an excuse to rerun until it passes.
3. Medians reported, never best runs.
4. No hand-edited outputs: raw records are written only by the harness;
   summaries are derived from them.
5. Report generation is separate from execution.
