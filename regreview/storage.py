"""Indexed SQLite storage for canonical register models.

Layout (storage schema v1):

* ``meta``        — key/value: schema versions, counts, address range, timings.
                    Metadata never requires scanning entity tables.
* ``definition``  — deduplicated canonical content (JSON body per unique hash).
* ``node``        — one row per declared instance, arrays folded. Element
                    addresses are computed arithmetically (base + i*stride).
* ``src_file``    — interned source file paths.
* ``search``      — contentless FTS5 over node name/path/description.
* ``def_search``  — contentless FTS5 over definition field names/descriptions.

Addresses are stored as zero-padded 32-char hex TEXT so lexicographic order
is numeric order; Python ints (arbitrary precision) everywhere in memory.

Write path: single transaction, executemany batches, secondary indexes
created after bulk load (timed separately). No file-per-entity anywhere:
one .sqlite file per specification.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Optional

from . import CANONICAL_SCHEMA_VERSION, STORAGE_SCHEMA_VERSION, __version__
from .canonical import ADDR_HEX_WIDTH, Decl, addr_to_hex, hex_to_addr

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE definition (
    def_id    INTEGER PRIMARY KEY,
    hash      TEXT NOT NULL,
    kind      TEXT NOT NULL,
    type_name TEXT,
    body      TEXT NOT NULL
);
CREATE TABLE src_file (
    file_id INTEGER PRIMARY KEY,
    path    TEXT NOT NULL
);
CREATE TABLE node (
    node_id      INTEGER PRIMARY KEY,
    parent_id    INTEGER,
    kind         TEXT NOT NULL,
    name         TEXT NOT NULL,
    path         TEXT NOT NULL,
    def_id       INTEGER NOT NULL,
    addr         TEXT NOT NULL,
    addr_end     TEXT NOT NULL,
    offset       TEXT NOT NULL,
    size         TEXT NOT NULL,
    array_dims   TEXT,
    array_stride TEXT,
    reg_count    INTEGER NOT NULL,
    src_file_id  INTEGER,
    src_offset   INTEGER,
    src_line     INTEGER,
    src_col      INTEGER,
    sort_key     INTEGER NOT NULL,
    block_id     INTEGER
);
"""

_INDEXES = """
CREATE UNIQUE INDEX idx_node_path ON node(path);
CREATE INDEX idx_node_parent ON node(parent_id, sort_key);
CREATE INDEX idx_node_addr ON node(kind, addr);
CREATE INDEX idx_node_block ON node(block_id);
CREATE UNIQUE INDEX idx_def_hash ON definition(hash);
CREATE UNIQUE INDEX idx_src_path ON src_file(path);
"""

_FTS = """
CREATE VIRTUAL TABLE search USING fts5(name, path, desc, content='', contentless_delete=1);
CREATE VIRTUAL TABLE def_search USING fts5(type_name, field_names, field_descs, content='', contentless_delete=1);
"""

_ARRAY_SUFFIX = re.compile(r"^(.*?)((?:\[\d+\])+)$")


def _def_desc(body: dict) -> str:
    return body.get("desc", "") or ""


def _def_search_row(body: dict) -> tuple:
    fields = body.get("fields") or []
    names = " ".join(f["name"] for f in fields)
    descs = " ".join(f.get("desc", "") for f in fields if f.get("desc"))
    return names, descs


