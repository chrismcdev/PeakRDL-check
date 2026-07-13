# ADR-0010: Framework-free viewer (deviation from the brief)

Status: accepted (2026-07-13) — explicit deviation

## Context

The brief preferred React + TypeScript with TanStack Virtual for the viewer.
The viewer's actual requirements, stated as claims to verify:

- render trees/tables of arbitrary size via virtualization;
- lazy-load everything through the paginated API;
- keep browser state bounded by what the user has expanded;
- render untrusted spec text safely;
- work fully offline.

## Decision

A **single-file vanilla-JS viewer** (`regreview/viewer/viewer.js`, ~400 lines,
plus `index.html`) with hand-rolled virtualization, served as static files by
the local server.

Rationale:

- **The claims are architecture properties, not framework properties.**
  Virtualization is "render rows [scrollTop/rowHeight .. +viewport] into a
  translated container" — ~40 lines. Lazy loading and bounded state are API
  and data-model disciplines. A framework neither provides nor enforces any
  of them.
- **Zero build chain.** No Node, no bundler, no lockfile, no supply-chain
  exposure, nothing to compile before `pip install` works. The Python package
  ships two static files.
- **Offline by construction.** No CDN, no fonts, no runtime fetches beyond
  the local API.
- **Trivially auditable.** The security posture (textContent-only insertion of
  untrusted text) is checkable by reading one file — and is enforced by test
  (`test_viewer_never_uses_innerhtml`). Auditing the same property through a
  framework's rendering layer requires trusting the framework's escaping and
  every dependency update.

Cost accepted: no component ecosystem, manual DOM code, and contributors must
read the virtualization instead of recognising a library. At the current UI
scope (tree, detail pane, search, changes list) this is a good trade.

## Revisit when

UI scope grows beyond the review surface — e.g. cross-view state (filters +
diff + waveforms), complex forms, or multiple interacting panels. At that
point adopt a framework deliberately rather than accreting an ad-hoc one; the
JSON API is framework-agnostic and would not change.
