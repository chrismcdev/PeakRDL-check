# ADR-0009: A review tool, not an editor

Status: accepted (2026-07-13)

## Context

Adjacent feature territory was tempting: SystemRDL editing support, an LSP
server (completion, go-to-definition, live diagnostics), collaborative
review with comments and sign-off workflows.

## Decision

PeakRDL-check does none of that. Scope is: **build a fast index, browse it, diff
two revisions semantically, gate CI**.

Reasons:

- **The editing/LSP niche is already served.** systemrdl-pro exists as a
  commercial SystemRDL IDE/language server. Competing with a funded IDE on
  editor features is a poor use of a small tool's budget, and users who need
  both can use both — the tools don't conflict.
- **Review is the underserved niche.** Nothing in the ecosystem answers "what
  does this PR actually change in the register interface, and does it break
  software?" or "let me browse a million-register map without a 3 GB process".
  Performance at scale and semantic diff are the entire value proposition.
- **Editing multiplies the correctness surface.** A reviewer tool can be
  read-only over untrusted input (see SECURITY.md); an editor must write user
  files, manage partial/broken parse states, and keep an AST synchronised —
  none of which serves review.
- **Collaboration belongs to the forge.** PR comments, approvals and history
  live in GitHub/GitLab; the right integration point is a CI check with
  annotations and a job summary (the GitHub Action), not a parallel review
  system.

## Consequences

- The viewer has no write path at all; the server is read-only over the
  index.
- CI is a first-class consumer: `peakrdl-check check --fail-on`, SARIF output,
  the composite action in `action/`.
- If review workflows someday need persistent annotations, the answer should
  be exporting to the forge's review primitives, not building storage for
  them here.
