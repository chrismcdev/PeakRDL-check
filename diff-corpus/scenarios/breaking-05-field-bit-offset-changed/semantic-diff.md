# Register interface changes

| Classification | Count |
|---|---|
| ✖ breaking | 1 |

## ✖ Breaking (1)

- **`ctrl.mode`** `FIELD-OFFSET-CHANGED`
  - Field 'mode' moved from bit 1 to bit 5. — `diff-corpus/scenarios/breaking-05-field-bit-offset-changed/after.rdl`:5
  - before: `[3:1]` → after: `[7:5]`

