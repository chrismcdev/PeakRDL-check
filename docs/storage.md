# SQLite storage

`peakrdl_check/storage.py` implements storage schema v1: **one SQLite file per
specification** (`register-map.sqlite`), no file-per-entity anywhere.

## Schema

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE definition (
    def_id    INTEGER PRIMARY KEY,
    hash      TEXT NOT NULL,          -- sha256 content hash
    kind      TEXT NOT NULL,          -- addrmap | regfile | reg | mem
    type_name TEXT,
    body      TEXT NOT NULL           -- canonical JSON body
);

CREATE TABLE src_file (
    file_id INTEGER PRIMARY KEY,
    path    TEXT NOT NULL             -- interned source paths
);

CREATE TABLE node (                   -- one row per declared instance, arrays folded
    node_id      INTEGER PRIMARY KEY,
    parent_id    INTEGER,
    kind         TEXT NOT NULL,
    name         TEXT NOT NULL,
    path         TEXT NOT NULL,
    def_id       INTEGER NOT NULL,
    addr         TEXT NOT NULL,       -- zero-padded 32-hex: lexicographic == numeric
    addr_end     TEXT NOT NULL,       -- inclusive end of full arrayed footprint
    offset       TEXT NOT NULL,
    size         TEXT NOT NULL,
    array_dims   TEXT,                -- JSON list, NULL if scalar
    array_stride TEXT,
    reg_count    INTEGER NOT NULL,    -- unrolled registers in subtree
    src_file_id  INTEGER,
    src_offset   INTEGER,
    src_line     INTEGER,
    src_col      INTEGER,
    sort_key     INTEGER NOT NULL,
    block_id     INTEGER              -- incremental unit (block-root node_id)
);

-- FTS (contentless; deletable rows for the incremental splicer)
CREATE VIRTUAL TABLE search     USING fts5(name, path, desc, content='', contentless_delete=1);
CREATE VIRTUAL TABLE def_search USING fts5(type_name, field_names, field_descs, content='', contentless_delete=1);
```

Secondary indexes are created **after** bulk load and timed separately
(`createIndexSeconds` in the build report):

```sql
CREATE UNIQUE INDEX idx_node_path  ON node(path);
CREATE INDEX        idx_node_parent ON node(parent_id, sort_key);
CREATE INDEX        idx_node_addr   ON node(kind, addr);
CREATE INDEX        idx_node_block  ON node(block_id);
CREATE UNIQUE INDEX idx_def_hash    ON definition(hash);
CREATE UNIQUE INDEX idx_src_path    ON src_file(path);
```

`meta` holds schema versions, entity counts, address range, build timings, the
sha256 build-input manifest, and the block-root list — metadata queries never
scan entity tables.

## FTS5 details

Both search tables are **contentless** (`content=''`) — the indexed text is
not stored twice — with `contentless_delete=1` so the incremental splicer can
delete rows (requires SQLite ≥ 3.43; `peakrdl-check doctor` checks). `search`
covers node name/path/description; `def_search` covers definition-level field
names and descriptions, surfaced as `"match": "field"` results. User input is
sanitised into a safe prefix query (`_sanitize_fts`: tokenise, cap at 8 terms,
quote each) — FTS operators in user input cannot inject syntax
(`tests/test_security.py::test_search_operators_handled`).

## Write path

Single connection with `journal_mode=OFF`, `synchronous=OFF`,
`temp_store=MEMORY`, 256 MB page cache (safe: the writer always creates a fresh
file). Rows stream in `executemany` batches of 10,000. Only definitions
actually referenced by a decl row are written.

## Verified query plans

`RegIndex.explain()` wraps `EXPLAIN QUERY PLAN`, and `tests/test_storage.py`
**asserts** the plans:

| Query | Required plan |
|---|---|
| children page (`parent_id = ? AND sort_key > ? ORDER BY sort_key`) | uses `idx_node_parent` |
| address range (`kind='reg' AND addr <= ? AND addr_end >= ? AND addr > ?`) | uses `idx_node_addr` |
| metadata | never scans `node` |

## Dedup effect at scale

800k-register mixed fixture (`build/800k-build.json`):

| Metric | Value |
|---|---:|
| elaborated registers | 800,000 |
| node rows | 85,151 |
| definition rows | 67,483 |
| single-file size | 337 MB |

Compare peakrdl-html at 100k mixed: 10,603 files / 154 MB — an order of
magnitude fewer registers spread over four orders of magnitude more files.

## Array elements

Never rows. `node_by_path("grp_0.blk[2].arr0_ctrl[5]")` resolves the folded
base row, validates each index against the stored dimensions, and computes the
address as `base + flat_index * stride`. Out-of-range indices and non-array
subscripts raise `PathResolveError` (HTTP 400 at the API).

## Read side

`RegIndex` opens the file read-only (`mode=ro` URI) and refuses databases whose
`storage_schema_version` does not match `STORAGE_SCHEMA_VERSION` (currently 1).
All list queries are cursor-paginated with server-side clamps.
