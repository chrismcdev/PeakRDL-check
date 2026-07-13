# Register interface changes

| Classification | Count |
|---|---|
| ✖ breaking | 2 |
| ? uncertain | 2 |
| ✚ compatible | 2 |

## ✖ Breaking (2)

- **`spare_a`** `REG-REMOVED`
  - reg 'spare_a' at 0x10 was removed. — `/Users/christopher.mcdonald/Desktop/RagReview/diff-corpus/scenarios/difficult-08-ambiguous-rename/before.rdl`:3
  - before: `0x10` → after: `None`
- **`spare_b`** `REG-REMOVED`
  - reg 'spare_b' at 0x14 was removed. — `/Users/christopher.mcdonald/Desktop/RagReview/diff-corpus/scenarios/difficult-08-ambiguous-rename/before.rdl`:4
  - before: `0x14` → after: `None`

## ? Uncertain (2)

- **`spare_a`** `MATCH-UNCERTAIN` _(confidence: uncertain)_
  - reg 'spare_a' was removed and 2 added sibling(s) have identical content; possible rename but ambiguous — reporting both removal and addition. — `/Users/christopher.mcdonald/Desktop/RagReview/diff-corpus/scenarios/difficult-08-ambiguous-rename/before.rdl`:3
- **`spare_b`** `MATCH-UNCERTAIN` _(confidence: uncertain)_
  - reg 'spare_b' was removed and 2 added sibling(s) have identical content; possible rename but ambiguous — reporting both removal and addition. — `/Users/christopher.mcdonald/Desktop/RagReview/diff-corpus/scenarios/difficult-08-ambiguous-rename/before.rdl`:4

## ✚ Compatible (2)

- **`dbg_x`** `REG-ADDED-UNUSED-SPACE`
  - reg 'dbg_x' added at 0x20 in previously unused address space. — `/Users/christopher.mcdonald/Desktop/RagReview/diff-corpus/scenarios/difficult-08-ambiguous-rename/after.rdl`:3
  - before: `None` → after: `0x20`
- **`dbg_y`** `REG-ADDED-UNUSED-SPACE`
  - reg 'dbg_y' added at 0x24 in previously unused address space. — `/Users/christopher.mcdonald/Desktop/RagReview/diff-corpus/scenarios/difficult-08-ambiguous-rename/after.rdl`:4
  - before: `None` → after: `0x24`

