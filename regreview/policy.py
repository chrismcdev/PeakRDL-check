"""Severity policy for semantic changes.

The policy maps stable rule identifiers to classifications. It is versioned
independently of change *detection*: detection describes what structurally
changed; the policy decides how much a reviewer should care. Custom policies
can override classifications per rule id.

Classifications:
    breaking       — existing software/hardware contract violated
    behavioural    — observable behaviour differs, layout contract intact
    compatible     — additive, existing consumers unaffected
    documentation  — human-facing text only
    informational  — metadata/bookkeeping
    uncertain      — the tool refuses to guess (e.g. ambiguous rename)
"""

from __future__ import annotations

POLICY_VERSION = "1.0.0"

BREAKING = "breaking"
BEHAVIOURAL = "behavioural"
COMPATIBLE = "compatible"
DOCUMENTATION = "documentation"
INFORMATIONAL = "informational"
UNCERTAIN = "uncertain"

CLASSIFICATION_ORDER = [BREAKING, BEHAVIOURAL, UNCERTAIN, COMPATIBLE,
                        DOCUMENTATION, INFORMATIONAL]

DEFAULT_POLICY: dict[str, str] = {
    # --- specification level ---
    "SPEC-COMPILE-FAILED": BREAKING,       # head no longer elaborates
    # --- register / container level ---
    "REG-REMOVED": BREAKING,
    "REG-ADDED-UNUSED-SPACE": COMPATIBLE,
    "REG-ADDED-OVERLAPPING": BREAKING,
    "REG-ADDRESS-CHANGED": BREAKING,
    "REG-WIDTH-REDUCED": BREAKING,
    "REG-WIDTH-INCREASED": BEHAVIOURAL,
    "REG-RENAMED": BEHAVIOURAL,            # layout identical, symbol changed
    "REG-MOVED-AND-RENAMED": BREAKING,     # address changed too
    "BLOCK-REMOVED": BREAKING,
    "BLOCK-ADDED": COMPATIBLE,
    "BLOCK-MOVED": BREAKING,               # propagates to all children
    "BLOCK-RENAMED": BEHAVIOURAL,
    "ARRAY-DIMS-CHANGED": BREAKING,
    "ARRAY-STRIDE-CHANGED": BREAKING,
    "ADDR-OVERLAP-NEW": BREAKING,
    # --- field level ---
    "FIELD-REMOVED": BREAKING,
    "FIELD-ADDED-UNUSED-BITS": COMPATIBLE,
    "FIELD-ADDED-OVERLAPPING": BREAKING,
    "FIELD-OFFSET-CHANGED": BREAKING,
    "FIELD-WIDTH-REDUCED": BREAKING,
    "FIELD-WIDTH-INCREASED": BEHAVIOURAL,
    "FIELD-OVERLAP-NEW": BREAKING,
    "FIELD-RENAMED": BEHAVIOURAL,
    # --- access semantics ---
    "ACCESS-RW-TO-RO": BREAKING,           # writes silently dropped
    "ACCESS-READABLE-TO-WO": BREAKING,     # reads no longer defined
    "ACCESS-WIDENED": BEHAVIOURAL,         # e.g. r -> rw
    "ACCESS-CHANGED-AMBIGUOUS": UNCERTAIN, # e.g. w -> r
    "HW-ACCESS-CHANGED": BEHAVIOURAL,
    # --- behaviour ---
    "RESET-VALUE-CHANGED": BEHAVIOURAL,
    "RESET-ADDED": BEHAVIOURAL,
    "RESET-REMOVED": BEHAVIOURAL,
    "VOLATILITY-CHANGED": BEHAVIOURAL,
    "ONREAD-CHANGED": BEHAVIOURAL,
    "ONWRITE-CHANGED": BEHAVIOURAL,
    # --- enumerations ---
    "ENUM-VALUE-CHANGED": BREAKING,        # existing name now encodes differently
    "ENUM-VALUE-REMOVED": BREAKING,
    "ENUM-VALUE-ADDED": COMPATIBLE,
    "ENUM-VALUE-RENAMED": BEHAVIOURAL,
    "ENUM-ADDED": COMPATIBLE,
    "ENUM-REMOVED": BEHAVIOURAL,
    "INTERRUPT-CHANGED": BEHAVIOURAL,
    "COUNTER-CHANGED": BEHAVIOURAL,
    # --- aliases ---
    "REG-ALIAS-ADDED": COMPATIBLE,
    # --- documentation / metadata ---
    "DESC-ADDED": COMPATIBLE,
    "DESC-CHANGED": DOCUMENTATION,
    "DESC-REMOVED": DOCUMENTATION,
    "METADATA-ADDED": COMPATIBLE,
    "METADATA-CHANGED": INFORMATIONAL,
    # --- matching ---
    "MATCH-UNCERTAIN": UNCERTAIN,          # possible rename, not asserted
}


def load_policy(path=None) -> dict:
    """Default policy, optionally overlaid with a user JSON file."""
    policy = dict(DEFAULT_POLICY)
    if path:
        import json
        from pathlib import Path
        overrides = json.loads(Path(path).read_text())
        for rule, cls in overrides.get("rules", {}).items():
            if cls not in CLASSIFICATION_ORDER:
                raise ValueError(f"policy override {rule}: unknown classification {cls}")
            policy[rule] = cls
    return policy
