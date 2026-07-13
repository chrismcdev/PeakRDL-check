# Implementation plan (as executed)

The phased plan for PeakRDL-check v0.1, recorded **as it was actually executed**
on 2026-07-13, with what each phase delivered and the evidence gate it had to
pass. Gates were defined up front; a phase did not proceed until its gate held
(gate F remains open — see [progress.md](progress.md)).

## Phases

### Phase 0 — Environment and pins
Pinned toolchain (Python 3.12.12, systemrdl-compiler 1.32.2, peakrdl-html
2.12.2, full pins in `docs/pinned-versions.txt`), `peakrdl-check doctor`
environment checks, benchmark integrity rules agreed
(`docs/baseline-methodology.md`).

### Phase 1 — Ecosystem inspection and baseline reproduction
Read systemrdl-compiler and peakrdl-html sources; confirmed the file-count
explosion and eager full-model memory behaviour still present in current
releases; measured baselines at 1k/10k/100k/uniq10k
(`docs/ecosystem-review.md`, `docs/problem-reproduction.md`).
**Gate A ✓ — baseline problems reproduced on current versions, raw records
preserved.**

### Phase 2 — Fixture generator
Deterministic, seeded SystemRDL generator (`peakrdl_check/fixture_gen.py`) with
exact analytic register counts, sha256 manifests, and a `verify` subcommand
that re-derives counts from the elaborated model. Mixed-realistic and
unique-register profiles.

### Phase 3 — Canonical model + adapter
`canonical.py` / `adapter.py`: folded arrays, content-hash dedup,
per-instance extraction (identity cache measured and rejected), per-stage
timings, source-location modes with the bisect line index (`lineindex.py`).

### Phase 4 — SQLite storage
Schema v1 (`storage.py`): one file per spec, batched writes, deferred
indexes, contentless FTS5 with `contentless_delete`, EXPLAIN-verified plans.
**Gate B ✓ — 100k vertical slice: build → serve → browse worked end to end.**

### Phase 5 — Local server
Stdlib HTTP server, localhost-only, paginated JSON API, security clamps;
TCP_NODELAY/buffering fix eliminating the flat ~50 ms keep-alive penalty
(ADR-0008).

### Phase 6 — Viewer
Framework-free single-file SPA with hand-rolled virtualization, textContent-
only rendering, `window.__peakrdl-checkPerf` instrumentation. Verified
interactively against the 800k index.
**Gate C ✓ — 800k index built (~210 s total, PeakRDL-check-owned stages ≈ 9.6 s)
and browsable with sub-millisecond API p95s.**

### Phase 7 — Semantic diff engine
Matching (subtree content hashes, honest rename policy), detection, versioned
severity policy (1.0.0), explanation, four output formats
(text/json/markdown/sarif); def-pair comparison caching; container-move
propagation collapse.

### Phase 8 — Diff corpus
47 scenarios across breaking / behavioural / compatible / neutral / difficult
with machine-checked `expected.json` ground truth; runner writes per-scenario
git diff vs semantic diff artifacts.
**Gate D ✓ — 47/47 scenarios pass (`diff-corpus/results.json`).**

### Phase 9 — Incremental builds
Block-root units, sha256 manifest invalidation, parameter replay, SQLite
subtree splice, deterministic fallbacks, equivalence verifier.
**Gate E ✓ — 800k one-line edit rebuilt in 33.7 s (200/800 units), spliced
index verified equivalent to a clean rebuild.**

### Phase 10 — Hardening and accuracy
Security test suite (XSS, traversal, clamps, FTS injection, deep/hostile
inputs), mutation harness (240 trials: recall 1.0, precision 1.0, neutral
suppression 1.0), CLI surface (`doctor`, `cache`, `query`, `check`,
`benchmark`), 56-test suite green.

### Phase 11 — CI integration
GitHub composite action (`action/action.yml` + `review.py`): changed-file
detection, per-file semantic diffs, job summary, source annotations,
severity-threshold exit codes, artifact upload.
**Gate G ✓ — exercised via local simulation
(`scripts/simulate_pr_workflow.sh`): breaking PR fails with annotations and
summary; docs-only PR passes. Evidence in
`benchmarks/raw-results/pr-workflow-simulation/`.** (Hosted-runner execution
remains a known limitation.)

### Phase 12 — Benchmark harness and documentation
`bench.py` / `bench_queries.py` / `run_full_matrix.sh`, raw-record format,
this documentation set and the ADRs.
**Gate F — pending: the full benchmark matrix run (all cells, 3 runs each)
has not yet been executed end to end.** Individual cells measured so far are
preserved in `benchmarks/raw-results/` and `build/`.

## Gate summary

| Gate | Criterion | Status |
|---|---|---|
| A | Baseline problems reproduced on current versions | ✓ |
| B | 100k vertical slice (build → serve → browse) | ✓ |
| C | 800k index built and browsable | ✓ |
| D | Diff corpus green (47 scenarios) | ✓ |
| E | Incremental 800k edit ≪ clean build, equivalence verified | ✓ (33.7 s) |
| F | Full benchmark matrix executed and reported | pending |
| G | CI action exercised end to end | ✓ (local simulation) |
