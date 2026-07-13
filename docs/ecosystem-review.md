# Ecosystem review

A survey of the existing SystemRDL/register-map tooling, as actually inspected and
measured on this machine. Version pins and hardware are listed at the end; all
numbers come from runs preserved under `benchmarks/raw-results/` and `build/`.

## systemrdl-compiler 1.32.2

The reference SystemRDL 2.0 front end (Python, ANTLR4-based parser). It is the
compile/elaborate foundation for essentially the whole open ecosystem, including
PeakRDL-check. Observations from reading the 1.32.2 source:

- **Parsing is ANTLR4 in Python** and dominates wall time on large inputs. At the
  800k-register mixed fixture, parse alone is ~190 s of a ~210 s PeakRDL-check build
  (`build/800k-build.json`).
- **Per-lookup source rescans.** `source_ref.py` `DirectSourceRef._extract_line_info`
  re-reads the source file from position 0 for every line/column lookup —
  O(file size) per reference. PeakRDL-check replaces this with a per-file line-start
  table and bisect lookup (`peakrdl_check/lineindex.py`; see ADR-0005).
- **Elaboration deep-copies per instance.** Each instantiation copies the component
  definition, so memory and elaboration time scale with instance count.
- **Non-unrolled traversal keeps arrays folded.** `children(unroll=False)` yields one
  node per declared array with dimensions and stride intact. PeakRDL-check's adapter
  relies on this to keep the canonical model proportional to declarations, not
  elaborated registers.

Verdict: unavoidable and adequate as a front end; the parser is the scaling
bottleneck for every downstream tool, including this one.

## peakrdl 1.5.0 / peakrdl-html 2.12.2

`peakrdl` is the CLI umbrella; exporters plug in via `__peakrdl__.py` entry points
(a clean, well-documented plugin architecture). `peakrdl-html` is the standard
HTML documentation exporter and the natural baseline for a register *browser*.

From reading `peakrdl_html/exporter.py` (2.12.2) and measuring it:

- **One HTML file per node.** The exporter writes `content/<uid>.html` for every
  addressable node. File count therefore scales with the number of distinct nodes.
- **Eager full-model materialisation.** It builds a complete `RALData` structure in
  memory for the whole design before writing anything, then chunks it into
  `data/ral-data-N.json` files, plus a search index under `search/`.
- Both behaviours — the file-count explosion and the eager full-model memory
  profile — were **confirmed still present in the current 2.12.2 release**.

Measured on generated fixtures (`fixtures/generated/`, medians; commands and
methodology in [baseline-methodology.md](baseline-methodology.md)):

| Fixture | Wall time | Output files | Output size | Peak RSS |
|---|---:|---:|---:|---:|
| 1k mixed | 0.66 s | 186 | 9.4 MB | 88 MB |
| 10k mixed | 4.2 s | 1,136 | 22 MB | 395 MB |
| 10k unique-profile | 65 s | 10,078 | 147 MB | 3.7 GB |
| 100k mixed | 57.1 s | 10,603 | 154 MB | 3.1 GB |

The unique-register profile (every register a distinct type) is the stress case:
peakrdl-html's cost tracks *distinct definitions*, so 10k unique registers cost
more than 100k mixed ones. Extrapolation and reproduction commands are in
[problem-reproduction.md](problem-reproduction.md).

## Kactus2

Qt-based graphical IP-XACT editor (kactus2.org). Different niche: it is an
*editing* environment for IP-XACT packaging, not a SystemRDL review/browsing tool.
No overlap with PeakRDL-check's review workflow; not benchmarked.

## OpenTitan reggen

OpenTitan's in-tree register tool. Input is hjson (not SystemRDL); it generates
per-block documentation and RTL as part of the OpenTitan build. Excellent within
its ecosystem, but tied to hjson and per-block scope — no whole-SoC browsing or
semantic diff of SystemRDL.

## systemrdl-pro

Commercial SystemRDL IDE / language server (editor integration, completion,
navigation, live diagnostics). PeakRDL-check deliberately does **not** duplicate its
editor/LSP feature set: the underserved niche is large-scale *review* — fast
whole-design indexing, browsing, and semantic diff in CI (see ADR-0009).

## Where PeakRDL-check fits

| Need | Existing answer | Gap |
|---|---|---|
| Compile/elaborate SystemRDL | systemrdl-compiler | none — PeakRDL-check builds on it |
| HTML documentation | peakrdl-html | collapses at 100k+ registers (files, memory) |
| Editing / LSP | systemrdl-pro | commercial; out of scope here |
| IP-XACT packaging | Kactus2 | different format/workflow |
| Semantic diff of register maps in CI | — | PeakRDL-check's `diff`/`check` + GitHub Action |
| Million-register local browsing | — | PeakRDL-check's SQLite index + local server |

Storage is a single SQLite file per specification (rationale and rejected
alternatives in [ADR-0003](adr/0003-sqlite-storage.md)).

## Pinned environment

All measurements in this documentation set were taken on:

- Python 3.12.12; sqlite 3.50.4 (Python module) / 3.51.0 (CLI)
- systemrdl-compiler 1.32.2, peakrdl 1.5.0, peakrdl-html 2.12.2
  (full transitive pins in `docs/pinned-versions.txt`)
- macOS 26.5.1, Apple M4 Pro (14 cores), 24 GB RAM
