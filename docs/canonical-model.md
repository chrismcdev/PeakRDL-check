# The canonical model

`peakrdl_check/canonical.py` defines the tool-independent representation that
storage, diffing and reporting operate on. Only the adapter
(`peakrdl_check/adapter.py`) produces it; nothing downstream imports
systemrdl-compiler.

## Two entity kinds

### Definition — deduplicated content

The elaborated *content* of a component, identified by a sha256 content hash of
its canonical JSON body (`content_hash({"kind": ..., "body": ...})`). Two
instances whose effective semantics differ hash differently and are therefore
never merged.

Register body:

| Key | Meaning |
|---|---|
| `regwidth` | register width in bits |
| `desc` | description text (`""` if absent) |
| `fields[]` | list of field dicts, see below |
| `display_name` | only when a `name` property differs from the instance name |

Field dict keys: `name`, `lsb`, `msb`, `width`, `sw`, `hw`, `onread`,
`onwrite`, `volatile`, `reset` (variable-width hex string or `null`), `desc`,
`encode` (list of `[name, value_hex, desc]` or absent), plus `intr`,
`counter`, `display_name` — the last three stored only when set, to keep
bodies small.

Container bodies (`addrmap`/`regfile`) carry `desc`; `mem` additionally
carries `mementries` and `memwidth`.

### Decl — one instance row

One `Decl` per *declared* instance in the elaborated tree, arrays folded:

| Field | Meaning |
|---|---|
| `decl_id`, `parent_id`, `sort_key` | tree identity and declaration order |
| `kind` | `addrmap` \| `regfile` \| `reg` \| `mem` |
| `name`, `path` | instance name; dotted hierarchical path from top |
| `def_hash` | content hash of its Definition |
| `addr`, `offset`, `size` | absolute address of element `[0..0]`, offset in parent, element size — all arbitrary-precision Python ints |
| `array_dims`, `array_stride` | folded array geometry (`None` if scalar) |
| `reg_count` | unrolled registers in this subtree (including self) |
| `src_file`, `src_offset`, `src_line`, `src_col` | source location (mode-dependent) |
| `block_id` | enclosing incremental unit (block-root decl_id) |
| `is_alias` | alias register (shares primary's storage) |
| `type_name`, `def_file`, `params`, `params_supported` | block roots only: source type, defining file, resolved parameter values |

Element addresses are exact and computed arithmetically:
`element_addr(i) = addr + i * stride`. An element is never materialised as its
own row anywhere in the system.

## Numeric representation

- All addresses, offsets, sizes, resets and masks are **Python ints**
  (arbitrary precision) in memory.
- On disk, ordering-sensitive values are **zero-padded 32-character lowercase
  hex** (128-bit range), so lexicographic order equals numeric order
  (`addr_to_hex` / `hex_to_addr`).
- **Floats are never used** — no rounding, no 2^53 cliffs, no equality
  surprises at large addresses.

## Per-instance extraction (and the rejected cache)

SystemRDL permits *dynamic property assignments*: an instance can override
properties of its component type (`inst_name->property = value;`). Two
instances of the same `original_def` can therefore have different effective
semantics.

An extraction cache keyed on `id(original_def)` was implemented and measured:
it saved **less than 0.2 s at 100k registers** — and it is unsafe, because it
would merge instances that share an `original_def` but differ under dynamic
property assignment. It was rejected.

Extraction therefore always runs **per declared instance**; deduplication
happens afterwards via content hashing, which is exact — instances with
genuinely identical elaborated content share a Definition, instances that
differ in any semantic way never do. The trade-off and its measurement are
recorded in a comment in `adapter.py` (`_Extractor.__init__`) and in
[ADR-0001](adr/0001-canonical-domain-model.md).

## Versioning

`CANONICAL_SCHEMA_VERSION` (currently 1, `peakrdl_check/__init__.py`) is bumped on
any change to the entity representation or hashing scheme; cached artifacts are
keyed on it.
