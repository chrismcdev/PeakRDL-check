"""systemrdl-compiler → canonical model adapter.

This is the only module allowed to import systemrdl. It compiles source,
elaborates, and walks the elaborated tree (arrays folded) emitting canonical
``Definition`` and ``Decl`` objects, with per-stage timings.

Source-location modes:
* ``none``      — no source locations extracted.
* ``registers`` — locations for addressable components (addrmap/regfile/reg/mem).
* ``all``       — additionally resolves line/column for every location
                  (fields inherit their register's location in v1).

Line/column resolution uses regreview.lineindex (bisect over a per-file
line-start table) instead of upstream's per-lookup file rescan; if the
private offset attributes are unavailable it falls back to the upstream API.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from .canonical import Decl, Definition, content_hash, int_to_hexstr
from .lineindex import SourceLineIndex


@dataclass
class StageTimings:
    parse_s: float = 0.0
    elaborate_s: float = 0.0
    traverse_s: float = 0.0
    validation_messages: int = 0

    def to_dict(self) -> dict:
        return {
            "parseSeconds": round(self.parse_s, 3),
            "elaborateSeconds": round(self.elaborate_s, 3),
            "traverseSeconds": round(self.traverse_s, 3),
        }


@dataclass
class CanonicalModel:
    """Full canonical model of one elaborated specification."""
    top_name: str
    definitions: dict            # hash -> Definition
    decls: list                  # list[Decl], parents before children
    timings: StageTimings
    source_mode: str
    src_files: list = field(default_factory=list)
    tool_versions: dict = field(default_factory=dict)


def _enum_to_canonical(enum_type) -> list:
    members = []
    for m in enum_type:
        members.append([
            m.name,
            int_to_hexstr(int(m.value)),
            (m.rdl_desc or m.rdl_name or ""),
        ])
    return members


class _Extractor:
    def __init__(self, source_mode: str):
        self.source_mode = source_mode
        self.line_index = SourceLineIndex()
        self.defs: dict[str, Definition] = {}
        # Note: an id(original_def)-keyed extraction cache was measured at
        # 100k registers and saved <0.2s while being unsafe under dynamic
        # property assignments (same original_def, different semantics).
        # Extraction therefore always runs per declared instance; dedup
        # happens via content hashing, which is exact.
        self._cache_hits = 0
        self._cache_misses = 0

    # ---- source locations ----

    def src_of(self, node) -> tuple:
        """Return (path, char_offset, line, col) subject to source mode."""
        if self.source_mode == "none":
            return (None, None, None, None)
        sr = node.inst.inst_src_ref
        if sr is None:
            return (None, None, None, None)
        try:
            path = sr.path  # resolves segment map for included files
        except Exception:
            return (None, None, None, None)
        offset = getattr(sr, "_start_idx", None)
        line = col = None
        if self.source_mode == "all" and path is not None and offset is not None:
            try:
                line, col = self.line_index.resolve(path, offset)
            except OSError:
                # File unreadable post-compile; fall back to upstream slow path.
                try:
                    line = sr.line
                except Exception:
                    line = None
        return (path, offset, line, col)

    # ---- definition extraction ----

    def _field_canonical(self, f) -> dict:
        get = f.get_property
        sw = get("sw")
        hw = get("hw")
        onread = get("onread")
        onwrite = get("onwrite")
        reset = get("reset")
        encode = get("encode")
        d = {
            "name": f.inst_name,
            "lsb": f.lsb,
            "msb": f.msb,
            "width": f.width,
            "sw": sw.name if sw else None,
            "hw": hw.name if hw else None,
            "onread": onread.name if onread else None,
            "onwrite": onwrite.name if onwrite else None,
            "volatile": bool(f.is_volatile),
            "reset": int_to_hexstr(int(reset)) if isinstance(reset, int) else None,
            "desc": get("desc") or "",
        }
        if encode is not None:
            d["encode"] = _enum_to_canonical(encode)
        return d

    def reg_def(self, node) -> str:
        """Extract the canonical definition of a register (content-hash dedup)."""
        self._cache_misses += 1
        fields = [self._field_canonical(f) for f in node.fields()]
        body = {
            "regwidth": node.get_property("regwidth"),
            "desc": node.get_property("desc") or "",
            "fields": fields,
        }
        h = content_hash({"kind": "reg", "body": body})
        if h not in self.defs:
            self.defs[h] = Definition(kind="reg", type_name=node.inst.type_name,
                                      body=body, hash=h)
        return h

    def container_def(self, node, kind: str) -> str:
        body = {"desc": node.get_property("desc") or ""}
        if kind == "mem":
            body["mementries"] = int(node.get_property("mementries"))
            body["memwidth"] = int(node.get_property("memwidth"))
        h = content_hash({"kind": kind, "body": body})
        if h not in self.defs:
            self.defs[h] = Definition(kind=kind, type_name=node.inst.type_name,
                                      body=body, hash=h)
        return h


def build_canonical(rdl_files: list, top: Optional[str] = None,
                    source_mode: str = "registers",
                    incl_search_paths: Optional[list] = None) -> CanonicalModel:
    """Compile SystemRDL sources and produce the canonical model."""
    from systemrdl import RDLCompiler
    from systemrdl.node import (AddrmapNode, FieldNode, MemNode, RegfileNode,
                                RegNode, SignalNode)
    import systemrdl

    assert source_mode in ("none", "registers", "all")

    timings = StageTimings()
    rdlc = RDLCompiler()

    t0 = time.perf_counter()
    for f in rdl_files:
        rdlc.compile_file(str(f), incl_search_paths=incl_search_paths)
    timings.parse_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    root = rdlc.elaborate(top_def_name=top)
    timings.elaborate_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    ex = _Extractor(source_mode)
    decls: list[Decl] = []
    next_id = 0

    kind_of = {AddrmapNode: "addrmap", RegfileNode: "regfile",
               RegNode: "reg", MemNode: "mem"}

    def walk(node, parent_id: Optional[int], parent_path: str) -> tuple:
        """Emit decls for node's children; return (reg_count, child_ids)."""
        nonlocal next_id
        subtree_regs = 0
        for child in node.children(unroll=False):
            if isinstance(child, (FieldNode, SignalNode)):
                continue
            kind = kind_of.get(type(child))
            if kind is None:
                continue
            my_id = next_id
            next_id += 1
            name = child.inst_name
            path = f"{parent_path}.{name}" if parent_path else name

            is_array = bool(child.is_array)
            dims = list(child.array_dimensions) if is_array else None
            stride = int(child.array_stride) if is_array and child.array_stride is not None else None
            elements = 1
            if dims:
                for d in dims:
                    elements *= d

            addr = int(child.raw_absolute_address)
            offset = int(child.raw_address_offset)
            size = int(child.size)

            src_path, src_off, src_line, src_col = ex.src_of(child)

            if isinstance(child, RegNode):
                def_hash = ex.reg_def(child)
                regs_here = elements
                d = Decl(decl_id=my_id, parent_id=parent_id, kind=kind,
                         name=name, path=path, def_hash=def_hash,
                         addr=addr, offset=offset, size=size,
                         array_dims=dims, array_stride=stride,
                         reg_count=regs_here,
                         src_file=src_path, src_offset=src_off,
                         src_line=src_line, src_col=src_col,
                         sort_key=my_id)
                decls.append(d)
                subtree_regs += regs_here
            else:
                def_hash = ex.container_def(child, kind)
                d = Decl(decl_id=my_id, parent_id=parent_id, kind=kind,
                         name=name, path=path, def_hash=def_hash,
                         addr=addr, offset=offset, size=size,
                         array_dims=dims, array_stride=stride,
                         reg_count=0,
                         src_file=src_path, src_offset=src_off,
                         src_line=src_line, src_col=src_col,
                         sort_key=my_id)
                decls.append(d)
                inner_regs = walk(child, my_id, path)
                d.reg_count = inner_regs * elements
                subtree_regs += d.reg_count
        return subtree_regs

    top_node = root.top
    top_name = top_node.inst_name
    total = walk(top_node, None, "")
    timings.traverse_s = time.perf_counter() - t0

    src_files = sorted({d.src_file for d in decls if d.src_file}) or [str(f) for f in rdl_files]

    model = CanonicalModel(
        top_name=top_name,
        definitions=ex.defs,
        decls=decls,
        timings=timings,
        source_mode=source_mode,
        src_files=src_files,
        tool_versions={"systemrdl-compiler": systemrdl.__version__},
    )
    # Stash cache stats for benchmarking visibility
    model.def_cache_stats = {"hits": ex._cache_hits, "misses": ex._cache_misses}
    model.total_regs = total
    return model
