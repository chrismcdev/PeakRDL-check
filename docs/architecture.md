# Architecture

PeakRDL-check is three pipelines sharing one canonical model: **index build**,
**semantic diff**, and **incremental rebuild**. Everything downstream of the
adapter is independent of systemrdl-compiler internals.

## Build pipeline

```
SystemRDL sources
      │
      ▼
systemrdl-compiler 1.32.2          parse (ANTLR4) + elaborate
      │  elaborated tree
      ▼
adapter (peakrdl_check/adapter.py)     canonical extraction:
      │                            - arrays kept folded (children(unroll=False))
      │                            - definition/instance dedup via content hashing
      │                            - per-stage timings, source locations
      ▼
canonical model (peakrdl_check/canonical.py)
      │  Definition (hash → body) + Decl list (parents before children)
      ▼
SQLite index (peakrdl_check/storage.py)
      │  ONE file: build/<name>/register-map.sqlite
      │  batched inserts, deferred index creation, contentless FTS5
      ▼
local server (peakrdl_check/server.py)  stdlib http.server, localhost-only,
      │                             paginated JSON API, no full-hierarchy responses
      ▼
viewer (peakrdl_check/viewer/)          framework-free single-file SPA,
                                    virtualized tree, textContent-only rendering
```

Only `adapter.py` may import `systemrdl`. Storage, diff, report, server, and
viewer all consume the canonical model or the SQLite index.

### Measured stage timings (800k mixed fixture, clean build)

From `build/800k-build.json` / `800k-build2.json` (representative run):

| Stage | Seconds |
|---|---:|
| parse (ANTLR, upstream) | 190 |
| elaborate (upstream) | 10 |
| traverse (adapter walk + hashing) | 6.6 |
| write rows (SQLite batched inserts) | 2.9 |
| create indexes (deferred) | 0.25 |
| **total** | **~210** |

PeakRDL-check-owned work (traverse + write + index) is under 10 s at 800k
registers; the front-end parser dominates everything else (see
[known-limitations.md](known-limitations.md) and ADR-0002).

## Semantic diff pipeline

```
base sources ──► canonical model ─┐
                                  ├─► matching        (paths, then rename heuristics
head sources ──► canonical model ─┘                    over subtree content hashes)
                                        │
                                        ▼
                                   detection          (structural changes, no opinions)
                                        │
                                        ▼
                                   policy             (peakrdl_check/policy.py, versioned 1.0.0,
                                        │              rule id → classification, JSON overrides)
                                        ▼
                                   explanation        (human message per change)
                                        │
                                        ▼
                                   formats            (text / json / markdown / sarif,
                                                       peakrdl_check/report.py)
```

The stages are deliberately separated: detection states *what* changed; the
policy decides *how much a reviewer should care*; formatters never recompute
anything. Rules and classifications: [diff-rules.md](diff-rules.md).

## Incremental rebuild pipeline

```
content-hash manifest (sha256 per tracked input, stored in meta.build_inputs)
      │  compare
      ▼
changed files ──► affected block roots (units recorded per node at build time)
      │
      ▼
standalone re-elaboration            ONE parse per changed file
      │                              (parameters replayed via elaborate(parameters=))
      ▼
SQLite subtree splice                delete subtree rows → reinsert rebased →
      │                              FTS delete/insert → orphan-definition purge →
      ▼                              ancestor reg_count fixup
equivalence-verified                 scripts/verify_incremental_equivalence.py +
                                     unit tests: spliced index == clean rebuild
```

Any condition the splicer cannot handle raises a deterministic
`FullRebuildRequired` with a reported reason. Details and honest cost
accounting: [incremental-builds.md](incremental-builds.md).

## Key invariants

- **No floats anywhere.** Addresses/offsets/sizes/resets are Python ints in
  memory, zero-padded 32-hex strings on disk (lexicographic == numeric order).
- **Arrays are never materialised.** Element addresses are computed as
  `base + i * stride` at query time.
- **No full-model responses.** Every server endpoint is paginated or
  single-entity; browser state is proportional to what the user expanded.
- **Specs are untrusted input.** JSON-only API, textContent-only viewer,
  traversal-checked static serving (see `SECURITY.md`).

Related reading: [canonical-model.md](canonical-model.md),
[storage.md](storage.md), and the ADRs under `docs/adr/`.
