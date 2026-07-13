"""PeakRDL-check: local-first semantic review and large-scale browsing for hardware register specifications."""

__version__ = "0.1.0"

# Version of the canonical model schema. Bump on any change to the canonical
# entity representation or hashing scheme; cached artifacts are keyed on it.
CANONICAL_SCHEMA_VERSION = 1

# Version of the SQLite storage schema. Bump on any table/index change.
STORAGE_SCHEMA_VERSION = 1

# Version of the semantic-diff severity policy.
POLICY_VERSION = "1.0.0"
