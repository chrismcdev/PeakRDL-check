# Progress

Live checklist. Dates are completion dates.

## Done

- [x] 2026-07-13 — Environment pinned (Python 3.12.12, systemrdl-compiler
      1.32.2, peakrdl-html 2.12.2, sqlite 3.50.4; `docs/pinned-versions.txt`)
- [x] 2026-07-13 — Ecosystem review on current releases
      (`docs/ecosystem-review.md`)
- [x] 2026-07-13 — peakrdl-html problem reproduction: 1k/10k/100k/uniq10k
      measured, file-count and memory behaviour confirmed on 2.12.2
      (`docs/problem-reproduction.md`) — **Gate A**
- [x] 2026-07-13 — Deterministic fixture generator with manifests + `verify`
      (`peakrdl_check/fixture_gen.py`)
- [x] 2026-07-13 — Canonical model + adapter (folded arrays, content-hash
      dedup, per-instance extraction; identity cache measured <0.2 s @100k and
      rejected) (`docs/canonical-model.md`)
- [x] 2026-07-13 — Bisect line index replacing upstream per-lookup rescan
      (`peakrdl_check/lineindex.py`, ADR-0005)
- [x] 2026-07-13 — SQLite storage schema v1, deferred indexes, contentless
      FTS5, EXPLAIN-asserted query plans (`docs/storage.md`) — **Gate B**
      (100k vertical slice)
- [x] 2026-07-13 — Local server (localhost-only, paginated JSON, clamps,
      TCP_NODELAY fix) + framework-free virtualized viewer
- [x] 2026-07-13 — 800k clean build: 210 s total (parse 190 / elaborate 10 /
      traverse 6.6 / write 2.9 / index 0.25), 337 MB single file, 85,151 node
      rows (`build/800k-build*.json`) — **Gate C**
- [x] 2026-07-13 — Semantic diff engine + versioned policy 1.0.0 + four
      report formats (`docs/diff-rules.md`)
- [x] 2026-07-13 — 47-scenario diff corpus, 47/47 passing
      (`diff-corpus/results.json`) — **Gate D**
- [x] 2026-07-13 — Incremental builds: block-root splice, parameter replay,
      deterministic fallbacks; 800k one-line edit = 33.7 s (hash 0.04 +
      elaborate 33.0 + splice 0.6; 200/800 units), equivalence vs clean
      rebuild verified (`docs/incremental-builds.md`) — **Gate E**
- [x] 2026-07-13 — Mutation harness: 240 trials, recall 1.0, precision 1.0,
      neutral suppression 1.0
      (`benchmarks/raw-results/mutation-results.json`)
- [x] 2026-07-13 — Security posture implemented and tested (JSON-only API,
      textContent-only viewer, traversal checks, clamps; `SECURITY.md`,
      `tests/test_security.py`)
- [x] 2026-07-13 — Test suite: 56/56 passing
- [x] 2026-07-13 — GitHub Action + local PR-workflow simulation (breaking PR
      fails, docs PR passes;
      `benchmarks/raw-results/pr-workflow-simulation/`) — **Gate G** (local
      simulation)
- [x] 2026-07-13 — Benchmark harnesses (`bench.py`, `bench_queries.py`,
      `run_full_matrix.sh`) with raw-record integrity rules
      (`docs/benchmarking.md`)
- [x] 2026-07-13 — Documentation set: architecture, canonical model, storage,
      incremental, diff rules, benchmarking, development, known limitations,
      baseline methodology, problem reproduction, ecosystem review,
      ADRs 0001–0010, CONTRIBUTING, SECURITY, LICENSE, implementation plan

- [x] 2026-07-13 — Full benchmark matrix (Gate F): every fixture × tool cell,
      3 runs each, all completed within timeout. Headlines at 800k:
      peakrdl-check 285 s / 1 file / 338 MB vs peakrdl-html 1390 s / 85,216 files /
      1.1 GB; interactive p95s 0.6–10.4 ms; incremental 32.2–32.9 s (3 runs);
      source-location modes measured equal-cost (18.6–18.8 s at 100k);
      browser first-page comparison recorded
      (`benchmarks/raw-results/browser-comparison-800k.json`)
- [x] 2026-07-13 — PROOF.md generated from raw results
      (`scripts/build_proof.py`): **Claim 1 Supported, Claim 2 Supported** —
      all 21 computed criteria PASS
- [x] 2026-07-13 — README with machine-injected benchmark summary
- [x] 2026-07-13 — 10 named fixture profiles generated + count-verified
      (`fixtures/manifests/p1..p10`)

## Remaining (post-MVP)

- [ ] Run the GitHub Action on a hosted runner (currently proven via local
      simulation)
- [ ] Submit the prepared systemrdl-compiler line-index patch upstream
- [ ] Static (in-browser SQLite) delivery mode — ADR-0008
