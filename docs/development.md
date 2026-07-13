# Development guide

## Bootstrap

```bash
uv venv
uv pip install -e ".[baseline,dev]"
```

- `baseline` pulls `peakrdl==1.5.0` + `peakrdl-html==2.12.2` (needed only for
  benchmarks; RegReview itself depends solely on
  `systemrdl-compiler==1.32.2`).
- `dev` pulls `pytest`.

Check the environment:

```bash
.venv/bin/regreview doctor
```

(verifies Python ≥ 3.10, systemrdl-compiler, SQLite ≥ 3.43 with FTS5,
`/usr/bin/time`, memory.)

## Run the tests

```bash
.venv/bin/python -m pytest tests/
```

56 tests across canonical model, storage (including EXPLAIN-verified query
plans), diff rules, incremental splicing, CLI, and security.

## Run the diff corpus

```bash
.venv/bin/python scripts/run_corpus.py            # all 47 scenarios
.venv/bin/python scripts/run_corpus.py breaking   # filter by substring
```

## Build and serve an index

```bash
# Generate a fixture (deterministic, manifest with checksums)
.venv/bin/regreview-fixture generate --registers 100000 --name 100k \
    --output fixtures/generated
# verify a manifest against the elaborated model:
.venv/bin/regreview-fixture verify fixtures/generated/100k.manifest.json

# Build
.venv/bin/regreview build fixtures/generated/100k.rdl \
    --top bench100k_top --output build/100k

# Incremental rebuild after editing a type file
.venv/bin/regreview build fixtures/generated/100k.rdl \
    --top bench100k_top --output build/100k --incremental

# Serve (localhost only; port 0 = auto)
regreview serve build/100k --port 8642
# → http://127.0.0.1:8642/
```

Other useful commands: `regreview inspect <index>`, `regreview query <index>
--search foo`, `regreview diff --base a.rdl --head b.rdl --format markdown`,
`regreview check --base a.rdl --head b.rdl --fail-on breaking`,
`regreview cache stats <index>`.

## Repository layout

| Path | Contents |
|---|---|
| `regreview/` | the package: `adapter.py` (only module that imports systemrdl), `canonical.py`, `storage.py`, `diff.py`, `policy.py`, `report.py`, `incremental.py`, `server.py`, `lineindex.py`, `cli.py`, `fixture_gen.py` |
| `regreview/viewer/` | `index.html` + `viewer.js` — the whole UI |
| `tests/` | pytest suite |
| `diff-corpus/scenarios/` | 47 semantic-diff scenarios with `expected.json` ground truth |
| `scripts/` | `run_corpus.py`, `mutation_tests.py`, `verify_incremental_equivalence.py`, `simulate_pr_workflow.sh` |
| `benchmarks/scripts/` | `bench.py`, `bench_queries.py`, `peakrdl_driver.py`, `run_full_matrix.sh` |
| `benchmarks/raw-results/` | one JSON per benchmark run — source of truth, never edited |
| `fixtures/generated/` | seeded fixtures + `*.manifest.json` (checksums, expected counts) |
| `action/` | GitHub composite action (`action.yml`, `review.py`) |
| `build/` | built indexes and build reports (local artifacts) |
| `docs/` | this documentation, ADRs under `docs/adr/` |

## The viewer has no build step

`regreview/viewer/viewer.js` is a single hand-written vanilla-JS file (~400
lines) served as-is by the local server; `index.html` carries the CSS. There
is no Node, no bundler, no transpiler, no lockfile — editing the file and
reloading the browser is the entire workflow. Invariants to preserve
(enforced by `tests/test_security.py::test_viewer_never_uses_innerhtml`):

- all untrusted text is inserted via `textContent` — never `innerHTML`,
  `outerHTML`, `document.write`, or `insertAdjacentHTML`;
- no API response contains the full hierarchy; keep everything paginated;
- browser state stays proportional to what the user has expanded
  (the virtualized list renders only visible rows).

Rationale: [ADR-0010](adr/0010-framework-free-viewer.md).
