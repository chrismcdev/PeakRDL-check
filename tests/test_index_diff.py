"""Index-based diffing must be equivalent to source-based diffing.

The GitHub Action diffs prebuilt indexes (cached base + incrementally
spliced head) instead of recompiling both revisions; these tests pin the
round-trip: model -> index -> model_from_index -> diff.
"""

import json

import pytest

from peakrdl_check.diff import diff_models
from peakrdl_check.storage import IndexWriter, model_from_index

BASE = """
addrmap soc {
    reg {
        desc = "Control register.";
        field { sw = rw; hw = r; reset = 0x0; } en[0:0];
        field { sw = rw; hw = r; reset = 0x3; } baud[3:1];
    } ctrl @ 0x0;
    reg { field { sw = r; hw = w; } busy[0:0]; } status @ 0x4;
    regfile {
        reg { field { sw = rw; hw = r; } d[7:0]; } data @ 0x0;
    } rf @ 0x100;
    reg { field { sw = rw; hw = r; } v[31:0]; } arr[8] @ 0x200 += 0x4;
};
"""

HEAD = """
addrmap soc {
    reg {
        desc = "Control register, revised.";
        field { sw = r; hw = r; reset = 0x1; } en[0:0];
        field { sw = rw; hw = r; reset = 0x3; } baud[3:1];
    } ctrl @ 0x40;
    reg {
        field { sw = r; hw = w; } busy[0:0];
        field { sw = r; hw = w; } overflow[1:1];
    } status @ 0x4;
    regfile {
        reg { field { sw = rw; hw = r; } d[7:0]; } data @ 0x0;
    } rf @ 0x100;
    reg { field { sw = rw; hw = r; } v[31:0]; } arr[16] @ 0x200 += 0x4;
};
"""


def _index_model(model, tmp_path, name):
    db = tmp_path / f"{name}.sqlite"
    IndexWriter(db).write_model(model)
    return model_from_index(db)


@pytest.fixture()
def source_models(compile_model):
    base = compile_model(BASE, name="base.rdl", source_mode="all")
    head = compile_model(HEAD, name="head.rdl", source_mode="all")
    return base, head


def test_index_diff_equals_source_diff(source_models, tmp_path):
    base, head = source_models
    src_result = diff_models(base, head)
    idx_result = diff_models(_index_model(base, tmp_path, "base"),
                             _index_model(head, tmp_path, "head"))
    assert json.dumps(idx_result, sort_keys=True) == \
        json.dumps(src_result, sort_keys=True)


def test_index_diff_detects_expected_rules(source_models, tmp_path):
    base, head = source_models
    result = diff_models(_index_model(base, tmp_path, "base"),
                         _index_model(head, tmp_path, "head"))
    rules = {c["ruleId"] for c in result["changes"]}
    assert {"REG-ADDRESS-CHANGED", "ACCESS-RW-TO-RO", "RESET-VALUE-CHANGED",
            "FIELD-ADDED-UNUSED-BITS", "ARRAY-DIMS-CHANGED",
            "DESC-CHANGED"} <= rules


def test_index_roundtrip_preserves_decl_content(compile_model, tmp_path):
    model = compile_model(BASE, name="base.rdl", source_mode="all")
    loaded = _index_model(model, tmp_path, "roundtrip")
    assert loaded.top_name == model.top_name
    by_path = {d.path: d for d in model.decls}
    loaded_by_path = {d.path: d for d in loaded.decls}
    assert set(by_path) == set(loaded_by_path)
    for path, d in by_path.items():
        l = loaded_by_path[path]
        assert (d.kind, d.addr, d.offset, d.size, d.array_dims, d.array_stride,
                d.reg_count, d.def_hash, d.is_alias, d.src_file, d.src_line) == \
               (l.kind, l.addr, l.offset, l.size, l.array_dims, l.array_stride,
                l.reg_count, l.def_hash, l.is_alias, l.src_file, l.src_line)


def test_cli_diff_accepts_index_paths(compile_model, tmp_path, capsys):
    from peakrdl_check.cli import main as cli_main

    base = compile_model(BASE, name="base.rdl", source_mode="all")
    head = compile_model(HEAD, name="head.rdl", source_mode="all")
    base_dir = tmp_path / "base-idx"
    head_dir = tmp_path / "head-idx"
    IndexWriter(base_dir / "register-map.sqlite").write_model(base)
    IndexWriter(head_dir / "register-map.sqlite").write_model(head)

    out = tmp_path / "changes.json"
    rc = cli_main(["diff", "--base", str(base_dir), "--head", str(head_dir),
                   "--format", "json", "--output", str(out)])
    result = json.loads(out.read_text())
    assert result["summary"].get("breaking")
    assert rc == 0
