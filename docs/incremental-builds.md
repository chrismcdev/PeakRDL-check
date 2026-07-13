# Incremental builds

`regreview build --incremental` reuses an existing index and rebuilds only the
parts affected by changed files. Implementation: `regreview/incremental.py`.

## Unit of incrementality: the block root

A **block root** is the topmost instance whose *defining* source file differs
from the top component's file (determined at build time via the component's
`def_src_ref`, recorded per node as `block_id`). Everything beneath a block
root shares its `block_id` and can be spliced independently.

## Invalidation

- A **sha256 manifest of every tracked input** is stored in `meta.build_inputs`
  at build time. `--incremental` re-hashes all tracked files and diffs digests.
- **Granularity is the defining file**: if any block type defined in file F
  changed, *every* block unit whose type is defined in F is rebuilt — even
  types in F that did not textually change (they are all re-elaborated from
  the one fresh parse of F).
- **Parameter values are recorded per block root** at build time
  (`params` in the block-root list) and **replayed** during standalone
  re-elaboration via `rdlc.elaborate(top_def_name=type, parameters=params)`.
  Roots sharing (type, params) share one re-elaboration.

## The splice

For each affected block instance:

1. delete the old subtree's node rows (root row kept, updated in place),
2. delete the matching FTS rows (`contentless_delete=1` makes this legal),
3. reinsert the freshly elaborated subtree with ids/paths/addresses **rebased**
   onto the unchanged instance base address,
4. insert new definitions/FTS rows as needed, then purge definitions no longer
   referenced by any node (and their `def_search` rows),
5. fix up `reg_count` on every ancestor if the register count changed,
6. refresh `meta` (manifest, counts, block-root register counts, `addr_max`).

## Deterministic fallbacks

Each condition the splicer cannot handle raises `FullRebuildRequired` with a
reported reason (printed to stderr; the CLI then runs a clean build):

| Reason | Why splicing is unsafe |
|---|---|
| top-level file changed | instance layout may differ |
| changed file contains declarations outside any block unit | change is not block-local |
| affected block's total size changed | downstream auto-allocated addresses would shift |
| unsupported parameter values (`params_supported == False`) | standalone elaboration could not reproduce them |
| standalone elaboration failed | cross-file type dependency |
| schema / source-mode mismatch, missing manifest, missing/new input | index not comparable |

There are no heuristics: every fallback is a hard, explainable condition.

## Measured: 800k mixed, one-line edit

One reset value changed in one type file (`800k_types_0.rdl`, ~220k lines,
hosting 200 of the 800 block units):

| Stage | Seconds |
|---|---:|
| hash all tracked inputs | 0.04 |
| standalone re-elaboration (incl. one parse of the changed file) | 33.0 |
| SQLite splice | 0.6 |
| **total** | **33.7** |

Units: 200 rebuilt / 600 reused of 800. Versus the ~210 s clean build
(`build/800k-build.json`) that is a ~6x improvement.

## Honesty: what dominates and what is not skipped

- **Parsing the changed file dominates incremental cost**: 33.0 of the 33.7 s
  is the standalone elaboration stage, which is almost entirely the ANTLR parse
  of the one changed 200k-line type file. The splice itself is 0.6 s.
- Unaffected **files** are never re-parsed — that is the entire point, since
  parse time dominates large builds (190 s of 210 s at 800k).
- But **all types defined in a changed file are re-elaborated**, not just the
  edited one: invalidation granularity is the file, not the type. Splitting
  type definitions across more files buys finer incrementality.

## Equivalence guarantee

An incrementally spliced index must be semantically identical to a clean
rebuild. This is enforced two ways:

- `scripts/verify_incremental_equivalence.py A.sqlite B.sqlite` compares
  canonical dumps — every node keyed by path with kind, addresses, sizes,
  array geometry, register counts, source location, and the full definition
  body. Only `node_id`/`def_id` assignment (a storage detail) may differ.
  Run against the 800k splice vs `build/800k-verify/`: EQUIVALENT.
- `tests/test_incremental.py` asserts splice == clean on every scenario it
  covers (block edit, selective cross-file reuse, register removal with
  ancestor-count fixup, plus the fallback triggers).

## Inspecting the cache

```bash
regreview cache stats build/800k    # units, tracked inputs, db size
regreview cache list  build/800k    # every block root: path, type, regs, file
regreview cache verify build/800k   # which tracked inputs are stale
regreview cache clear build/800k
```
