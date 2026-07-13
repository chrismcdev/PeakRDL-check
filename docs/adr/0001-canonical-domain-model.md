# ADR-0001: Tool-independent canonical domain model

Status: accepted (2026-07-13)

## Context

Every PeakRDL-check feature — storage, browsing, semantic diff, incremental
rebuilds — needs a representation of the elaborated register map. The obvious
shortcut is to pass systemrdl-compiler's node objects around. That couples
every module to upstream internals (which change), makes content comparison
depend on object identity, and drags the full elaborated object graph into
memory wherever any consumer runs.

## Decision

Define a small canonical model (`peakrdl_check/canonical.py`) that only the
adapter produces and everything else consumes:

1. **Definition** — the deduplicated elaborated *content* of a component,
   identified by a sha256 hash of its canonical JSON body. Two instances with
   different effective semantics hash differently and are never merged.
2. **Decl** — one row per *declared* instance, arrays kept folded
   (dimensions + stride); element addresses are computed arithmetically, never
   materialised.
3. **Per-instance extraction, content-hash dedup.** Extraction always runs per
   declared instance; dedup happens through hashing, which is exact. An
   `id(original_def)`-keyed extraction cache was measured (saved < 0.2 s at
   100k registers) and rejected: SystemRDL dynamic property assignments mean
   two instances of one `original_def` can differ semantically, and an
   identity-keyed cache would silently merge them.
4. **Ints only.** Addresses, offsets, sizes, resets, masks are
   arbitrary-precision Python ints in memory and zero-padded fixed-width hex
   strings on disk (lexicographic order == numeric order). Floats are banned.

## Consequences

- Storage, diff, report, server and viewer have zero dependency on
  systemrdl-compiler; only `adapter.py` imports it.
- Model size is proportional to *declarations*, not elaborated registers:
  800k registers → 85,151 Decls + 67,483 Definitions.
- Content hashing gives the diff engine exact "content identical" evidence,
  which is what makes honest rename detection possible (ADR-0007).
- Cost accepted: extraction work is O(instances) even when types repeat —
  measured at < 0.2 s of overhead at 100k, a fair price for correctness.
- `CANONICAL_SCHEMA_VERSION` gates cached artifacts; any change to the
  representation or hashing scheme bumps it.
