# PeakRDL-check

**Semantic compatibility analysis and configurable quality gates for SystemRDL
specifications. Detects firmware-breaking register changes, produces CI
reports and provides scalable exploration of large register maps.**

PeakRDL-check is local-first and complements your existing
flow around `systemrdl-compiler` and PeakRDL: point it at the same `.rdl`
sources, get an indexed, instantly searchable register map and a
reviewer-grade semantic diff that classifies interface changes by impact.

## Installation

Install the command-line tool once:

```bash
pip install peakrdl-check
```

## Available commands

### Build and serve register documentation

Build a searchable index from your SystemRDL entry file, then serve the local
documentation viewer:

```bash
peakrdl-check build design.rdl -o build/design
peakrdl-check serve build/design
```

The server prints the local URL to open. It runs until you stop it with
`Ctrl+C`.

### Generate a diff report

Compare the old (`--base`) and new (`--head`) specifications:

```bash
peakrdl-check diff --base old.rdl --head new.rdl
```

The report is printed in the terminal. Add `-o diff.txt` to save it, or use
`--format markdown`, `json`, or `sarif` when another format is needed. `diff`
does not fail just because it finds a breaking change.

#### Browse a diff in the documentation viewer

Build the new register map and save a JSON diff beside it:

```bash
peakrdl-check build new.rdl -o build/review
peakrdl-check diff --base old.rdl --head new.rdl --format json -o build/review/changes.json
peakrdl-check serve build/review
```

Open the printed URL and select the **Changes** tab. The server automatically
finds `changes.json` in the index directory.

### Run a CI gate

Use `check` when breaking register-interface changes should fail a CI step:

```bash
peakrdl-check check --base old.rdl --head new.rdl
```

The command exits with status `1` when it finds a breaking change. Add
`--fail-on behavioural` only if behavioural and uncertain changes should also
fail the build.

