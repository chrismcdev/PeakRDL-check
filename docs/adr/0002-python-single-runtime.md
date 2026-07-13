# ADR-0002: Single Python runtime (deviation from the brief)

Status: accepted (2026-07-13) — explicit deviation, evidence attached

## Context

The project brief expressed a preference for a Scala 3 / JVM core, with Python
only as a thin front-end shim. The presumption was that index generation and
diffing over ~1M registers would need JVM-class performance.

Two facts changed the calculus once measured:

1. **The front end is necessarily Python.** systemrdl-compiler is the only
   viable SystemRDL 2.0 elaborator, and it is a Python library. Whatever the
   core is written in, parsing + elaboration happens in Python and dominates
   cost (190 s of a 210 s clean 800k build).
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

Ship v1 as a **single Python runtime**. No JVM core.

A JVM core would add, on the critical path, an IPC/serialization boundary to
move the elaborated model (or a dump of it) from Python to the JVM — paying
serialization cost proportional to exactly the data volume the core is meant
to process quickly — plus a second runtime for every user and CI job to
install, version and debug. It would accelerate only the ~5 % of the pipeline
that is already 6x faster than required.

## Consequences

- One `pip install`, one interpreter, one debugging surface; the GitHub Action
  is `setup-python` + `pip install .`.
- Performance-critical Python paths lean on C-backed machinery: sqlite3
  batched executemany, hashlib, sorted-key JSON.
- Accepted risk: if workloads appear where the Python-owned stages (not the
  upstream parser) become the bottleneck, the boundary is clean — everything
  downstream of the canonical model could be reimplemented without touching
  the front end.

## Revisit trigger

Reopen this decision if index generation or diff **misses its performance
target by more than 2x after profiling** (i.e. the shortfall is demonstrably
in PeakRDL-check-owned code, not the upstream parser). Until then, a second
runtime is complexity without a customer.
