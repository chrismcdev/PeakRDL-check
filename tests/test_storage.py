import json
import sqlite3

import pytest

from regreview.storage import IndexWriter, RegIndex

SPEC = """
addrmap soc {
    addrmap {
        reg { field { sw = rw; hw = r; reset = 0x0; } en[0:0]; } ctrl @ 0x0;
        reg { field { sw = r; hw = w; } busy[0:0]; } status @ 0x4;
        reg { field { sw = rw; hw = r; reset = 0x0; } d[7:0]; } ch[16] @ 0x100 += 0x10;
    } uart @ 0x0;
    addrmap {
        reg { field { sw = rw; hw = r; reset = 0x1; } cfg_watermark[3:0]; } wm @ 0x0;
    } dma @ 0x10000;
};
"""


@pytest.fixture()
def index(tmp_path, compile_model):
    model = compile_model(SPEC)
    db = tmp_path / "idx.sqlite"
    IndexWriter(db).write_model(model)
    return RegIndex(db)


def test_metadata_no_table_scan(index):
    meta = index.metadata()
    assert meta["counts"]["registers"] == 19  # 2 + 16 + 1
    plan = index.explain("SELECT value FROM meta WHERE key='counts'")
    assert not any("SCAN node" in str(p) for p in plan)


def test_children_pagination(index):
    roots = index.children(None, limit=1)
    assert len(roots["items"]) == 1
    assert roots["nextCursor"] is not None
    page2 = index.children(None, cursor=roots["nextCursor"], limit=10)
    names = [n["name"] for n in page2["items"]]
    assert "dma" in names
    assert page2["nextCursor"] is None


def test_children_query_uses_index(index):
    plan = index.explain(
        "SELECT * FROM node WHERE parent_id=? AND sort_key>? "
        "ORDER BY sort_key LIMIT 10", (1, -1))
    assert any("idx_node_parent" in str(p) for p in plan)


def test_exact_path_lookup(index):
    n = index.node_by_path("uart.ctrl")
    assert n and n["kind"] == "reg" and n["addr"] == "0"
    assert index.node_by_path("uart.nonexistent") is None


def test_array_element_resolution(index):
    n = index.node_by_path("uart.ch[3]")
    assert n is not None
    assert n["addr_int"] == 0x100 + 3 * 0x10
    from regreview.storage import PathResolveError
    with pytest.raises(PathResolveError):
        index.node_by_path("uart.ch[16]")  # out of range
    with pytest.raises(PathResolveError):
        index.node_by_path("uart.ctrl[0]")  # not an array


def test_register_detail_includes_fields(index):
    d = index.register_detail("dma.wm")
    fields = d["definition"]["fields"]
    assert fields[0]["name"] == "cfg_watermark"
    assert fields[0]["reset"] == "1"


def test_search_name_and_field(index):
    hits = index.search("watermark")
    assert any(h["path"] == "dma.wm" for h in hits["items"])


def test_search_injection_is_safe(index):
    # FTS syntax and SQL metacharacters must not raise or leak
    for q in ('"; DROP TABLE node; --', "a* OR b", "NEAR(", "()", "🙂"):
        res = index.search(q)
        assert isinstance(res["items"], list)


def test_address_range(index):
    res = index.address_range(0x100, 0x11F)
    paths = [i["path"] for i in res["items"]]
    assert paths == ["uart.ch"]
    assert res["items"][0]["element_range"] == [0, 1]


def test_address_range_uses_index(index):
    plan = index.explain(
        "SELECT * FROM node WHERE kind='reg' AND addr <= ? AND addr_end >= ? "
        "AND addr > ? ORDER BY addr LIMIT 10", ("f" * 32, "0" * 32, ""))
    assert any("idx_node_addr" in str(p) for p in plan)


def test_schema_version_rejected(tmp_path, compile_model):
    model = compile_model(SPEC)
    db = tmp_path / "idx2.sqlite"
    IndexWriter(db).write_model(model)
    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value='99' WHERE key='storage_schema_version'")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="unsupported storage schema"):
        RegIndex(db)


def test_corrupt_db_rejected(tmp_path):
    db = tmp_path / "corrupt.sqlite"
    db.write_bytes(b"this is not a sqlite file at all" * 100)
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        RegIndex(db)


def test_query_limits_clamped(index):
    res = index.children(None, limit=999999)
    assert len(res["items"]) <= 1000
    res = index.search("d", limit=99999)
    assert len(res["items"]) <= 500
