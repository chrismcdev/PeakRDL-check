# ADR-0007: Six semantic classifications, versioned policy

Status: accepted (2026-07-13)

## Context

A register-map diff is only useful to a reviewer if it answers "how much
should I care?" — but severity is a *judgement*, and judgements differ between
teams (one team treats reset-value changes as breaking, another doesn't).
Baking severity into detection would make both untestable and unconfigurable.

## Decision

1. **Six classifications**: `breaking`, `behavioural`, `compatible`,
   `documentation`, `informational`, `uncertain`. Six because the review
   decision space is: must-block / needs-human-thought / safe-additive /
   prose-only / bookkeeping / tool-refuses-to-guess. Fewer loses the
   compatible-vs-documentation distinction that CI gating needs
   (`--fail-on breaking` vs `behavioural`); more invites taxonomy debates
   with no gating consequence.
2. **`uncertain` is a first-class outcome.** When matching is ambiguous the
   tool reports facts plus a `MATCH-UNCERTAIN` advisory rather than guessing
   (see docs/diff-rules.md, rename honesty).
3. **Policy is versioned separately from detection.** Detection emits stable
   rule ids describing *what* changed; `peakrdl_check/policy.py` maps rule id →
   classification under `POLICY_VERSION` (1.0.0), and every change record
   carries the `policyVersion` it was classified under. Teams override per
   rule with `--policy overrides.json`.
4. **No rule-language engine in the MVP.** A DSL for user-defined detection
   rules (patterns over the model) was considered and rejected for v1: the
   48-rule catalogue covers the corpus and mutation suite at 100 % recall /
   100 % precision, and a rule language is a large, security-sensitive surface
   with no demonstrated demand yet. Overriding classifications covers the
   observed customisation need.

## Consequences

- Detection is testable against ground truth without severity opinions
  (mutation harness), and policy changes never require re-validating
  detection.
- Reports are deterministic and ordered by severity group, entity, rule.
- If two teams need different *detection* (not classification), that is the
  signal to revisit the no-rule-language decision.
