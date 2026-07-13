# ADR-0006: Incremental-build boundaries

Status: accepted (2026-07-13)

## Context

Clean builds are parser-bound (190 s of 210 s at 800k). The only meaningful
incremental win is *not re-parsing unchanged files*. That requires a unit of
work that (a) can be re-elaborated standalone from its own file, and (b) can
be spliced back into the index without disturbing neighbours.

## Decision

- **Unit = block root**: the topmost instance whose defining file (via
  `original_def.def_src_ref`) differs from the top component's file. Recorded
  per node (`block_id`) at build time; the block-root list (type, file,
  params, size, regs) is stored in `meta`.
- **Invalidation granularity = defining file**, tracked by a sha256 manifest
  of all inputs. A changed file invalidates every unit whose type it defines;
  all types in that file are re-elaborated from one fresh parse
  (`build_canonical_many` / one `RDLCompiler` per changed file).
- **Parameters are replayed**: resolved parameter values recorded per root at
  build time are passed to `elaborate(parameters=...)`; roots whose values
  are not representable (`params_supported=False`) force a full rebuild.
- **Splice, don't rebuild**: delete subtree rows, reinsert rebased onto the
  unchanged instance base address, fix FTS and ancestor counts, purge orphan
  definitions — all in one transaction.
- **Deterministic fallbacks, each with a reported reason** (top file changed;
  declarations outside blocks; unit size changed; unsupported params;
  standalone elaboration failure; schema/mode mismatch). No heuristics: when
  in doubt, full rebuild and say why.

## Why not AST-level caching?

The tempting alternative — serialize parsed ASTs / the compiler's namespace
and re-elaborate only the edited type — fails on upstream reality: the ANTLR
parse tree and systemrdl-compiler's namespace objects are **not serializable**
(interlinked Python objects with parser context, no stable pickle contract
across versions). Building and maintaining a custom serializer for a private
representation would be more code than the rest of the incremental system and
would break on every upstream release. File-level parse granularity is what
the upstream API actually supports.

## Consequences

- Measured: one-line edit at 800k = 33.7 s vs ~210 s clean (~6x), with the
  remaining cost dominated by the ANTLR parse of the one changed 200k-line
  file (docs/incremental-builds.md).
- Users control incremental granularity through file organisation: more,
  smaller type files → finer invalidation.
- Correctness is enforced, not assumed: spliced index must equal a clean
  rebuild (`scripts/verify_incremental_equivalence.py`, unit tests).
