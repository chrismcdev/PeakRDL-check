# ADR-0002: Single Python runtime

Status: accepted (2026-07-13)

## Context

Two facts determine the runtime choice:

1. **The front end is necessarily Python.** systemrdl-compiler is the only
   viable SystemRDL 2.0 elaborator, and it is a Python library. Parsing and
   elaboration therefore happen in Python and dominate cost (190 s of a 210 s
   clean 800k build).
2. **The Python-owned portion already beats its target by ~6x.** Index
   generation from an elaborated model — traverse + hash + write + index — was
   measured at **9.0–9.8 s at 800k registers** (`build/800k-build.json`:
   6.40 + 2.40 + 0.25 = 9.05 s; `800k-build2.json`: 6.63 + 2.92 + 0.23 =
   9.77 s; a third, noisier run totalled 12.3 s — still 5x under target)
   against a 60 s target. Diffing and query latencies also meet their targets
   with large margin (query p95s measured 10–100x under target via
   `benchmarks/scripts/bench_queries.py`; the persisted interactive records
   land in `benchmarks/raw-results/` with the full-matrix run, Gate F).

## Decision

Ship v1 as a **single Python runtime**. Keep the elaborated model in-process
through canonicalization, indexing, and semantic comparison. The measured
Python-owned stages already exceed their performance targets, so an additional
runtime boundary is not justified.

## Consequences

- One `pip install`, one interpreter, one debugging surface; the GitHub Action
  is `setup-python` + `pip install .`.
- Performance-critical Python paths lean on C-backed machinery: sqlite3
  batched executemany, hashlib, sorted-key JSON.
- Accepted risk: if workloads appear where the Python-owned stages, rather than
  the upstream parser, become the bottleneck, the canonical model provides a
  clean optimization boundary.

## Revisit trigger

Reopen this decision if index generation or diff **misses its performance
target by more than 2x after profiling** and the shortfall is demonstrably in
PeakRDL-check-owned code rather than the upstream parser.
