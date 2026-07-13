"""Semantic diff engine over two canonical models.

Pipeline (deliberately separated):
  1. entity matching       (paths, then definition/instance rename heuristics)
  2. raw change detection  (structural comparison, no severity opinions)
  3. severity policy       (peakrdl_check.policy, versioned)
  4. explanation           (human message per change)
  5. formatting            (peakrdl_check.report)

Matching honesty: a rename is asserted only when exactly one removed and one
added sibling have identical content and footprint. Anything ambiguous emits
MATCH-UNCERTAIN *plus* the removal/addition changes — the tool never silently
upgrades a guess to a rename.

Propagation: when a container moves, descendants whose offsets within it are
unchanged are not re-reported; the container change carries the affected
register count. This keeps one-line source changes from producing thousands
of redundant address-change records while remaining lossless.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .policy import (BREAKING, CLASSIFICATION_ORDER, POLICY_VERSION,
                     UNCERTAIN, load_policy)

CERTAIN = "certain"
LIKELY = "likely"
UNSURE = "uncertain"


@dataclass
class Change:
    ruleId: str
    entityType: str
    entityKey: str
    message: str
    before: Optional[str] = None
    after: Optional[str] = None
    baseLocation: Optional[dict] = None
    headLocation: Optional[dict] = None
    confidence: str = CERTAIN
    affectedRegisters: Optional[int] = None
    candidates: Optional[list] = None
    classification: str = ""      # filled by policy application

    def to_dict(self) -> dict:
        d = {
            "ruleId": self.ruleId,
            "policyVersion": POLICY_VERSION,
            "classification": self.classification,
            "entityType": self.entityType,
            "entityKey": self.entityKey,
            "message": self.message,
            "before": self.before,
            "after": self.after,
            "baseLocation": self.baseLocation,
            "headLocation": self.headLocation,
            "confidence": self.confidence,
        }
        if self.affectedRegisters is not None:
            d["affectedRegisters"] = self.affectedRegisters
        if self.candidates:
            d["candidates"] = self.candidates
        return d


def _loc(decl) -> Optional[dict]:
    if decl is None or decl.src_file is None:
        return None
    return {"file": decl.src_file, "line": decl.src_line, "column": decl.src_col}


def _hex(v) -> str:
    return f"0x{v:x}" if isinstance(v, int) else (f"0x{v}" if v else "none")


class ModelDiffer:
    def __init__(self, base, head, policy=None, rename_detection=True):
        self.base = base
        self.head = head
        self.policy = policy or load_policy()
        self.rename_detection = rename_detection
        self.changes: list[Change] = []
        self._defpair_cache: dict[tuple, list] = {}
        # path -> decl
        self.bmap = {d.path: d for d in base.decls}
        self.hmap = {d.path: d for d in head.decls}
        self._children_b = self._children_index(base)
        self._children_h = self._children_index(head)
        self._subtree_b = self._subtree_hashes(base)
        self._subtree_h = self._subtree_hashes(head)
        # paths consumed by rename matching (suppress add/remove for definite renames)
        self._renamed_b: dict[str, str] = {}
        self._renamed_h: dict[str, str] = {}

    @staticmethod
    def _children_index(model) -> dict:
        idx: dict[Optional[int], list] = {}
        for d in model.decls:
            idx.setdefault(d.parent_id, []).append(d)
        return idx

    @staticmethod
    def _subtree_hashes(model) -> dict:
        """Bottom-up structural hash per decl (content + child layout)."""
        import hashlib
        by_parent: dict[Optional[int], list] = {}
        for d in model.decls:
            by_parent.setdefault(d.parent_id, []).append(d)
        hashes: dict[int, str] = {}

        def compute(d) -> str:
            h = hashes.get(d.decl_id)
            if h is not None:
                return h
            # The node's OWN offset is deliberately excluded: content identity
            # must survive a move so rename/move detection can work. Children
            # are encoded with their offsets (internal layout is content).
            parts = [d.def_hash, format(d.size, "x"),
                     json.dumps(d.array_dims), format(d.array_stride or 0, "x")]
            for c in by_parent.get(d.decl_id, ()):
                parts.append(c.name)
                parts.append(format(c.offset, "x"))
                parts.append(compute(c))
            h = hashlib.sha256("|".join(parts).encode()).hexdigest()
            hashes[d.decl_id] = h
            return h

        import sys
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 100000))
        try:
            for d in model.decls:
                compute(d)
        finally:
            sys.setrecursionlimit(old_limit)
        return hashes

    # ------------------------------------------------------------------
    def run(self) -> dict:
        self._match_and_renames()
        self._compare_matched()
        self._emit_adds_removes()
        self._apply_policy()
        # Deterministic ordering: severity group, then entity, then rule.
        order = {c: i for i, c in enumerate(CLASSIFICATION_ORDER)}
        self.changes.sort(key=lambda c: (order.get(c.classification, 99),
                                         c.entityKey, c.ruleId))
        summary = {c: 0 for c in CLASSIFICATION_ORDER}
        for c in self.changes:
            summary[c.classification] = summary.get(c.classification, 0) + 1
        return {
            "policyVersion": POLICY_VERSION,
            "base": {"top": self.base.top_name},
            "head": {"top": self.head.top_name},
            "summary": {k: v for k, v in summary.items() if v},
            "totalChanges": len(self.changes),
            "changes": [c.to_dict() for c in self.changes],
        }

    # ------------------------------------------------------------------
    # Stage 1: matching
    # ------------------------------------------------------------------
    def _match_and_renames(self):
        removed = [p for p in self.bmap if p not in self.hmap]
        added = [p for p in self.hmap if p not in self.bmap]
        if not self.rename_detection or (not removed and not added):
            return
        # Group by (parent path, kind); parent must exist on both sides.
        def parent_path(p):
            return p.rsplit(".", 1)[0] if "." in p else None

        def groups(paths, m):
            g: dict[tuple, list] = {}
            for p in paths:
                d = m[p]
                g.setdefault((parent_path(p), d.kind), []).append(d)
            return g

        rem_g = groups(removed, self.bmap)
        add_g = groups(added, self.hmap)
        for key, rems in rem_g.items():
            adds = add_g.get(key)
            if not adds:
                continue
            self._try_renames(rems, adds)

    def _try_renames(self, rems: list, adds: list):
        """Definite rename: unique content+footprint pair. Else uncertain."""
        sub_b, sub_h = self._subtree_b, self._subtree_h

        def sig(d, sub):
            return (sub[d.decl_id], format(d.offset, "x"))

        rem_by_sig: dict[tuple, list] = {}
        for r in rems:
            rem_by_sig.setdefault(sig(r, sub_b), []).append(r)
        add_by_sig: dict[tuple, list] = {}
        for a in adds:
            add_by_sig.setdefault(sig(a, sub_h), []).append(a)

        # Pass 1: identical content AND identical offset -> rename in place
        for s, rlist in list(rem_by_sig.items()):
            alist = add_by_sig.get(s)
            if alist and len(rlist) == 1 and len(alist) == 1:
                self._record_rename(rlist[0], alist[0], moved=False)
                rem_by_sig.pop(s)
                add_by_sig.pop(s)

        # Pass 2: identical content, different offset -> moved and renamed
        rem_by_content: dict[str, list] = {}
        for rlist in rem_by_sig.values():
            for r in rlist:
                rem_by_content.setdefault(sub_b[r.decl_id], []).append(r)
        add_by_content: dict[str, list] = {}
        for alist in add_by_sig.values():
            for a in alist:
                add_by_content.setdefault(sub_h[a.decl_id], []).append(a)
        for h, rlist in rem_by_content.items():
            alist = add_by_content.get(h)
            if alist and len(rlist) == 1 and len(alist) == 1:
                self._record_rename(rlist[0], alist[0], moved=True)
            elif alist:
                # Multiple identical candidates: refuse to guess.
                for r in rlist:
                    self.changes.append(Change(
                        ruleId="MATCH-UNCERTAIN", entityType=r.kind,
                        entityKey=r.path, confidence=UNSURE,
                        message=(f"{r.kind} '{r.path}' was removed and "
                                 f"{len(alist)} added sibling(s) have identical "
                                 f"content; possible rename but ambiguous — "
                                 f"reporting both removal and addition."),
                        candidates=sorted(a.path for a in alist),
                        baseLocation=_loc(r)))

        # Pass 3: same offset+kind but different content -> possible in-place
        # replacement; flag uncertain (could be rename+edit or remove+add).
        still_rem = [r for r in rems
                     if r.path not in self._renamed_b
                     and not any(c.entityKey == r.path and c.ruleId == "MATCH-UNCERTAIN"
                                 for c in self.changes)]
        still_add = [a for a in adds if a.path not in self._renamed_h]
        by_off_add = {}
        for a in still_add:
            by_off_add.setdefault(a.offset, []).append(a)
        for r in still_rem:
            cands = by_off_add.get(r.offset, [])
            if len(cands) == 1 and cands[0].kind == r.kind:
                a = cands[0]
                self.changes.append(Change(
                    ruleId="MATCH-UNCERTAIN", entityType=r.kind,
                    entityKey=r.path, confidence=UNSURE,
                    message=(f"{r.kind} '{r.name}' was removed and '{a.name}' "
                             f"added at the same offset {_hex(r.offset)} with "
                             f"different content; possible rename-with-edit — "
                             f"not assumed, reporting removal and addition."),
                    candidates=[a.path],
                    baseLocation=_loc(r), headLocation=_loc(a)))

    def _record_rename(self, b, h, moved: bool):
        self._renamed_b[b.path] = h.path
        self._renamed_h[h.path] = b.path
        if moved:
            self.changes.append(Change(
                ruleId=("REG-MOVED-AND-RENAMED" if b.kind == "reg"
                        else "BLOCK-MOVED"),
                entityType=b.kind, entityKey=b.path,
                before=f"{b.path} @ {_hex(b.addr)}",
                after=f"{h.path} @ {_hex(h.addr)}",
                confidence=LIKELY,
                affectedRegisters=b.reg_count or None,
                message=(f"{b.kind} '{b.path}' appears renamed to '{h.path}' "
                         f"and moved from {_hex(b.addr)} to {_hex(h.addr)} "
                         f"(content identical)."),
                baseLocation=_loc(b), headLocation=_loc(h)))
        else:
            self.changes.append(Change(
                ruleId="REG-RENAMED" if b.kind == "reg" else "BLOCK-RENAMED",
                entityType=b.kind, entityKey=b.path,
                before=b.name, after=h.name, confidence=LIKELY,
                message=(f"{b.kind} '{b.path}' renamed to '{h.name}' "
                         f"(address {_hex(b.addr)} and content unchanged). "
                         f"Software symbols change; hardware layout does not."),
                baseLocation=_loc(b), headLocation=_loc(h)))
        # Content identical, but the matched pair may still sit under a moved
        # parent; address comparison for children is handled via the parent.

    # ------------------------------------------------------------------
    # Stage 2: comparison of matched entities
    # ------------------------------------------------------------------
    def _compare_matched(self):
        for path, b in self.bmap.items():
            h = self.hmap.get(path)
            if h is None or h.kind != b.kind:
                continue
            self._compare_decl(b, h)
        # Renamed pairs (content identical by construction) need no body diff.

    def _parent_moved(self, b, h) -> bool:
        """True if some matched ancestor's address changed (so this node's
        absolute move is already covered by the ancestor's change record)."""
        bp = b.path.rsplit(".", 1)[0] if "." in b.path else None
        hp = h.path.rsplit(".", 1)[0] if "." in h.path else None
        if bp is None or hp is None:
            return False
        pb, ph = self.bmap.get(bp), self.hmap.get(hp)
        return pb is not None and ph is not None and pb.addr != ph.addr

    def _compare_decl(self, b, h):
        kind = b.kind
        # Address: compare offset-in-parent to avoid propagation spam.
        if b.offset != h.offset or (b.addr != h.addr and not self._parent_moved(b, h)):
            rule = "REG-ADDRESS-CHANGED" if kind == "reg" else "BLOCK-MOVED"
            self.changes.append(Change(
                ruleId=rule, entityType=kind, entityKey=b.path,
                before=_hex(b.addr), after=_hex(h.addr),
                affectedRegisters=(b.reg_count if kind != "reg" else
                                   (b.total_elements if b.array_dims else None)),
                message=(f"{kind} '{b.path}' address changed from {_hex(b.addr)} "
                         f"to {_hex(h.addr)}"
                         + (f", moving all {b.reg_count} registers beneath it."
                            if kind != "reg" and b.reg_count else ".")),
                baseLocation=_loc(b), headLocation=_loc(h)))
        if (b.array_dims or None) != (h.array_dims or None):
            self.changes.append(Change(
                ruleId="ARRAY-DIMS-CHANGED", entityType=kind, entityKey=b.path,
                before=str(b.array_dims), after=str(h.array_dims),
                affectedRegisters=abs((h.total_elements - b.total_elements)
                                      * max(1, b.reg_count if kind != "reg" else 1)),
                message=(f"{kind} '{b.path}' array dimensions changed from "
                         f"{b.array_dims} to {h.array_dims}; element addresses "
                         f"and the overall footprint change."),
                baseLocation=_loc(b), headLocation=_loc(h)))
        elif b.array_dims and b.array_stride != h.array_stride:
            self.changes.append(Change(
                ruleId="ARRAY-STRIDE-CHANGED", entityType=kind, entityKey=b.path,
                before=_hex(b.array_stride), after=_hex(h.array_stride),
                message=(f"{kind} '{b.path}' array stride changed from "
                         f"{_hex(b.array_stride)} to {_hex(h.array_stride)}; "
                         f"every element beyond [0] moves."),
                baseLocation=_loc(b), headLocation=_loc(h)))
        if b.def_hash != h.def_hash:
            bdef = self.base.definitions[b.def_hash]
            hdef = self.head.definitions[h.def_hash]
            if kind == "reg":
                for tmpl in self._compare_reg_defs(b.def_hash, h.def_hash,
                                                   bdef.body, hdef.body):
                    c = Change(**{**tmpl, "entityKey": tmpl["entityKey"].format(path=b.path)})
                    c.baseLocation = _loc(b)
                    c.headLocation = _loc(h)
                    self.changes.append(c)
            else:
                self._compare_desc(b, h, bdef.body.get("desc", ""),
                                   hdef.body.get("desc", ""))

    def _compare_desc(self, b, h, bd, hd, entity_suffix=""):
        key = b.path + entity_suffix
        if bd == hd:
            return
        if not bd and hd:
            self.changes.append(Change(
                ruleId="DESC-ADDED", entityType=b.kind, entityKey=key,
                after=hd[:120], message=f"Description added to '{key}'.",
                baseLocation=_loc(b), headLocation=_loc(h)))
        elif bd and not hd:
            self.changes.append(Change(
                ruleId="DESC-REMOVED", entityType=b.kind, entityKey=key,
                before=bd[:120], message=f"Description removed from '{key}'.",
                baseLocation=_loc(b), headLocation=_loc(h)))
        else:
            self.changes.append(Change(
                ruleId="DESC-CHANGED", entityType=b.kind, entityKey=key,
                before=bd[:120], after=hd[:120],
                message=f"Description wording changed on '{key}'.",
                baseLocation=_loc(b), headLocation=_loc(h)))

    # ---- register definition comparison (cached per def pair) ----

    def _compare_reg_defs(self, bh, hh, bbody, hbody) -> list:
        """Return change templates with '{path}' placeholders, cached per
        (base def, head def) pair so shared-type changes are computed once
        no matter how many instances they affect."""
        cache_key = (bh, hh)
        cached = self._defpair_cache.get(cache_key)
        if cached is not None:
            return cached
        out: list[dict] = []

        def add(ruleId, entity_suffix, message, before=None, after=None,
                confidence=CERTAIN):
            out.append(dict(ruleId=ruleId, entityType="field" if entity_suffix else "reg",
                            entityKey="{path}" + entity_suffix,
                            message=message, before=before, after=after,
                            confidence=confidence))

        bw, hw = bbody.get("regwidth"), hbody.get("regwidth")
        if bw != hw:
            add("REG-WIDTH-REDUCED" if hw < bw else "REG-WIDTH-INCREASED", "",
                f"Register width changed from {bw} to {hw} bits.",
                before=str(bw), after=str(hw))
        bd, hd = bbody.get("desc", ""), hbody.get("desc", "")
        if bd != hd:
            if not bd and hd:
                add("DESC-ADDED", "", "Description added.", after=hd[:120])
            elif bd and not hd:
                add("DESC-REMOVED", "", "Description removed.", before=bd[:120])
            else:
                add("DESC-CHANGED", "", "Description wording changed.",
                    before=bd[:120], after=hd[:120])

        if bbody.get("display_name") != hbody.get("display_name"):
            bd_, hd_ = bbody.get("display_name"), hbody.get("display_name")
            add("METADATA-ADDED" if not bd_ else "METADATA-CHANGED", "",
                f"Display-name metadata {'added' if not bd_ else 'changed'}.",
                before=bd_, after=hd_)

        bfields = {f["name"]: f for f in bbody.get("fields", [])}
        hfields = {f["name"]: f for f in hbody.get("fields", [])}

        # Occupied bits in base (for classifying added fields)
        base_bits = 0
        for f in bfields.values():
            base_bits |= ((1 << (f["msb"] - f["lsb"] + 1)) - 1) << f["lsb"]

        removed = [n for n in bfields if n not in hfields]
        added = [n for n in hfields if n not in bfields]

        # Field rename: removed+added pair identical except the name.
        def stripped(f):
            return {k: v for k, v in f.items() if k != "name"}
        for rn in list(removed):
            twins = [an for an in added if stripped(hfields[an]) == stripped(bfields[rn])]
            if len(twins) == 1:
                an = twins[0]
                add("FIELD-RENAMED", f".{rn}",
                    f"Field '{rn}' renamed to '{an}' (bits, access, reset "
                    f"unchanged). Software symbols change only.",
                    before=rn, after=an, confidence=LIKELY)
                removed.remove(rn)
                added.remove(an)

        for n in removed:
            f = bfields[n]
            add("FIELD-REMOVED", f".{n}",
                f"Field '{n}' [{f['msb']}:{f['lsb']}] was removed.",
                before=f"[{f['msb']}:{f['lsb']}] sw={f['sw']}")
        for n in added:
            f = hfields[n]
            mask = ((1 << (f["msb"] - f["lsb"] + 1)) - 1) << f["lsb"]
            if mask & base_bits:
                add("FIELD-ADDED-OVERLAPPING", f".{n}",
                    f"Field '{n}' added at [{f['msb']}:{f['lsb']}], overlapping "
                    f"bits that were previously used by other fields.",
                    after=f"[{f['msb']}:{f['lsb']}] sw={f['sw']}")
            else:
                add("FIELD-ADDED-UNUSED-BITS", f".{n}",
                    f"Field '{n}' added at [{f['msb']}:{f['lsb']}] in previously "
                    f"unused bits.",
                    after=f"[{f['msb']}:{f['lsb']}] sw={f['sw']}")

        for n, bf in bfields.items():
            hf = hfields.get(n)
            if hf is None:
                continue
            self._compare_field(add, n, bf, hf)

        self._defpair_cache[cache_key] = out
        return out

    def _compare_field(self, add, name, bf, hf):
        sfx = f".{name}"
        if bf["lsb"] != hf["lsb"]:
            add("FIELD-OFFSET-CHANGED", sfx,
                f"Field '{name}' moved from bit {bf['lsb']} to bit {hf['lsb']}.",
                before=f"[{bf['msb']}:{bf['lsb']}]", after=f"[{hf['msb']}:{hf['lsb']}]")
        bw = bf["msb"] - bf["lsb"] + 1
        hw = hf["msb"] - hf["lsb"] + 1
        if bw != hw:
            add("FIELD-WIDTH-REDUCED" if hw < bw else "FIELD-WIDTH-INCREASED", sfx,
                f"Field '{name}' width changed from {bw} to {hw} bits.",
                before=f"{bw} bits", after=f"{hw} bits")
        if bf["sw"] != hf["sw"]:
            rule = self._sw_access_rule(bf["sw"], hf["sw"])
            add(rule, sfx,
                f"Field '{name}' software access changed from {bf['sw']} to {hf['sw']}.",
                before=bf["sw"], after=hf["sw"],
                confidence=CERTAIN if rule != "ACCESS-CHANGED-AMBIGUOUS" else UNSURE)
        if bf.get("hw") != hf.get("hw"):
            add("HW-ACCESS-CHANGED", sfx,
                f"Field '{name}' hardware access changed from {bf.get('hw')} "
                f"to {hf.get('hw')}.",
                before=bf.get("hw"), after=hf.get("hw"))
        if bf.get("reset") != hf.get("reset"):
            br, hr = bf.get("reset"), hf.get("reset")
            if br is None:
                add("RESET-ADDED", sfx, f"Field '{name}' gained a reset value.",
                    after=_hex(hr))
            elif hr is None:
                add("RESET-REMOVED", sfx, f"Field '{name}' no longer has a reset value.",
                    before=_hex(br))
            else:
                add("RESET-VALUE-CHANGED", sfx,
                    f"Field '{name}' reset value changed from {_hex(br)} to {_hex(hr)}.",
                    before=_hex(br), after=_hex(hr))
        if bf.get("volatile") != hf.get("volatile"):
            add("VOLATILITY-CHANGED", sfx,
                f"Field '{name}' volatility changed from {bf.get('volatile')} "
                f"to {hf.get('volatile')}; read-back guarantees differ.",
                before=str(bf.get("volatile")), after=str(hf.get("volatile")))
        for prop, rule in (("intr", "INTERRUPT-CHANGED"),
                           ("counter", "COUNTER-CHANGED")):
            if bool(bf.get(prop)) != bool(hf.get(prop)):
                add(rule, sfx,
                    f"Field '{name}' {prop} behaviour "
                    f"{'enabled' if hf.get(prop) else 'disabled'}; "
                    f"{'interrupt' if prop == 'intr' else 'counter'} semantics "
                    f"of this field changed.",
                    before=str(bool(bf.get(prop))), after=str(bool(hf.get(prop))))
        if bf.get("display_name") != hf.get("display_name"):
            bd_, hd_ = bf.get("display_name"), hf.get("display_name")
            add("METADATA-ADDED" if not bd_ else "METADATA-CHANGED", sfx,
                f"Display-name metadata on field '{name}' "
                f"{'added' if not bd_ else 'changed'}.",
                before=bd_, after=hd_)
        for prop, rule in (("onread", "ONREAD-CHANGED"), ("onwrite", "ONWRITE-CHANGED")):
            if bf.get(prop) != hf.get(prop):
                add(rule, sfx,
                    f"Field '{name}' {prop} side-effect changed from "
                    f"{bf.get(prop)} to {hf.get(prop)}.",
                    before=str(bf.get(prop)), after=str(hf.get(prop)))
        if bf.get("desc", "") != hf.get("desc", ""):
            bd, hd = bf.get("desc", ""), hf.get("desc", "")
            if not bd and hd:
                add("DESC-ADDED", sfx, f"Description added to field '{name}'.",
                    after=hd[:120])
            elif bd and not hd:
                add("DESC-REMOVED", sfx, f"Description removed from field '{name}'.",
                    before=bd[:120])
            else:
                add("DESC-CHANGED", sfx,
                    f"Description wording changed on field '{name}'.",
                    before=bd[:120], after=hd[:120])
        self._compare_enums(add, name, bf.get("encode"), hf.get("encode"))

    @staticmethod
    def _sw_access_rule(before: str, after: str) -> str:
        """Classify a software-access transition.

        SystemRDL sw values: r, w, rw, w1, rw1, na.
        """
        readable = {"r", "rw", "rw1"}
        writable = {"w", "rw", "w1", "rw1"}

        b_r, b_w = before in readable, before in writable
        a_r, a_w = after in readable, after in writable

        if b_r and b_w and a_r and not a_w:
            return "ACCESS-RW-TO-RO"           # rw -> r: writes now dropped
        if b_r and not a_r and a_w:
            return "ACCESS-READABLE-TO-WO"     # readable -> write-only
        if a_r >= b_r and a_w >= b_w and (a_r > b_r or a_w > b_w):
            return "ACCESS-WIDENED"            # strictly more capability
        return "ACCESS-CHANGED-AMBIGUOUS"      # anything else: don't guess

    def _compare_enums(self, add, name, be, he):
        sfx = f".{name}"
        if be is None and he is None:
            return
        if be is None:
            add("ENUM-ADDED", sfx, f"Field '{name}' gained an enumeration.")
            return
        if he is None:
            add("ENUM-REMOVED", sfx, f"Field '{name}' no longer has an enumeration.")
            return
        bm = {m[0]: m for m in be}
        hm = {m[0]: m for m in he}
        bv = {m[1]: m for m in be}
        hv = {m[1]: m for m in he}
        for n, m in bm.items():
            hm_m = hm.get(n)
            if hm_m is None:
                # renamed (same value exists under a new name)?
                twin = hv.get(m[1])
                if twin is not None and twin[0] not in bm:
                    add("ENUM-VALUE-RENAMED", sfx,
                        f"Enum member '{n}' (={_hex(m[1])}) renamed to "
                        f"'{twin[0]}' in field '{name}'.",
                        before=n, after=twin[0], confidence=LIKELY)
                else:
                    add("ENUM-VALUE-REMOVED", sfx,
                        f"Enum member '{n}' (={_hex(m[1])}) removed from "
                        f"field '{name}'.", before=f"{n}={_hex(m[1])}")
            elif hm_m[1] != m[1]:
                add("ENUM-VALUE-CHANGED", sfx,
                    f"Enum member '{n}' in field '{name}' changed value from "
                    f"{_hex(m[1])} to {_hex(hm_m[1])}; existing encodings break.",
                    before=_hex(m[1]), after=_hex(hm_m[1]))
        for n, m in hm.items():
            if n not in bm and m[1] not in bv:
                add("ENUM-VALUE-ADDED", sfx,
                    f"Enum member '{n}' (={_hex(m[1])}) added to field '{name}' "
                    f"without modifying existing members.",
                    after=f"{n}={_hex(m[1])}")

    # ------------------------------------------------------------------
    # Stage 2b: additions/removals (not consumed by rename matching)
    # ------------------------------------------------------------------
    def _emit_adds_removes(self):
        base_spans = self._reg_spans(self.base)
        for path, b in self.bmap.items():
            if path in self.hmap or path in self._renamed_b:
                continue
            rule = "REG-REMOVED" if b.kind == "reg" else "BLOCK-REMOVED"
            self.changes.append(Change(
                ruleId=rule, entityType=b.kind, entityKey=path,
                before=_hex(b.addr),
                affectedRegisters=b.reg_count if b.kind != "reg" else
                (b.total_elements if b.array_dims else None),
                message=(f"{b.kind} '{path}' at {_hex(b.addr)} was removed"
                         + (f" (containing {b.reg_count} registers)."
                            if b.kind != "reg" and b.reg_count else ".")),
                baseLocation=_loc(b)))
        for path, h in self.hmap.items():
            if path in self.bmap or path in self._renamed_h:
                continue
            if h.kind == "reg" and h.is_alias:
                rule = "REG-ALIAS-ADDED"
                msg = (f"alias register '{path}' added at {_hex(h.addr)}; "
                       f"it augments access to existing storage without "
                       f"changing existing addresses.")
            elif h.kind == "reg":
                overlaps = self._overlaps_base(h, base_spans)
                rule = ("REG-ADDED-OVERLAPPING" if overlaps
                        else "REG-ADDED-UNUSED-SPACE")
                msg = (f"reg '{path}' added at {_hex(h.addr)} "
                       + ("overlapping address space previously used by "
                          f"'{overlaps}'." if overlaps
                          else "in previously unused address space."))
            else:
                rule = "BLOCK-ADDED"
                msg = f"{h.kind} '{path}' added at {_hex(h.addr)}."
            self.changes.append(Change(
                ruleId=rule, entityType=h.kind, entityKey=path,
                after=_hex(h.addr), message=msg, headLocation=_loc(h)))

    @staticmethod
    def _reg_spans(model) -> list:
        spans = [(d.addr, d.addr_span_end, d.path)
                 for d in model.decls if d.kind == "reg"]
        spans.sort()
        return spans

    @staticmethod
    def _overlaps_base(h, spans) -> Optional[str]:
        import bisect
        lo, hi = h.addr, h.addr_span_end
        i = bisect.bisect_right(spans, (lo, ))
        # check neighbours around insertion point
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(spans):
                s_lo, s_hi, s_path = spans[j]
                if s_lo <= hi and s_hi >= lo:
                    return s_path
        return None

    # ------------------------------------------------------------------
    def _apply_policy(self):
        for c in self.changes:
            c.classification = self.policy.get(c.ruleId, UNCERTAIN)
            if c.confidence == UNSURE and c.classification not in (BREAKING,):
                # never let an uncertain match masquerade as definitive
                if c.ruleId == "MATCH-UNCERTAIN":
                    c.classification = UNCERTAIN


def diff_models(base, head, policy=None, rename_detection=True) -> dict:
    return ModelDiffer(base, head, policy=policy,
                       rename_detection=rename_detection).run()


def compile_failed_result(stage: str, error: str) -> dict:
    """Diff result when the head specification no longer elaborates."""
    ch = Change(
        ruleId="SPEC-COMPILE-FAILED", entityType="specification",
        entityKey=stage, confidence=CERTAIN,
        message=(f"The {stage} specification failed to compile/elaborate: "
                 f"{error.strip()[:500]}"),
        after=error.strip()[:200])
    ch.classification = BREAKING
    return {
        "policyVersion": POLICY_VERSION,
        "summary": {BREAKING: 1},
        "totalChanges": 1,
        "changes": [ch.to_dict()],
        "compileError": {"stage": stage, "message": error.strip()[:2000]},
    }