class IndexWriter:
    """Streams a canonical model into a new SQLite index."""

    BATCH = 10000

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        if self.db_path.exists():
            self.db_path.unlink()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.db_path))
        self.con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"
                               "PRAGMA temp_store=MEMORY; PRAGMA cache_size=-262144;")
        self.con.executescript(_SCHEMA)
        self.con.executescript(_FTS)
        self.timings: dict[str, float] = {}
        self._rows_written = 0

    def write_model(self, model, build_inputs: Optional[dict] = None,
                    expand_arrays: bool = False) -> dict:
        """Write the whole canonical model. Returns build stats."""
        con = self.con
        t0 = time.perf_counter()

        # Definitions (only those actually referenced by a declared instance;
        # build_canonical also extracts the top component's own definition,
        # which no decl row references)
        referenced = {d.def_hash for d in model.decls}
        def_ids: dict[str, int] = {}
        def_rows = []
        def_fts = []
        items = [(h, d) for h, d in model.definitions.items() if h in referenced]
        for i, (h, d) in enumerate(items, start=1):
            def_ids[h] = i
            def_rows.append((i, h, d.kind, d.type_name, json.dumps(d.body, sort_keys=True)))
            names, descs = _def_search_row(d.body)
            def_fts.append((i, d.type_name or "", names, descs))
        con.executemany("INSERT INTO definition VALUES (?,?,?,?,?)", def_rows)
        con.executemany(
            "INSERT INTO def_search(rowid, type_name, field_names, field_descs) VALUES (?,?,?,?)",
            def_fts)

        # Source files
        files = {p: i for i, p in enumerate(model.src_files, start=1)}
        con.executemany("INSERT INTO src_file VALUES (?,?)",
                        [(i, p) for p, i in files.items()])

        # Nodes (+ per-node FTS)
        desc_by_hash = {h: _def_desc(d.body) for h, d in model.definitions.items()}
        batch, fts_batch = [], []
        n_nodes = 0
        addr_min, addr_max = None, 0
        total_regs = 0
        block_roots = []
        for d in model.decls:
            if d.block_id == d.decl_id:
                entry = {
                    "id": d.decl_id, "path": d.path, "type": d.type_name,
                    "file": d.def_file, "addr": addr_to_hex(d.addr),
                    "size": format(d.size, "x"), "regs": d.reg_count,
                }
                if d.params:
                    entry["params"] = d.params
                if not d.params_supported:
                    entry["unsupported"] = True
                block_roots.append(entry)
            row, fts = self._node_row(d, def_ids, files, desc_by_hash)
            batch.append(row)
            fts_batch.append(fts)
            n_nodes += 1
            if d.kind == "reg":
                total_regs += d.reg_count
                if addr_min is None or d.addr < addr_min:
                    addr_min = d.addr
                addr_max = max(addr_max, d.addr_span_end)
            if len(batch) >= self.BATCH:
                self._flush(batch, fts_batch)
                batch, fts_batch = [], []
        self._flush(batch, fts_batch)
        self.timings["writeRowsSeconds"] = time.perf_counter() - t0

        # Secondary indexes (deferred, timed separately)
        t0 = time.perf_counter()
        con.executescript(_INDEXES)
        self.timings["createIndexSeconds"] = time.perf_counter() - t0

        # Metadata
        meta = {
            "storage_schema_version": str(STORAGE_SCHEMA_VERSION),
            "canonical_schema_version": str(CANONICAL_SCHEMA_VERSION),
            "regreview_version": __version__,
            "top_name": model.top_name,
            "source_mode": model.source_mode,
            "counts": json.dumps({
                "registers": total_regs,
                "decls": n_nodes,
                "definitions": len(def_rows),
                "sourceFiles": len(files),
            }),
            "addr_min": addr_to_hex(addr_min or 0),
            "addr_max": addr_to_hex(addr_max),
            "tool_versions": json.dumps(model.tool_versions),
            "build_timings": json.dumps({**model.timings.to_dict(),
                                         **{k: round(v, 3) for k, v in self.timings.items()}}),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "build_inputs": json.dumps(build_inputs or {}),
            "block_roots": json.dumps(block_roots),
            "top_src_file": getattr(model, "top_src_file", None) or "",
        }
        con.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", meta.items())
        con.execute("PRAGMA optimize")
        con.commit()
        con.execute("VACUUM") if False else None
        con.close()
        return {"nodes": n_nodes, "definitions": len(def_rows),
                "registers": total_regs, **{k: round(v, 3) for k, v in self.timings.items()}}

    def _node_row(self, d: Decl, def_ids, files, desc_by_hash) -> tuple:
        dims = json.dumps(d.array_dims) if d.array_dims else None
        stride = format(d.array_stride, "x") if d.array_stride else None
        block_id = d.block_id
        row = (
            d.decl_id, d.parent_id, d.kind, d.name, d.path, def_ids[d.def_hash],
            addr_to_hex(d.addr), addr_to_hex(d.addr_span_end),
            format(d.offset, "x"), format(d.size, "x"),
            dims, stride, d.reg_count,
            files.get(d.src_file) if d.src_file else None,
            d.src_offset, d.src_line, d.src_col,
            d.sort_key, block_id,
        )
        fts = (d.decl_id, d.name, d.path.replace(".", " "),
               desc_by_hash.get(d.def_hash, ""))
        return row, fts

    def _flush(self, batch, fts_batch):
        if not batch:
            return
        self.con.executemany(
            "INSERT INTO node VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        self.con.executemany(
            "INSERT INTO search(rowid, name, path, desc) VALUES (?,?,?,?)", fts_batch)
        self._rows_written += len(batch)


