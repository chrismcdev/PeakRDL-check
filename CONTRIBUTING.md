# Contributing to PeakRDL-check

## Development setup

```bash
uv venv
uv pip install -e ".[baseline,dev]"
.venv/bin/peakrdl-check doctor        # environment sanity check
```

`baseline` (peakrdl-html) is only needed to run benchmarks; `dev` brings
pytest. Details: `docs/development.md`.

## Tests

```bash
.venv/bin/python -m pytest tests/                 # unit + integration (56 tests)
.venv/bin/python scripts/run_corpus.py            # 47 semantic-diff scenarios
.venv/bin/python scripts/mutation_tests.py 240    # diff-engine accuracy
.venv/bin/python scripts/simulate_pr_workflow.sh  # GitHub Action end-to-end (local)
```

All of these must pass before a change to `peakrdl_check/` merges. Changes to the
storage schema bump `STORAGE_SCHEMA_VERSION`; changes to canonical bodies or
hashing bump `CANONICAL_SCHEMA_VERSION`; classification changes bump
`POLICY_VERSION` (`peakrdl_check/__init__.py`, `peakrdl_check/policy.py`).

## Benchmark rules

Benchmarks are evidence, and evidence has chain-of-custody rules:

1. **Never hand-edit anything under `benchmarks/raw-results/`.** Raw records
   are written only by the harnesses (`bench.py`, `bench_queries.py`,
   `mutation_tests.py`). If a number is wrong, rerun; don't patch.
2. **Preserve failures and timeouts.** A timed-out or crashed run is a result
   (`"timeout": true`, `exitCode`, `stderrTail`) and stays in the record set.
3. **Medians, not best runs.** Minimum 3 runs per cell; summarise with
   medians.
4. **Pin and record the environment.** Same machine and venv for any numbers
   that will be compared; every record carries hardware, versions and the
   fixture checksum. Version pins live in `docs/pinned-versions.txt`.
5. **Reports are generated from raw records**, separately from execution.

Methodology: `docs/baseline-methodology.md`.

## Commit conventions

- [Conventional Commits](https://www.conventionalcommits.org/): pull-request
  titles are `type(scope): summary` (or `type: summary`) with types `feat`,
  `fix`, `docs`, `test`, `perf`, `build`, `ci`, `style`, or `revert`; ≤ 72
  characters and imperative mood. `chore` and `refactor` are intentionally
  excluded. GitHub squash-merges the pull-request title into the single commit
  added to `main`. CI blocks titles that do not follow this convention, and
  the required unit-test job must also pass before merging.
- A commit that changes behaviour includes/updates its tests in the same
  commit; a commit that changes performance claims includes the raw-result
  files from the rerun.
- Do not mix functional changes with benchmark reruns or fixture
  regeneration — keep the evidence diff auditable on its own.

## Releases

Merges to `main` update a generated release pull request based on Conventional
Commit titles. `fix` changes produce a patch release, `feat` changes produce a
minor release, and a `!` or `BREAKING CHANGE` produces a major release. Merging
the generated `feat(release): prepare vX.Y.Z` pull request creates the tag and
GitHub Release, verifies the package versions, runs the test and semantic-diff
corpus, builds and checks the distributions, then publishes to PyPI through
trusted publishing. Do not edit versions or create release tags manually.

## Authoring diff-corpus scenarios

Each scenario is a directory under `diff-corpus/scenarios/`, named
`<category>-<nn>-<slug>` where category is one of `breaking`, `behavioural`,
`compatible`, `neutral`, `difficult`.

Required files:

- `before.rdl` and `after.rdl` (or `before/` and `after/` directories, each
  containing `main.rdl`, for multi-file scenarios);
- `expected.json` — the ground truth the runner scores against.

`expected.json` schema (consumed by `scripts/run_corpus.py`):

```json
{
  "title": "Register removed",
  "category": "breaking",
  "top": "soc",
  "expect": [
    {
      "ruleId": "REG-REMOVED",
      "entityKey": "timer",
      "classification": "breaking",
      "confidence": "certain"
    }
  ],
  "forbid": ["REG-RENAMED", "MATCH-UNCERTAIN"],
  "maxChanges": 1,
  "minChanges": 1
}
```

| Key | Required | Meaning |
|---|---|---|
| `title` | yes | human-readable one-liner |
| `category` | yes | scenario family (drives reporting) |
| `top` | no | top component name if the file defines several |
| `expect[]` | yes | changes that MUST appear; `entityKey`, `classification`, `confidence` are optional narrowing constraints on the matched rule |
| `forbid[]` | no | rule ids that must NOT appear at all |
| `maxChanges` / `minChanges` | no | bounds on total emitted changes — use `maxChanges` to prove noise suppression |

Guidelines:

- Neutral scenarios (formatting, comments, reordering, equivalent
  expressions) should assert `"maxChanges": 0` — silence is the tested
  behaviour.
- For rename scenarios, decide whether the rename is *definite* (unique
  content+footprint pair → expect `REG-RENAMED`, forbid `MATCH-UNCERTAIN`) or
  *ambiguous* (expect `MATCH-UNCERTAIN`, forbid `REG-RENAMED`).
- Keep specs minimal — a scenario should demonstrate exactly one behaviour.
- Run `scripts/run_corpus.py <slug-substring>` and commit the generated
  `git.diff`, `semantic-diff.json`, `semantic-diff.md` alongside your inputs;
  they double as reviewable documentation of engine behaviour.

## Security

Specifications are untrusted input. Anything touching the server, storage
query paths or the viewer must preserve the properties in `SECURITY.md` and
keep `tests/test_security.py` green. Report vulnerabilities per `SECURITY.md`
rather than via public issues.
