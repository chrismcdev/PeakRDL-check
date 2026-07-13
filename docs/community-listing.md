# PeakRDL community-page listing

The [PeakRDL community page](https://peakrdl.readthedocs.io/en/latest/community.html)
is a table of `name | author | one-line summary`, and projects are added by
posting in the SystemRDL org's
[show-and-tell discussions](https://github.com/orgs/SystemRDL/discussions/categories/show-and-tell),
after which maintainers add the entry.

## Proposed table entry (Documentation section, or a new "Analysis/CI" row)

| Plugin | Author | Summary |
|---|---|---|
| [PeakRDL-check](https://github.com/chrismcdev/PeakRDL-check) | [Christopher McDonald](https://github.com/chrismcdev) | Semantic compatibility analysis and CI quality gates for SystemRDL; detects firmware-breaking register changes and provides scalable exploration of large register maps |

## Draft show-and-tell post

**Title:** PeakRDL-check — semantic compatibility analysis and CI quality gates for SystemRDL

**Body:**

> PeakRDL-check provides semantic compatibility analysis and configurable
> quality gates for SystemRDL specifications. It detects firmware-breaking
> register changes, produces CI reports and provides scalable exploration of
> large register maps.
>
> Highlights:
>
> - `peakrdl-check diff/check`: semantic diff between two spec revisions with
>   impact classification (breaking / behavioural / compatible /
>   documentation / uncertain), stable rule IDs, explanations, source
>   locations, and text/JSON/Markdown/SARIF output. CI-friendly exit codes
>   plus a reusable GitHub Action with job summaries and inline annotations.
>   Validated against a 47-scenario public corpus (100% detection of curated
>   breaking cases, 100% suppression of formatting-only changes, no silent
>   rename guessing) and 240 seeded mutation trials (recall 1.0,
>   precision 1.0).
> - `peakrdl-check build/serve`: indexes very large register maps into a
>   single SQLite file and serves a virtualized local viewer. Measured on an
>   800,000-register fixture: one output file vs 85,216 files, ~4.9× faster
>   end-to-end than peakrdl-html 2.12.2, sub-millisecond exact lookups and
>   ~10 ms p95 search, ~33 s incremental rebuild after a local block edit.
> - Uses systemrdl-compiler as its front end; benchmark methodology, raw run
>   records and a generated PROOF.md ship in the repository.
>
> Repo: https://github.com/chrismcdev/PeakRDL-check

## Before posting

1. Publish the repository and create the `v0` action tag referenced by the
   example workflow.
2. ~~Optionally implement a `__peakrdl__` entry point~~ — done:
   `peakrdl check head.rdl --base main/design.rdl` works via the
   `peakrdl.exporters` entry point (`peakrdl_check/__peakrdl__.py`), so the
   project is a true PeakRDL plugin. Mention this in the post.
