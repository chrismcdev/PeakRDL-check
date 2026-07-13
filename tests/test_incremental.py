import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

TYPES = """
addrmap blk_a {
    reg { field { sw = rw; hw = r; reset = 0x1; } v[3:0]; } r0 @ 0x0;
    reg { field { sw = rw; hw = r; reset = 0x2; } v[3:0]; } r1 @ 0x4;
};
addrmap blk_b {
    reg { field { sw = r; hw = w; } s[7:0]; } st @ 0x0;
};
"""

TOP = """
`include "types.rdl"
addrmap incr_top {
    blk_a a0 @ 0x0000;
    blk_a a1 @ 0x1000;
    blk_b b0 @ 0x2000;
};
"""


def build(tmp_path, out, incremental=False):
    from peakrdl_check.cli import main
    args = ["build", str(tmp_path / "top.rdl"), "--top", "incr_top",
            "--output", str(out)]
    if incremental:
        args.append("--incremental")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(args)
    assert rc == 0
    return json.loads(buf.getvalue())


@pytest.fixture()
def project(tmp_path):
    (tmp_path / "types.rdl").write_text(TYPES)
    (tmp_path / "top.rdl").write_text(TOP)
    return tmp_path


def dump(db):
    sys.path.insert(0, str(ROOT / "scripts"))
    from verify_incremental_equivalence import canonical_dump
    return canonical_dump(str(db))


def test_no_change_is_all_hits(project, tmp_path):
    out = tmp_path / "out"
    build(project, out)
    rep = build(project, out, incremental=True)
    assert rep["result"] == "up-to-date"
    assert rep["unitsRebuilt"] == 0
    assert rep["unitsReused"] == 3


def test_block_edit_splices_and_matches_clean(project, tmp_path):
    out = tmp_path / "out"
    build(project, out)
    (project / "types.rdl").write_text(TYPES.replace("reset = 0x2", "reset = 0x3"))
    rep = build(project, out, incremental=True)
    assert rep["result"] == "updated"
    # invalidation granularity is the defining FILE: blk_b lives in the same
    # types.rdl, so all 3 units rebuild here (see the two-file test below for
    # selective reuse)
    assert rep["unitsRebuilt"] == 3
    assert rep["unitsReused"] == 0
    clean = tmp_path / "clean"
    build(project, clean)
    da = dump(out / "register-map.sqlite")
    db_ = dump(clean / "register-map.sqlite")
    assert da["nodes"] == db_["nodes"]
    assert json.loads(da["meta"]["counts"]) == json.loads(db_["meta"]["counts"])


def test_selective_reuse_across_files(tmp_path):
    (tmp_path / "a.rdl").write_text(
        "addrmap blk_a { reg { field { sw = rw; hw = r; reset = 0x1; } v[3:0]; }"
        " r0 @ 0x0; };\n")
    (tmp_path / "b.rdl").write_text(
        "addrmap blk_b { reg { field { sw = r; hw = w; } s[7:0]; } st @ 0x0; };\n")
    (tmp_path / "top.rdl").write_text(
        '`include "a.rdl"\n`include "b.rdl"\n'
        "addrmap incr_top { blk_a a0 @ 0x0; blk_a a1 @ 0x100; blk_b b0 @ 0x200; };\n")
    out = tmp_path / "out"
    build(tmp_path, out)
    (tmp_path / "a.rdl").write_text(
        (tmp_path / "a.rdl").read_text().replace("reset = 0x1", "reset = 0x7"))
    rep = build(tmp_path, out, incremental=True)
    assert rep["result"] == "updated"
    assert rep["unitsRebuilt"] == 2      # a0, a1
    assert rep["unitsReused"] == 1       # b0 reused: different file untouched
    clean = tmp_path / "clean"
    build(tmp_path, clean)
    assert dump(out / "register-map.sqlite")["nodes"] == \
        dump(clean / "register-map.sqlite")["nodes"]


def test_register_removed_updates_counts(tmp_path):
    """Removing a MIDDLE register keeps the block's byte size constant, so the
    splice path (not the size-change fallback) must handle a register-count
    change and keep ancestor counts correct."""
    types = ("addrmap blk_c {\n"
             "    reg { field { sw = rw; hw = r; } a[0:0]; } head @ 0x0;\n"
             "    reg { field { sw = rw; hw = r; } b[0:0]; } middle @ 0x4;\n"
             "    reg { field { sw = rw; hw = r; } c[0:0]; } tail @ 0x8;\n"
             "};\n")
    (tmp_path / "types.rdl").write_text(types)
    (tmp_path / "top.rdl").write_text(
        '`include "types.rdl"\naddrmap incr_top { blk_c c0 @ 0x0; };\n')
    out = tmp_path / "out"
    build(tmp_path, out)
    (tmp_path / "types.rdl").write_text(
        "\n".join(l for l in types.splitlines() if "middle" not in l) + "\n")
    rep = build(tmp_path, out, incremental=True)
    assert rep["result"] == "updated"
    assert rep["registerDelta"] == -1
    clean = tmp_path / "clean"
    build(tmp_path, clean)
    assert dump(out / "register-map.sqlite")["nodes"] == \
        dump(clean / "register-map.sqlite")["nodes"]
    assert json.loads(dump(out / "register-map.sqlite")["meta"]["counts"]) == \
        json.loads(dump(clean / "register-map.sqlite")["meta"]["counts"])


def test_top_change_forces_full_rebuild(project, tmp_path, capsys):
    out = tmp_path / "out"
    build(project, out)
    (project / "top.rdl").write_text(TOP.replace("@ 0x2000", "@ 0x3000"))
    from peakrdl_check.incremental import FullRebuildRequired, incremental_build
    with pytest.raises(FullRebuildRequired, match="top-level file"):
        incremental_build([project / "top.rdl"], out, "incr_top", "registers")


def test_size_change_forces_full_rebuild(project, tmp_path):
    out = tmp_path / "out"
    build(project, out)
    bigger = TYPES.replace(
        "reg { field { sw = r; hw = w; } s[7:0]; } st @ 0x0;",
        "reg { field { sw = r; hw = w; } s[7:0]; } st @ 0x40;")
    (project / "types.rdl").write_text(bigger)
    from peakrdl_check.incremental import FullRebuildRequired, incremental_build
    with pytest.raises(FullRebuildRequired, match="size changed"):
        incremental_build([project / "top.rdl"], out, "incr_top", "registers")


def test_search_consistent_after_splice(project, tmp_path):
    out = tmp_path / "out"
    build(project, out)
    renamed = TYPES.replace("} r1 @ 0x4;", "} renamed_unique_xyz @ 0x4;")
    (project / "types.rdl").write_text(renamed)
    build(project, out, incremental=True)
    from peakrdl_check.storage import RegIndex
    idx = RegIndex(out / "register-map.sqlite")
    hits = idx.search("renamed_unique_xyz")
    assert {h["path"] for h in hits["items"]} == {"a0.renamed_unique_xyz",
                                                  "a1.renamed_unique_xyz"}
    assert not idx.search("r1")["items"] or all(
        "r1" != h["name"] for h in idx.search("r1")["items"])
