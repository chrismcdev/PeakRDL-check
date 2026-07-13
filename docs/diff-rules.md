# Semantic diff rules

Every change record carries a stable `ruleId`, a `classification` assigned by
the versioned severity policy (`regreview/policy.py`, `policyVersion` 1.0.0),
a `confidence`, a human message, before/after values, and source locations
where available. Detection (`regreview/diff.py`) is separate from policy:
detection states what changed; the policy decides how much a reviewer should
care.

## Classifications

| Classification | Meaning |
|---|---|
| `breaking` | an existing software/hardware contract is violated |
| `behavioural` | observable behaviour differs; layout contract intact |
| `compatible` | additive; existing consumers unaffected |
| `documentation` | human-facing text only |
| `informational` | metadata/bookkeeping |
| `uncertain` | the tool refuses to guess (e.g. ambiguous rename) |

Report ordering groups by severity: breaking, behavioural, uncertain,
compatible, documentation, informational.

## Confidence levels

| Confidence | Used when |
|---|---|
| `certain` | directly observed structural fact |
| `likely` | inferred with strong evidence (e.g. a definite-by-construction rename) |
| `uncertain` | plausible interpretations exist; the tool reports the facts instead of choosing |

## Rule table (default policy 1.0.0)

### Specification level

| Rule | Classification | Meaning | Example message |
|---|---|---|---|
| `SPEC-COMPILE-FAILED` | breaking | head (or base) no longer elaborates | "The head specification failed to compile/elaborate: …" |

### Register / container level

| Rule | Classification | Meaning | Example message |
|---|---|---|---|
| `REG-REMOVED` | breaking | register deleted | "reg 'timer' at 0x10 was removed." |
| `REG-ADDED-UNUSED-SPACE` | compatible | new register in previously unused space | "reg 'soc.new_ctrl' added at 0x40 in previously unused address space." |
| `REG-ADDED-OVERLAPPING` | breaking | new register overlaps existing footprint | "reg 'x' added at 0x10 overlapping address space previously used by 'y'." |
| `REG-ADDRESS-CHANGED` | breaking | register moved | "reg 'status' address changed from 0x4 to 0x40." |
| `REG-WIDTH-REDUCED` | breaking | regwidth shrank | "Register width changed from 64 to 32 bits." |
| `REG-WIDTH-INCREASED` | behavioural | regwidth grew | "Register width changed from 32 to 64 bits." |
| `REG-RENAMED` | behavioural | symbol changed, address+content identical | "reg 'uart.ctl' renamed to 'control' (address 0x0 and content unchanged)…" |
| `REG-MOVED-AND-RENAMED` | breaking | renamed and address changed (content identical) | "reg 'a.r0' appears renamed to 'r0_new' and moved from 0x0 to 0x100…" |
| `BLOCK-REMOVED` | breaking | container deleted (carries `affectedRegisters`) | "addrmap 'dma' at 0x10000 was removed (containing 12 registers)." |
| `BLOCK-ADDED` | compatible | container added | "addrmap 'spi2' added at 0x30000." |
| `BLOCK-MOVED` | breaking | container address changed; one record covers all children | "addrmap 'dma' address changed from 0x10000 to 0x20000, moving all 12 registers beneath it." |
| `BLOCK-RENAMED` | behavioural | container symbol changed, layout intact | "addrmap 'uart0' renamed to 'uart_a' (address … and content unchanged)…" |
| `ARRAY-DIMS-CHANGED` | breaking | array dimensions differ | "reg 'ch' array dimensions changed from [16] to [32]; element addresses and the overall footprint change." |
| `ARRAY-STRIDE-CHANGED` | breaking | stride differs (dims equal) | "reg 'ch' array stride changed from 0x10 to 0x20; every element beyond [0] moves." |
| `ADDR-OVERLAP-NEW` | breaking | new overlap introduced between existing entities | (reserved; overlap on addition is reported via `REG-ADDED-OVERLAPPING`) |

### Field level

| Rule | Classification | Meaning | Example message |
|---|---|---|---|
| `FIELD-REMOVED` | breaking | field deleted | "Field 'mode' [3:1] was removed." |
| `FIELD-ADDED-UNUSED-BITS` | compatible | new field in previously unused bits | "Field 'dbg' added at [15:12] in previously unused bits." |
| `FIELD-ADDED-OVERLAPPING` | breaking | new field over previously used bits | "Field 'dbg' added at [3:0], overlapping bits that were previously used by other fields." |
| `FIELD-OFFSET-CHANGED` | breaking | field moved within the register | "Field 'baud' moved from bit 1 to bit 4." |
| `FIELD-WIDTH-REDUCED` | breaking | field shrank | "Field 'div' width changed from 8 to 4 bits." |
| `FIELD-WIDTH-INCREASED` | behavioural | field grew | "Field 'div' width changed from 4 to 8 bits." |
| `FIELD-OVERLAP-NEW` | breaking | fields newly overlap | (reserved; overlap on addition is reported via `FIELD-ADDED-OVERLAPPING`) |
| `FIELD-RENAMED` | behavioural | field identical except its name | "Field 'en' renamed to 'enable' (bits, access, reset unchanged). Software symbols change only." |

### Access semantics

| Rule | Classification | Meaning | Example message |
|---|---|---|---|
| `ACCESS-RW-TO-RO` | breaking | writes silently dropped (rw → r) | "Field 'ctrl' software access changed from rw to r." |
| `ACCESS-READABLE-TO-WO` | breaking | reads no longer defined | "Field 'key' software access changed from rw to w." |
| `ACCESS-WIDENED` | behavioural | strictly more capability (e.g. r → rw) | "Field 'status' software access changed from r to rw." |
| `ACCESS-CHANGED-AMBIGUOUS` | uncertain | any other transition (e.g. w → r); the tool does not guess | "Field 'f' software access changed from w to r." |
| `HW-ACCESS-CHANGED` | behavioural | hardware-side access differs | "Field 'f' hardware access changed from r to w." |

