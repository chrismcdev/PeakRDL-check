# ADR-0003: SQLite for index storage

Status: accepted (2026-07-13)

## Context

The index must hold ~1M registers' worth of declarations and definitions,
answer interactive queries (children pages, exact path, search, address
ranges) in milliseconds, travel as a build artifact, and support in-place
incremental updates. Candidates considered:

| Candidate | Assessment |
|---|---|
| **SQLite** | single file, ubiquitous (stdlib), transactional, FTS5 built in, B-tree random access, inspectable with standard tools |
| **DuckDB** | excellent analytics, but columnar/OLAP-oriented; point lookups and in-place row splicing are not its shape; extra dependency |
| **LMDB** | fast KV, but no query language, no FTS, secondary indexes by hand; range queries over composite keys require manual encoding |
| **Custom binary format** | maximum control, but every feature (search, ranges, splicing, integrity) reimplemented; opaque to users; high defect surface |
| **Partitioned stores** (file per block) | mirrors the peakrdl-html failure mode: thousands of files, no cross-block queries without a merge layer |

## Decision

One SQLite file per specification (`register-map.sqlite`), schema in
`peakrdl_check/storage.py` (see docs/storage.md).

Deciding factors: portability (Python stdlib, no native deps), true random
access for a virtualized tree UI, FTS5 with contentless tables and
`contentless_delete` for the splicer, transactions for atomic incremental
updates, and inspectability — any engineer can open the artifact with the
`sqlite3` CLI and audit it.

## Evidence

Measured at the 800k mixed fixture (`build/800k-build*.json`):

- write rows: **2.9 s**; deferred index creation: **0.25 s**;
- 85,151 node rows + 67,483 definitions in a **337 MB** single file;
- all interactive query p95s under their targets by **10–100x** (measured via
  `benchmarks/scripts/bench_queries.py`; persisted records accompany the
  full-matrix run), with `EXPLAIN QUERY PLAN` assertions in
  `tests/test_storage.py` guaranteeing index usage doesn't regress.

## Consequences

- Write path uses `journal_mode=OFF` / `synchronous=OFF` — safe because the
  writer always creates a fresh file; the incremental splicer runs inside a
  normal transaction on an existing file.
- FTS5 `contentless_delete` requires SQLite ≥ 3.43 (`peakrdl-check doctor`
  checks; pinned environment ships 3.50.4).
- Addresses stored as zero-padded hex TEXT so B-tree order is numeric order
  without 64-bit integer or float hazards.

## Revisit when

- a single spec's index approaches multi-GB and column-store compression would
  materially matter (DuckDB or SQLite zstd VFS), or
- multi-writer concurrent indexing becomes a requirement (out of scope for a
  local-first review tool).
