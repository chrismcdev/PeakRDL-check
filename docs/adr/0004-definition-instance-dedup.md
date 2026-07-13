# ADR-0004: Definition/instance dedup with folded arrays

Status: accepted (2026-07-13)

## Context

Large SoCs reach huge register counts through repetition: arrays (channel
banks, descriptor rings) and repeated IP blocks. A representation that
materialises every elaborated register pays for that repetition everywhere —
peakrdl-html's per-node output is the cautionary example (10,603 files at 100k
registers).

## Decision

Two orthogonal dedup mechanisms:

1. **Folded arrays.** One `Decl` (one `node` row) per declared array, storing
   dimensions and stride. Element addresses are computed as
   `base + flat_index * stride` at query time; elements never exist as rows.
2. **Content-hashed definitions.** The elaborated body of each component is
   hashed (sha256 over canonical JSON); instances reference definitions by
   hash. Identical content is stored once regardless of instance count.

With one hard rule: **never merge differing semantics.** Anything that changes
effective behaviour — a dynamic property assignment, a parameter-dependent
field, a different description — changes the body, changes the hash, and gets
its own definition. Dedup is a consequence of exact content equality, never a
heuristic. (This is why the `id(original_def)` extraction cache was rejected —
see ADR-0001.)

## Evidence

800k-register mixed fixture (`build/800k-build.json`):

- 800,000 registers → **85,151 node rows + 67,483 definitions**;
- write time **2.9 s**, single **337 MB** file;
- the row count — and therefore write time, index size and query working set —
  scales with source-level declarations, not elaborated registers.

## Consequences

- Query layer must understand folded paths (`blk[2].ctrl[5]`) — implemented in
  `RegIndex.node_by_path` with per-segment index validation.
- Address-range queries intersect arrayed footprints (`addr`/`addr_end`) and
  report the element sub-range that falls inside the window.
- Shared-type diffs are computed once per definition pair and fanned out per
  instance (docs/diff-rules.md).
- Limitation accepted: per-array-element property overrides are not
  representable in the folded form (docs/known-limitations.md).
