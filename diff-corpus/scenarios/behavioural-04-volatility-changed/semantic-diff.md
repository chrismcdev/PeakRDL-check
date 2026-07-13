# Register interface changes

| Classification | Count |
|---|---|
| △ behavioural | 2 |

## △ Behavioural (2)

- **`status.busy`** `HW-ACCESS-CHANGED`
  - Field 'busy' hardware access changed from w to r. — `diff-corpus/scenarios/behavioural-04-volatility-changed/after.rdl`:2
  - before: `w` → after: `r`
- **`status.busy`** `VOLATILITY-CHANGED`
  - Field 'busy' volatility changed from True to False; read-back guarantees differ. — `diff-corpus/scenarios/behavioural-04-volatility-changed/after.rdl`:2
  - before: `True` → after: `False`

