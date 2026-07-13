# ADR-0005: Source location strategy

Status: accepted (2026-07-13)

## Context

Review needs source locations: the diff report and CI annotations point at
`file:line`, and the viewer shows where an instance was declared. Upstream,
systemrdl-compiler's `DirectSourceRef._extract_line_info` (source_ref.py)
**re-reads the source file from position 0 for every line/column lookup** —
O(file size) per reference. At hundreds of thousands of references over
multi-megabyte files this is quadratic-shaped and untenable.

## Decision

1. **Own line index** (`peakrdl_check/lineindex.py`): one O(file size) scan per
   file builds a line-start offset table; each lookup is then a
   `bisect_right` — O(log lines).
2. **Use the resolved path + private offset.** The adapter takes
   `src_ref.path` (which resolves the compiler's segment map, so `` `include
   ``d files attribute correctly) plus the private `_start_idx` character
   offset that exists after segment-map resolution. Offsets are in characters
   (the compiler opens files as UTF-8 text), so the index scan decodes UTF-8
   too.
3. **Fallback.** If the private attribute is unavailable or the file is
   unreadable post-compile, fall back to the upstream slow path (`sr.line`).
   Internals changing degrades performance, not correctness.
4. **Three modes**, because cost should be opt-in:
   - `none` — no locations extracted;
   - `registers` (default) — file/offset for addressable components;
   - `all` — additionally resolves line/column for every location (fields
     inherit their register's location in v1).

## Consequences

- `--source-locations all` at 100k costs a measurable but small increment over
  `registers` (matrix cell exists in `run_full_matrix.sh`); the upstream
  approach would have cost minutes.
- Dependency on a private attribute is contained to one function
  (`_Extractor.src_of`) with a tested fallback.
- **Upstream patch candidacy**: the line-start-table approach is small,
  dependency-free and semantically identical to upstream's slow path — a good
  candidate to contribute to systemrdl-compiler as a fix for
  `_extract_line_info`. Until accepted, PeakRDL-check keeps its own copy.
