# Register interface changes

| Classification | Count |
|---|---|
| ✖ breaking | 1 |

## ✖ Breaking (1)

- **`speed.sel`** `ENUM-VALUE-CHANGED`
  - Enum member 'TURBO' in field 'sel' changed value from 0x2 to 0x3; existing encodings break. — `diff-corpus/scenarios/breaking-07-enum-value-changed/after.rdl`:11
  - before: `0x2` → after: `0x3`

