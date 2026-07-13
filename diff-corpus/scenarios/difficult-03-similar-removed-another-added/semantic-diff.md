# Register interface changes

| Classification | Count |
|---|---|
| ✖ breaking | 1 |
| ✚ compatible | 1 |

## ✖ Breaking (1)

- **`wm_old`** `REG-REMOVED`
  - reg 'wm_old' at 0x8 was removed. — `/Users/christopher.mcdonald/Desktop/RagReview/diff-corpus/scenarios/difficult-03-similar-removed-another-added/before.rdl`:3
  - before: `0x8` → after: `None`

## ✚ Compatible (1)

- **`wm_new`** `REG-ADDED-UNUSED-SPACE`
  - reg 'wm_new' added at 0x10 in previously unused address space. — `/Users/christopher.mcdonald/Desktop/RagReview/diff-corpus/scenarios/difficult-03-similar-removed-another-added/after.rdl`:3
  - before: `None` → after: `0x10`

