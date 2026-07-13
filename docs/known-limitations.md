# Known limitations

An honest list. Each item is a real, current constraint of PeakRDL-check v0.1 —
not a roadmap promise.

## Performance

- **Cold builds are parser-bound.** The ANTLR4 parse inside systemrdl-compiler
  costs ~190 s at the 800k mixed fixture; everything PeakRDL-check adds (traverse,
  write, index) is under 10 s. PeakRDL-check cannot make first builds fast — it
  makes them *pay off* (one-file index, sub-millisecond queries, incremental
  rebuilds).
- **Mostly-unique register profiles are far worse upstream.** The 10k
  unique-register fixture costs ~19 s just to parse+elaborate (vs ~4 s for 10k
  mixed): with no shared types the compiler deep-copies every definition. A
  unique-800k fixture is impractical to even elaborate upstream, so no such
  cell exists in the benchmark matrix. PeakRDL-check's dedup helps storage and
  queries, but cannot recover the front-end cost.

## Incremental builds

- **Granularity is the defining file, not the type.** Editing one type in a
  200k-line type file re-elaborates every block type defined in that file
  (33.0 s of the 33.7 s measured one-line-edit rebuild at 800k). Unaffected
  files are never re-parsed, but a monolithic type file caps the win.
- **Per-array-element dynamic property overrides are not distinguished.**
  Arrays are folded to one Decl sharing one definition; a per-element override
  that changes semantics of a single element would not be representable. (The
  fixture generator and the corpus do not exercise this pattern; upstream
  non-unrolled traversal reports the folded view.)

## Model / diff

- **Alias information is not persisted into storage.** `Decl.is_alias` exists
  in the canonical model and the diff engine uses it (`REG-ALIAS-ADDED`), but
  the `node` table has no alias column — the viewer cannot mark aliases. Diff
  works from source, so review results are unaffected.
- **Enum dedup is at definition level.** Enumerations live inside the
  content-hashed register definition; renaming an enum member inside a shared
  type changes the definition and therefore reports against **all** instances
  of that type (correct for review, but there is no notion of "just one
  instance's enum").
- **Field-level source locations are approximate.** In v1 fields inherit
  their register's location; `line/column` for the exact field declaration is
  not resolved (see ADR-0005).

## Deployment / integration

- **Server mode only.** A static in-browser mode (SQLite-WASM, no server) was
  deliberately deferred — see [ADR-0008](adr/0008-server-mode-first.md). The
  `--mode static` CLI flag is accepted but currently produces the same
  server-mode index.
- **The GitHub Action is exercised via local simulation, not a hosted
  runner.** `scripts/simulate_pr_workflow.sh` runs `action/review.py` with
  `GITHUB_STEP_SUMMARY`/`GITHUB_OUTPUT` wired to files and asserts
  breaking-PR-fails / docs-PR-passes (evidence:
  `benchmarks/raw-results/pr-workflow-simulation/`). It has not yet run on
  github.com infrastructure.
- **Browser-side metrics for peakrdl-html were measured manually**, not by an
  automated harness (its viewer is a JS application; PeakRDL-check's viewer
  exposes `window.__peakrdl-checkPerf` for scripted checks, the baseline does
  not).

## Scope

- **IP-XACT is not supported.** SystemRDL only. (peakrdl-ipxact exists
  upstream for conversion.)
- **No editing, no language server, no collaboration features** — deliberate;
  see [ADR-0009](adr/0009-review-tool-not-editor.md).