The reusable [GitHub Action](https://github.com/chrismcdev/PeakRDL-check/blob/main/action/action.yml)
adds a Markdown report to the job summary, emits inline source annotations,
uploads the JSON and Markdown reports as an artifact, and applies the selected
failure threshold.

## What a semantic diff looks like

```text
$ peakrdl-check diff --base main/uart.rdl --head pr/uart.rdl

Semantic diff: 2 breaking, 1 documentation  (policy 1.0.0)

✖ [BREAKING     ] REG-ADDRESS-CHANGED        uart.status
    reg 'uart.status' address changed from 0x4 to 0x40.
    before: 0x4    after: 0x40
    at pr/uart.rdl:9
✖ [BREAKING     ] ENUM-VALUE-CHANGED         uart.ctrl.baud
    Enum member 'B115200' in field 'baud' changed value from 0x2 to 0x4;
    existing encodings break.
✎ [DOCUMENTATION] DESC-CHANGED               uart.ctrl
    Description wording changed on 'uart.ctrl'.
```

The corpus in `diff-corpus/` demonstrates the other direction too: a 203-line
textual refactor (file splits, reordering, hex renumbering, typedef
extraction) that produces **zero** semantic changes, and a one-line parameter
edit that changes hundreds of elaborated registers. Ambiguous renames are
reported as `MATCH-UNCERTAIN` — the tool never silently guesses.

## PeakRDL integration

To use PeakRDL-check as a registered PeakRDL subcommand, install the optional
host integration:

```bash
pip install "peakrdl-check[peakrdl]"
peakrdl check pr/design.rdl --base main/design.rdl --fail-on breaking
```

For an editable source checkout, benchmark tooling, and the test suite, see
[`CONTRIBUTING.md`](https://github.com/chrismcdev/PeakRDL-check/blob/main/CONTRIBUTING.md).

An example GitHub Actions workflow is in
[`examples/.github/workflows/register-review.yml`](https://github.com/chrismcdev/PeakRDL-check/blob/main/examples/.github/workflows/register-review.yml).

## Why PeakRDL-check

- **It reviews meaning, not text.** A textual diff can't tell a 200-line
  harmless refactor from a one-line change that silently moves hundreds of
  registers. PeakRDL-check compares the *elaborated* register models and
  classifies every change by impact — breaking, behavioural, compatible,
  documentation, or uncertain — with a stable rule ID, an explanation, and
  before/after values. When a match is ambiguous it says so instead of
  guessing.
- **Quality gates you control.** `--fail-on` picks the severity that fails CI,
  and a policy JSON reclassifies any rule to match your team's rules (e.g.
  treat reset-value changes as release-blocking). Reports come as text, JSON,
  Markdown or SARIF, and a reusable GitHub Action posts job summaries and
  inline annotations.
- **It stays fast when register maps get huge.** One SQLite index file
  instead of tens of thousands of HTML files, a virtualized viewer that only
  loads what you look at, second-scale incremental rebuilds after local
  edits, and millisecond queries — measured at 800,000 registers.
- **Every number is a measurement, not a slogan.** The benchmark summary
  below and the full evidence dossier in [PROOF.md](https://github.com/chrismcdev/PeakRDL-check/blob/main/PROOF.md) are generated
  from raw, preserved run records (`benchmarks/raw-results/`, failures and
  all) — nothing is typed by hand, and one script reproduces the lot.

## Measured performance

<!-- BENCH:BEGIN — this section is generated by scripts/build_proof.py; do not edit by hand -->
On an 800,000-register specification (Apple M4 Pro, medians of 3 runs each,
identical fixtures — full tables and environment in [PROOF.md](https://github.com/chrismcdev/PeakRDL-check/blob/main/PROOF.md)):

| Operation | PeakRDL-check | PeakRDL-html 2.12.2 |
|---|---|---|
| Cold build (raw source → browsable) | 285 s | 1390 s (4.9× slower) |
| Output | 1 file, 338 MB | 85,216 files, 1098 MB |
| Index generation from an already-elaborated model | 10 s | n/a (regenerates everything) |
| Incremental rebuild after a one-line block edit | 33 s | n/a (full rebuild) |
| Open existing index (server ready / first page) | 105 ms / 107 ms | static files, but 51.8 MB transferred up front |
| Search p95 / exact-lookup p95 | 10.4 ms / 0.6 ms | in-browser over the fully-loaded model |

Semantic diff: 47/47 curated scenarios pass (12/12 breaking detected,
10/10 formatting-only suppressed); 240 generated mutation trials at
recall 1.0, precision 1.0.
<!-- BENCH:END -->

## Supported input

- **SystemRDL 2.0** via systemrdl-compiler 1.32.2 (parameters, arrays,
  dynamic assignments, aliases, `` `include `` / `` `define `` preprocessing).
- **Not supported (yet):** IP-XACT, register editing, language-server
  features. PeakRDL-check is a review surface, not an editor
  (see [ADR-0009](https://github.com/chrismcdev/PeakRDL-check/blob/main/docs/adr/0009-review-tool-not-editor.md)).

## Architecture in one paragraph

`systemrdl-compiler` parses and elaborates; a thin adapter walks the
elaborated tree once (arrays kept folded) and emits a canonical model with
content-hash-deduplicated definitions and lightweight instances; that streams
into a single SQLite file with FTS5 search. A localhost stdlib server exposes
a paginated JSON API; the viewer is one static HTML+JS file with virtualized
rendering, so browser state stays proportional to what you actually look at.
The semantic diff engine compares two canonical models through separated
stages (matching → detection → versioned severity policy → explanation →
text/JSON/Markdown/SARIF). Incremental rebuilds re-elaborate only block types
from changed files and splice their subtrees into the existing index — proven
byte-equivalent to a clean rebuild. Details: [docs/architecture.md](https://github.com/chrismcdev/PeakRDL-check/blob/main/docs/architecture.md).

## Known limitations

- Incremental rebuilds operate at defining-file granularity.
- The register-map viewer requires a local server; static browser-only mode is
  not currently supported.
- Input is limited to SystemRDL 2.0. IP-XACT and register editing are outside
  the current scope.

See [the complete limitations list](https://github.com/chrismcdev/PeakRDL-check/blob/main/docs/known-limitations.md).

## Documentation

[Architecture](https://github.com/chrismcdev/PeakRDL-check/blob/main/docs/architecture.md) ·
[Diff rules](https://github.com/chrismcdev/PeakRDL-check/blob/main/docs/diff-rules.md) ·
[Benchmarks and evidence](https://github.com/chrismcdev/PeakRDL-check/blob/main/PROOF.md) ·
[ADRs](https://github.com/chrismcdev/PeakRDL-check/tree/main/docs/adr) ·
[Contributing](https://github.com/chrismcdev/PeakRDL-check/blob/main/CONTRIBUTING.md) ·
[Security](https://github.com/chrismcdev/PeakRDL-check/blob/main/SECURITY.md)
