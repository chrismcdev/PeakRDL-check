"""Canonical register model.

The canonical model is the tool-independent representation that storage,
diffing and reporting operate on. It never depends on systemrdl-compiler
internals; the adapter produces it, everything else consumes it.

Representation
--------------
* ``Definition`` — deduplicated elaborated *content* of a component
  (register fields, enums, properties), identified by a content hash of its
  canonical JSON body. Two instances whose effective semantics differ hash
  differently and are therefore never merged.
* ``Decl`` — one declared instance in the elaborated tree. Arrays are kept
  folded (one Decl with dimensions/stride); element addresses are exact and
  computed arithmetically. This is the definition/instance deduplication the
  storage layer builds on.

All addresses, offsets, resets and masks are Python ints (arbitrary
precision) in memory and zero-padded fixed-width hex strings on disk so that
lexicographic order equals numeric order. Floats are never used.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

# Fixed storage width for addresses: 128-bit. Lexicographic == numeric order.
ADDR_HEX_WIDTH = 32
_ADDR_LIMIT = 1 << (4 * ADDR_HEX_WIDTH)


def addr_to_hex(value: int) -> str:
    """Encode an address/size as fixed-width lowercase hex."""
    if value < 0 or value >= _ADDR_LIMIT:
        raise ValueError(f"address out of supported 128-bit range: {value:#x}")
    return format(value, "032x")


def hex_to_addr(text: str) -> int:
    return int(text, 16)


def int_to_hexstr(value: Optional[int]) -> Optional[str]:
    """Variable-width hex for resets/masks (not used for ordering)."""
    if value is None:
        return None
    return format(value, "x")


def canonical_json(obj) -> str:
    """Deterministic JSON serialization (sorted keys, no whitespace drift)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(body: dict) -> str:
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


@dataclass
class Definition:
    """Deduplicated elaborated content of a component."""
    kind: str                 # addrmap | regfile | reg | mem
    type_name: Optional[str]
    body: dict                # canonical JSON-able content (fields, enums, props)
    hash: str = ""

    def finalize(self) -> "Definition":
        if not self.hash:
            self.hash = content_hash({"kind": self.kind, "body": self.body})
        return self


@dataclass
class Decl:
    """One declared instance in the elaborated tree (arrays folded)."""
    decl_id: int
    parent_id: Optional[int]
    kind: str                          # addrmap | regfile | reg | mem
    name: str                          # instance name (no array suffix)
    path: str                          # dotted hierarchical path from top
    def_hash: str
    addr: int                          # absolute byte address of element [0..0]
    offset: int                        # offset relative to parent
    size: int                          # size of one element in bytes
    array_dims: Optional[list] = None  # e.g. [512]; None if scalar
    array_stride: Optional[int] = None
    reg_count: int = 0                 # unrolled registers in this subtree (incl. self)
    src_file: Optional[str] = None
    src_offset: Optional[int] = None   # char offset within src_file
    src_line: Optional[int] = None
    src_col: Optional[int] = None
    sort_key: int = 0                  # declaration order within parent

    @property
    def total_elements(self) -> int:
        n = 1
        for d in self.array_dims or ():
            n *= d
        return n

    @property
    def addr_span_end(self) -> int:
        """Inclusive end address of the full (arrayed) footprint."""
        if self.array_dims and self.array_stride:
            return self.addr + self.array_stride * (self.total_elements - 1) + self.size - 1
        return self.addr + self.size - 1

    def element_addr(self, index: int) -> int:
        if not self.array_dims:
            if index != 0:
                raise IndexError("scalar instance")
            return self.addr
        if index < 0 or index >= self.total_elements:
            raise IndexError(f"array index {index} out of range 0..{self.total_elements - 1}")
        return self.addr + index * (self.array_stride or self.size)


def reg_body_from_fields(regwidth: int, desc: Optional[str], fields: list,
                         extra_props: Optional[dict] = None) -> dict:
    """Canonical body for a register definition.

    ``fields`` is a list of dicts with keys:
    name, lsb, msb, width, sw, hw, onread, onwrite, volatile, reset (hex str
    or None), desc, encode (list of [name, value_hex, desc] or None).
    """
    body = {
        "regwidth": regwidth,
        "desc": desc or "",
        "fields": fields,
    }
    if extra_props:
        body["props"] = extra_props
    return body
