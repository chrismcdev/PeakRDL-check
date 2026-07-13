# Register interface changes

| Classification | Count |
|---|---|
| ✖ breaking | 1 |

## ✖ Breaking (1)

- **`clkdiv`** `REG-MOVED-AND-RENAMED` _(confidence: likely)_
  - reg 'clkdiv' appears renamed to 'clock_divider' and moved from 0x4 to 0x10 (content identical). — `diff-corpus/scenarios/difficult-02-register-moved-and-renamed/after.rdl`:3
  - before: `clkdiv @ 0x4` → after: `clock_divider @ 0x10`