### Behaviour

| Rule | Classification | Meaning | Example message |
|---|---|---|---|
| `RESET-VALUE-CHANGED` | behavioural | reset value differs | "Field 'baud' reset value changed from 0x3 to 0x7." |
| `RESET-ADDED` | behavioural | field gained a reset | "Field 'baud' gained a reset value." |
| `RESET-REMOVED` | behavioural | field lost its reset | "Field 'baud' no longer has a reset value." |
| `VOLATILITY-CHANGED` | behavioural | volatile flag flipped | "Field 'st' volatility changed from False to True; read-back guarantees differ." |
| `ONREAD-CHANGED` | behavioural | read side-effect differs | "Field 'fifo' onread side-effect changed from None to rclr." |
| `ONWRITE-CHANGED` | behavioural | write side-effect differs | "Field 'irq' onwrite side-effect changed from None to woclr." |

### Enumerations

| Rule | Classification | Meaning | Example message |
|---|---|---|---|
| `ENUM-VALUE-CHANGED` | breaking | existing name encodes differently | "Enum member 'FAST' in field 'mode' changed value from 0x2 to 0x3; existing encodings break." |
| `ENUM-VALUE-REMOVED` | breaking | member deleted | "Enum member 'LEGACY' (=0x1) removed from field 'mode'." |
| `ENUM-VALUE-ADDED` | compatible | member added, others untouched | "Enum member 'TURBO' (=0x4) added to field 'mode' without modifying existing members." |
| `ENUM-VALUE-RENAMED` | behavioural | same value, new name | "Enum member 'SLOW' (=0x0) renamed to 'LOW' in field 'mode'." |
| `ENUM-ADDED` | compatible | field gained an enumeration | "Field 'mode' gained an enumeration." |
| `ENUM-REMOVED` | behavioural | field lost its enumeration | "Field 'mode' no longer has an enumeration." |
| `INTERRUPT-CHANGED` | behavioural | `intr` property flipped | "Field 'err' intr behaviour enabled; interrupt semantics of this field changed." |
| `COUNTER-CHANGED` | behavioural | `counter` property flipped | "Field 'evt' counter behaviour disabled; counter semantics of this field changed." |

### Aliases, documentation, metadata, matching

| Rule | Classification | Meaning | Example message |
|---|---|---|---|
| `REG-ALIAS-ADDED` | compatible | alias register added over existing storage | "alias register 'dbg_ctrl' added at 0x0; it augments access to existing storage without changing existing addresses." |
| `DESC-ADDED` | compatible | description added | "Description added to field 'en'." |
| `DESC-CHANGED` | documentation | wording changed | "Description wording changed on field 'en'." |
| `DESC-REMOVED` | documentation | description removed | "Description removed from 'uart.ctrl'." |
| `METADATA-ADDED` | compatible | display-name metadata added | "Display-name metadata added." |
| `METADATA-CHANGED` | informational | display-name metadata changed | "Display-name metadata on field 'en' changed." |
| `MATCH-UNCERTAIN` | uncertain | possible rename, not asserted | "reg 'r7' was removed and 2 added sibling(s) have identical content; possible rename but ambiguous — reporting both removal and addition." |

## Rename honesty policy

A rename is asserted (as `REG-RENAMED`/`BLOCK-RENAMED`, or
`REG-MOVED-AND-RENAMED`/`BLOCK-MOVED` when the offset also changed) **only**
when exactly one removed and one added sibling of the same kind have identical
subtree content hash and footprint — a unique content+footprint pair. Anything
ambiguous (multiple identical candidates, or same offset with different
content) emits `MATCH-UNCERTAIN` with the candidate list **plus** the plain
removal/addition records. The tool never silently upgrades a guess to a
rename. Asserted renames carry `confidence: likely`, never `certain`.

## Container-move propagation collapse

When a container moves, descendants whose offsets *within it* are unchanged are
not re-reported. One `BLOCK-MOVED` record carries `affectedRegisters` (the
subtree register count) instead of N child `REG-ADDRESS-CHANGED` records. This
keeps a one-line source change from producing thousands of redundant records
while remaining lossless (corpus scenario `difficult-09-one-line-thousands`).

## Definition-pair comparison caching

Register bodies are compared once per *(base definition, head definition)*
pair; the resulting change templates are instantiated per instance path. A
change to a shared register type used by 500 instances costs one comparison,
not 500.

## Policy overrides

```bash
regreview diff --base a.rdl --head b.rdl --policy my-policy.json
```

```json
{"rules": {"RESET-VALUE-CHANGED": "breaking", "DESC-CHANGED": "informational"}}
```

Overrides replace the classification per rule id; unknown classifications are
rejected. `MATCH-UNCERTAIN` records keep the `uncertain` classification unless
a policy explicitly escalates them to breaking — an uncertain match is never
allowed to masquerade as a definitive non-breaking result.

Note: `ADDR-OVERLAP-NEW` and `FIELD-OVERLAP-NEW` are defined in the policy but
not currently emitted by detection: systemrdl-compiler refuses to elaborate
specifications with overlapping instances or fields, so such changes surface
as `SPEC-COMPILE-FAILED` (breaking) instead — see corpus scenarios
`breaking-10-address-overlap-new` and `breaking-11-field-overlap-new`.
Overlaps that do elaborate (e.g. alias registers, additions over removed
space) are reported via `REG-ADDED-OVERLAPPING` / `FIELD-ADDED-OVERLAPPING`.