# ----------------------------------------------------------------------------
# Read side
# ----------------------------------------------------------------------------

class PathResolveError(KeyError):
    pass


class RegIndex:
    """Read-only query interface over a RegReview index."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        if not self.db_path.is_file():
            raise FileNotFoundError(db_path)
        uri = f"file:{self.db_path}?mode=ro"
        self.con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        row = self.con.execute(
            "SELECT value FROM meta WHERE key='storage_schema_version'").fetchone()
        if row is None or int(row[0]) != STORAGE_SCHEMA_VERSION:
            found = row[0] if row else "missing"
            raise RuntimeError(
                f"unsupported storage schema version {found} "
                f"(this build of regreview supports {STORAGE_SCHEMA_VERSION})")

    # ---- metadata ----

    def metadata(self) -> dict:
        meta = {k: v for k, v in self.con.execute("SELECT key, value FROM meta")}
        for k in ("counts", "tool_versions", "build_timings"):
            if k in meta:
                meta[k] = json.loads(meta[k])
        meta["db_bytes"] = self.db_path.stat().st_size
        return meta

    # ---- entity access ----

    def node_by_id(self, node_id: int) -> Optional[dict]:
        row = self.con.execute("SELECT * FROM node WHERE node_id=?", (node_id,)).fetchone()
        return self._node_dict(row) if row else None

    def node_by_path(self, path: str) -> Optional[dict]:
        """Resolve a path that may contain array element suffixes.

        ``grp_0.blk[2].arr0_ctrl[5]`` resolves against folded decl rows;
        element addresses are computed from strides.
        """
        # Fast path: exact folded path
        row = self.con.execute("SELECT * FROM node WHERE path=?", (path,)).fetchone()
        if row:
            return self._node_dict(row)
        # Parse array indices segment by segment
        segments = path.split(".")
        base_parts, extra = [], 0
        indices: list[tuple[int, list[int]]] = []  # (segment position, [idx,...])
        for i, seg in enumerate(segments):
            m = _ARRAY_SUFFIX.match(seg)
            if m:
                base_parts.append(m.group(1))
                idxs = [int(x) for x in re.findall(r"\[(\d+)\]", m.group(2))]
                indices.append((i, idxs))
            else:
                base_parts.append(seg)
        base_path = ".".join(base_parts)
        row = self.con.execute("SELECT * FROM node WHERE path=?", (base_path,)).fetchone()
        if not row:
            return None
        node = self._node_dict(row)
        # Accumulate address offset from ancestor + own array indices
        addr = hex_to_addr(row["addr"])
        for pos, idxs in indices:
            anc_path = ".".join(base_parts[:pos + 1])
            anc = self.con.execute(
                "SELECT array_dims, array_stride FROM node WHERE path=?",
                (anc_path,)).fetchone()
            if not anc or not anc["array_dims"]:
                raise PathResolveError(f"{anc_path} is not an array")
            dims = json.loads(anc["array_dims"])
            if len(idxs) != len(dims):
                raise PathResolveError(f"{anc_path}: expected {len(dims)} indices")
            flat = 0
            for idx, dim in zip(idxs, dims):
                if idx >= dim:
                    raise PathResolveError(f"{anc_path}: index {idx} >= dimension {dim}")
                flat = flat * dim + idx
            stride = int(anc["array_stride"], 16) if anc["array_stride"] else 0
            addr += flat * stride
        node["resolved_path"] = path
        node["addr"] = format(addr, "x")
        node["addr_int"] = addr
        return node

    def register_detail(self, path: str) -> Optional[dict]:
        node = self.node_by_path(path)
        if not node:
            return None
        body = self.con.execute(
            "SELECT body, type_name FROM definition WHERE def_id=?",
            (node["def_id"],)).fetchone()
        node["definition"] = json.loads(body["body"])
        node["type_name"] = body["type_name"]
        return node

    # ---- hierarchy ----

    def children(self, parent_id: Optional[int], cursor: int = -1,
                 limit: int = 200) -> dict:
        limit = max(1, min(int(limit), 1000))
        if parent_id is None:
            q = ("SELECT * FROM node WHERE parent_id IS NULL AND sort_key > ? "
                 "ORDER BY sort_key LIMIT ?")
            rows = self.con.execute(q, (cursor, limit + 1)).fetchall()
        else:
            q = ("SELECT * FROM node WHERE parent_id = ? AND sort_key > ? "
                 "ORDER BY sort_key LIMIT ?")
            rows = self.con.execute(q, (parent_id, cursor, limit + 1)).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {
            "items": [self._node_dict(r) for r in rows],
            "nextCursor": rows[-1]["sort_key"] if has_more and rows else None,
        }

    # ---- search ----

    def search(self, query: str, cursor: int = 0, limit: int = 50) -> dict:
        limit = max(1, min(int(limit), 500))
        try:
            fts_q = _sanitize_fts(query)
        except ValueError:
            return {"items": [], "nextCursor": None}
        rows = self.con.execute(
            "SELECT rowid FROM search WHERE search MATCH ? "
            "ORDER BY rank LIMIT ? OFFSET ?",
            (fts_q, limit + 1, cursor)).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for r in rows:
            n = self.node_by_id(r["rowid"])
            if n:
                n["match"] = "node"
                items.append(n)
        # Also surface definition-level (field name/desc) hits
        if cursor == 0 and len(items) < limit:
            def_rows = self.con.execute(
                "SELECT rowid FROM def_search WHERE def_search MATCH ? "
                "ORDER BY rank LIMIT 20", (fts_q,)).fetchall()
            for dr in def_rows:
                for nr in self.con.execute(
                        "SELECT * FROM node WHERE def_id=? LIMIT 3", (dr["rowid"],)):
                    n = self._node_dict(nr)
                    n["match"] = "field"
                    items.append(n)
                    if len(items) >= limit:
                        break
                if len(items) >= limit:
                    break
        return {"items": items,
                "nextCursor": cursor + limit if has_more else None}

    # ---- address ranges ----

    def address_range(self, start: int, end: int, cursor: Optional[str] = None,
                      limit: int = 200) -> dict:
        """Registers whose (arrayed) footprint intersects [start, end]."""
        limit = max(1, min(int(limit), 1000))
        start_h, end_h = addr_to_hex(start), addr_to_hex(end)
        cur = cursor or ""
        rows = self.con.execute(
            "SELECT * FROM node WHERE kind='reg' AND addr <= ? AND addr_end >= ? "
            "AND addr > ? ORDER BY addr LIMIT ?",
            (end_h, start_h, cur, limit + 1)).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for r in rows:
            n = self._node_dict(r)
            if r["array_dims"]:
                # Which elements fall inside the window?
                base = hex_to_addr(r["addr"])
                stride = int(r["array_stride"], 16)
                total = 1
                for d in json.loads(r["array_dims"]):
                    total *= d
                first = max(0, (start - base + stride - 1) // stride if start > base else 0)
                last = min(total - 1, (end - base) // stride)
                n["element_range"] = [int(first), int(last)]
            items.append(n)
        return {"items": items,
                "nextCursor": rows[-1]["addr"] if has_more and rows else None}

    # ---- diagnostics ----

    def explain(self, sql: str, params: tuple = ()) -> list:
        return [tuple(r) for r in self.con.execute("EXPLAIN QUERY PLAN " + sql, params)]

    def _node_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["addr"] = d["addr"].lstrip("0") or "0"
        d["addr_end"] = d["addr_end"].lstrip("0") or "0"
        if d.get("src_file_id"):
            f = self.con.execute("SELECT path FROM src_file WHERE file_id=?",
                                 (d["src_file_id"],)).fetchone()
            d["src_file"] = f["path"] if f else None
        if d.get("array_dims"):
            d["array_dims"] = json.loads(d["array_dims"])
        return d

    def close(self):
        self.con.close()


def _sanitize_fts(query: str) -> str:
    """Convert raw user input into a safe FTS5 prefix query."""
    tokens = re.findall(r"[A-Za-z0-9_]+", query)[:8]
    if not tokens:
        raise ValueError("no searchable tokens")
    return " ".join(f'"{t}"*' for t in tokens)
