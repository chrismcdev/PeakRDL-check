# Register interface changes

| Classification | Count |
|---|---|
| △ behavioural | 1 |

## △ Behavioural (1)

- **`irq_status.pending`** `INTERRUPT-CHANGED`
  - Field 'pending' intr behaviour enabled; interrupt semantics of this field changed. — `diff-corpus/scenarios/behavioural-08-interrupt-changed/after.rdl`:2
  - before: `False` → after: `True`

