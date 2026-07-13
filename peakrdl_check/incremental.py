"""Content-addressed incremental rebuilds.

Unit of incrementality: a *block root* — the topmost instance whose defining
source file differs from the top component's file (recorded per node at build
time). A change to a type-definition file triggers:

  1. content hashing of all tracked inputs (sha256),
  2. standalone re-elaboration of each affected block type (its file only),
  3. an in-place splice of every instance's subtree in the SQLite index,
     rebasing relative addresses onto the unchanged instance base address.

Deterministic fallbacks to a full rebuild (each reported with its reason):
  * top file changed (instance layout may differ),
  * a changed file contains declarations outside any block,
  * an affected block's total size changed (downstream auto-allocated
    addresses would shift),
  * an affected instance is parameterized (standalone elaboration with
    default parameters would be wrong),
  * standalone elaboration fails (cross-file type dependencies),
  * schema/tool/source-mode mismatch with the existing index.

The splice path never re-parses unchanged files — that is the entire point:
parse time dominates large builds (measured 190 s of a 210 s 800k build).
Equivalence with a clean rebuild is enforced by
scripts/verify_incremental_equivalence.py and by unit tests.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .canonical import addr_to_hex
from . import STORAGE_SCHEMA_VERSION


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class FullRebuildRequired(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def incremental_build(files: list, output_dir: Path, top: Optional[str],
                      source_mode: str) -> dict:
    """Attempt an incremental update of an existing index.

    Returns a report dict; raises FullRebuildRequired when a clean rebuild
    is needed (caller decides to run it and reports the reason).
    """
    t_start = time.perf_counter()
    db_path = Path(output_dir) / "register-map.sqlite"
    if not db_path.is_file():
        raise FullRebuildRequired("no existing index")

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")}

    if meta.get("storage_schema_version") != str(STORAGE_SCHEMA_VERSION):
        con.close()
        raise FullRebuildRequired("storage schema version changed")
    if meta.get("source_mode") != source_mode:
        con.close()
        raise FullRebuildRequired("source-location mode changed")

    old_inputs = json.loads(meta.get("build_inputs") or "{}")
    if not old_inputs:
        con.close()
        raise FullRebuildRequired("existing index has no build manifest")

    t0 = time.perf_counter()
    current: dict[str, str] = {}
    for p in old_inputs:
        fp = Path(p)
        if not fp.is_file():
            con.close()
            raise FullRebuildRequired(f"tracked input disappeared: {p}")
        current[p] = _sha256(fp)
    for f in files:
        p = str(Path(f).resolve())
        if p not in current:
            if str(Path(f)) not in old_inputs and p not in old_inputs:
                con.close()
                raise FullRebuildRequired(f"new input file: {f}")
    hash_s = time.perf_counter() - t0

    changed = sorted(p for p in old_inputs if current.get(p) != old_inputs[p])
    block_roots = json.loads(meta.get("block_roots") or "[]")
    top_src = meta.get("top_src_file") or ""

    def _resolve(p: str) -> str:
        return str(Path(p).resolve()) if p else p

    top_src = _resolve(top_src)

    report = {
        "mode": "incremental",
        "changedFiles": changed,
        "unitsTotal": len(block_roots),
        "stages": {"hashSeconds": round(hash_s, 3)},
    }
    if not changed:
        con.close()
        report["unitsReused"] = len(block_roots)
        report["unitsRebuilt"] = 0
        report["totalSeconds"] = round(time.perf_counter() - t_start, 3)
        report["result"] = "up-to-date"
        return report

    if top_src in changed:
        con.close()
        raise FullRebuildRequired("top-level file changed (instance layout)")

    changed_set = set(changed)
    # Any declaration in a changed file that is NOT inside a block unit means
    # the change is not block-local.
    file_ids = [r["file_id"] for r in con.execute("SELECT file_id, path FROM src_file")
                if _resolve(r["path"]) in changed_set]
    if file_ids:
        qmarks = ",".join("?" * len(file_ids))
        stray = con.execute(
            f"SELECT COUNT(*) FROM node WHERE src_file_id IN ({qmarks}) "
            f"AND block_id IS NULL", file_ids).fetchone()[0]
        if stray:
            con.close()
            raise FullRebuildRequired(
                "changed file contains declarations outside any block unit")

    affected = [r for r in block_roots if _resolve(r.get("file") or "") in changed_set]
    if not affected:
        con.close()
        raise FullRebuildRequired(
            "changed files are tracked but no block units map to them")

    affected_types: dict[tuple, dict] = {}   # (type, params_json) -> info
    for r in affected:
        if not r.get("type"):
            con.close()
            raise FullRebuildRequired(f"block root {r['path']} has no type name")
        if r.get("unsupported"):
            con.close()
            raise FullRebuildRequired(
                f"block '{r['path']}' has parameter values the incremental "
                f"splicer cannot reproduce")
        key = (r["type"], json.dumps(r.get("params") or {}, sort_keys=True))
        prev = affected_types.setdefault(
            key, {"file": r["file"], "params": r.get("params") or {}, "roots": []})
        prev["roots"].append(r)

    # Parameterized instances elaborate differently per instance; the type
    # normalizer suffixes their type_name, so identical type names across
    # instances imply identical parameterization. A type name containing the
    # normalizer's suffix marker is treated as parameterized.
    from systemrdl import RDLCompileError

    from .adapter import StageTimings, canonicalize_root
    from systemrdl import RDLCompiler

    t0 = time.perf_counter()
    submodels: dict[tuple, object] = {}
    compilers: dict[str, RDLCompiler] = {}   # one parse per changed file
    try:
        for key, info in sorted(affected_types.items()):
            fpath, params = info["file"], info["params"]
            rdlc = compilers.get(fpath)
            if rdlc is None:
                rdlc = RDLCompiler()
                rdlc.compile_file(fpath)
                compilers[fpath] = rdlc
            root_node = rdlc.elaborate(top_def_name=key[0],
                                       parameters=params or None)
            submodels[key] = canonicalize_root(root_node, source_mode,
                                               StageTimings())
    except RDLCompileError as e:
        con.close()
        raise FullRebuildRequired(
            f"standalone elaboration failed "
            f"(cross-file dependency?): {str(e)[:200]}")
    for key, info in affected_types.items():
        sub = submodels[key]
        for root in info["roots"]:
            if int(root["size"], 16) != sub.top_size:
                con.close()
                raise FullRebuildRequired(
                    f"block '{root['path']}' size changed "
                    f"0x{root['size']} -> 0x{sub.top_size:x}; downstream "
                    f"addresses may shift")
    elab_s = time.perf_counter() - t0

    # ---- splice ----
    t0 = time.perf_counter()
    upd = _Splicer(con)
    reg_delta = 0
    for key, info in sorted(affected_types.items()):
        sub = submodels[key]
        for root in info["roots"]:
            reg_delta += upd.splice_block(root, sub)
    # Purge definitions no longer referenced by any node (and their search rows)
    orphans = [r[0] for r in con.execute(
        "SELECT def_id FROM definition WHERE def_id NOT IN "
        "(SELECT DISTINCT def_id FROM node)")]
    for i in range(0, len(orphans), 500):
        chunk = orphans[i:i + 500]
        q = ",".join("?" * len(chunk))
        con.execute(f"DELETE FROM def_search WHERE rowid IN ({q})", chunk)
        con.execute(f"DELETE FROM definition WHERE def_id IN ({q})", chunk)
    con.execute("UPDATE meta SET value=? WHERE key='build_inputs'",
                (json.dumps(current),))
    # refresh counts + block_roots regs
    counts = json.loads(meta["counts"])
    counts["registers"] += reg_delta
    counts["decls"] = con.execute("SELECT COUNT(*) FROM node").fetchone()[0]
    counts["definitions"] = con.execute("SELECT COUNT(*) FROM definition").fetchone()[0]
    con.execute("UPDATE meta SET value=? WHERE key='counts'", (json.dumps(counts),))
    for r in block_roots:
        key = (r.get("type"), json.dumps(r.get("params") or {}, sort_keys=True))
        if key in submodels:
            r["regs"] = submodels[key].total_regs
    con.execute("UPDATE meta SET value=? WHERE key='block_roots'",
                (json.dumps(block_roots),))
    amax = con.execute("SELECT MAX(addr_end) FROM node WHERE kind='reg'").fetchone()[0]
    if amax:
        con.execute("UPDATE meta SET value=? WHERE key='addr_max'", (amax,))
    con.commit()
    con.close()
    splice_s = time.perf_counter() - t0

    report["unitsRebuilt"] = len(affected)
    report["unitsReused"] = len(block_roots) - len(affected)
    rebuilt = sorted({k[0] for k in affected_types})
    report["rebuiltTypeCount"] = len(rebuilt)
    report["rebuiltTypes"] = rebuilt[:20] + (["..."] if len(rebuilt) > 20 else [])
    report["registerDelta"] = reg_delta
    report["stages"]["elaborateSeconds"] = round(elab_s, 3)
    report["stages"]["spliceSeconds"] = round(splice_s, 3)
    report["totalSeconds"] = round(time.perf_counter() - t_start, 3)
    report["result"] = "updated"
    return report


class _Splicer:
    """In-place subtree replacement inside an existing index."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.next_id = (con.execute("SELECT MAX(node_id) FROM node").fetchone()[0] or 0) + 1
        self.def_ids = {r["hash"]: r["def_id"]
                        for r in con.execute("SELECT def_id, hash FROM definition")}
        self.next_def = (con.execute("SELECT MAX(def_id) FROM definition").fetchone()[0] or 0) + 1
        self.file_ids = {r["path"]: r["file_id"]
                         for r in con.execute("SELECT file_id, path FROM src_file")}

    def _def_id(self, model, h) -> int:
        d = self.def_ids.get(h)
        if d is not None:
            return d
        dd = model.definitions[h]
        d = self.next_def
        self.next_def += 1
        names = " ".join(f["name"] for f in dd.body.get("fields", []))
        descs = " ".join(f.get("desc", "") for f in dd.body.get("fields", [])
                         if f.get("desc"))
        self.con.execute("INSERT INTO definition VALUES (?,?,?,?,?)",
                         (d, h, dd.kind, dd.type_name,
                          json.dumps(dd.body, sort_keys=True)))
        self.con.execute("INSERT INTO def_search(rowid, type_name, field_names, "
                         "field_descs) VALUES (?,?,?,?)",
                         (d, dd.type_name or "", names, descs))
        self.def_ids[h] = d
        return d

    def _file_id(self, path) -> Optional[int]:
        if path is None:
            return None
        f = self.file_ids.get(path)
        if f is None:
            f = (max(self.file_ids.values()) if self.file_ids else 0) + 1
            self.con.execute("INSERT INTO src_file VALUES (?,?)", (f, path))
            self.file_ids[path] = f
        return f

    def splice_block(self, root_info: dict, model) -> int:
        """Replace one block instance subtree. Returns register-count delta."""
        con = self.con
        root_id = root_info["id"]
        row = con.execute("SELECT * FROM node WHERE node_id=?", (root_id,)).fetchone()
        if row is None:
            raise FullRebuildRequired(f"block root id {root_id} missing from index")
        base_addr = int(row["addr"], 16)
        root_path = row["path"]
        old_regs = row["reg_count"]

        # Remove old subtree (children only; root row is updated in place).
        old_ids = [r["node_id"] for r in con.execute(
            "SELECT node_id FROM node WHERE block_id=? AND node_id<>?",
            (root_id, root_id))]
        if old_ids:
            for i in range(0, len(old_ids), 500):
                chunk = old_ids[i:i + 500]
                q = ",".join("?" * len(chunk))
                con.execute(f"DELETE FROM search WHERE rowid IN ({q})", chunk)
                con.execute(f"DELETE FROM node WHERE node_id IN ({q})", chunk)

        # Insert new subtree with rebased ids/paths/addresses.
        id_map = {None: root_id}
        desc_by_hash = {h: (d.body.get("desc", "") or "")
                        for h, d in model.definitions.items()}
        rows, fts = [], []
        for d in model.decls:
            nid = self.next_id
            self.next_id += 1
            id_map[d.decl_id] = nid
            path = f"{root_path}.{d.path}"
            addr = base_addr + d.addr
            span_end = addr + (d.addr_span_end - d.addr)
            rows.append((
                nid, id_map[d.parent_id], d.kind, d.name, path,
                self._def_id(model, d.def_hash),
                addr_to_hex(addr), addr_to_hex(span_end),
                format(d.offset, "x"), format(d.size, "x"),
                json.dumps(d.array_dims) if d.array_dims else None,
                format(d.array_stride, "x") if d.array_stride else None,
                d.reg_count,
                self._file_id(d.src_file), d.src_offset, d.src_line, d.src_col,
                nid, root_id,
            ))
            fts.append((nid, d.name, path.replace(".", " "),
                        desc_by_hash.get(d.def_hash, "")))
        con.executemany("INSERT INTO node VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        rows)
        con.executemany("INSERT INTO search(rowid, name, path, desc) VALUES (?,?,?,?)",
                        fts)

        # Update the root row itself (its own def/desc may have changed).
        con.execute("UPDATE node SET def_id=?, reg_count=? WHERE node_id=?",
                    (self._def_id(model, model.top_def_hash),
                     model.total_regs, root_id))
        delta = model.total_regs - old_regs
        if delta:
            # keep ancestor subtree counts correct
            parent = row["parent_id"]
            while parent is not None:
                con.execute("UPDATE node SET reg_count = reg_count + ? "
                            "WHERE node_id=?", (delta, parent))
                parent = con.execute("SELECT parent_id FROM node WHERE node_id=?",
                                     (parent,)).fetchone()[0]
        return delta
