import json

from peakrdl_check.policy import DEFAULT_POLICY, load_policy


BASE = """
addrmap soc {
    reg {
        field { sw = rw; hw = r; reset = 0x0; } en[0:0];
        field { sw = rw; hw = r; reset = 0x3; } mode[3:1];
    } ctrl @ 0x0;
    reg { field { sw = r; hw = w; } busy[0:0]; } status @ 0x4;
};
"""


def rules_of(result):
    return sorted(c["ruleId"] for c in result["changes"])


def test_no_changes_on_identical(diff_texts):
    r = diff_texts(BASE, BASE)
    assert r["changes"] == []
    assert r["totalChanges"] == 0


def test_deterministic_output(diff_texts):
    a = diff_texts(BASE, BASE.replace("@ 0x4", "@ 0x8"))
    b = diff_texts(BASE, BASE.replace("@ 0x4", "@ 0x8"))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_field_removed_and_added(diff_texts):
    after = BASE.replace(
        "field { sw = rw; hw = r; reset = 0x3; } mode[3:1];",
        "field { sw = rw; hw = r; reset = 0x0; } newbit[5:5];")
    r = diff_texts(BASE, after)
    assert "FIELD-REMOVED" in rules_of(r)
    assert "FIELD-ADDED-UNUSED-BITS" in rules_of(r)


def test_field_added_overlapping_bits(diff_texts):
    # 'mode' occupies [3:1] in base; new field lands on [2:2] after removing it
    after = BASE.replace(
        "field { sw = rw; hw = r; reset = 0x3; } mode[3:1];",
        "field { sw = rw; hw = r; reset = 0x0; } other[2:2];")
    r = diff_texts(BASE, after)
    assert "FIELD-ADDED-OVERLAPPING" in rules_of(r)


def test_access_transition_matrix():
    from peakrdl_check.diff import ModelDiffer
    rule = ModelDiffer._sw_access_rule
    assert rule("rw", "r") == "ACCESS-RW-TO-RO"
    assert rule("rw", "w") == "ACCESS-READABLE-TO-WO"
    assert rule("r", "w") == "ACCESS-READABLE-TO-WO"
    assert rule("r", "rw") == "ACCESS-WIDENED"
    assert rule("w", "rw") == "ACCESS-WIDENED"
    assert rule("w", "r") == "ACCESS-CHANGED-AMBIGUOUS"


def test_rename_detected_only_when_unique(diff_texts):
    # unique rename: content+offset identical
    after = BASE.replace("} status @ 0x4;", "} state @ 0x4;")
    r = diff_texts(BASE, after)
    assert rules_of(r) == ["REG-RENAMED"]
    assert r["changes"][0]["confidence"] == "likely"

    # rename + content edit at same offset: uncertain, remove+add preserved
    after2 = BASE.replace(
        "reg { field { sw = r; hw = w; } busy[0:0]; } status @ 0x4;",
        "reg { field { sw = r; hw = w; } done[0:0]; } state @ 0x4;")
    r2 = diff_texts(BASE, after2)
    assert "MATCH-UNCERTAIN" in rules_of(r2)
    assert "REG-REMOVED" in rules_of(r2)


def test_rename_disabled_flag(diff_texts):
    after = BASE.replace("} status @ 0x4;", "} state @ 0x4;")
    r = diff_texts(BASE, after, rename_detection=False)
    assert "REG-RENAMED" not in rules_of(r)
    assert "REG-REMOVED" in rules_of(r)


def test_container_move_collapses_propagation(diff_texts):
    base = """
addrmap soc {
    addrmap {
        reg { field { sw = rw; hw = r; } a[0:0]; } r0 @ 0x0;
        reg { field { sw = rw; hw = r; } a[0:0]; } r1 @ 0x4;
        reg { field { sw = rw; hw = r; } a[0:0]; } r2 @ 0x8;
    } blk @ 0x1000;
};
"""
    after = base.replace("} blk @ 0x1000;", "} blk @ 0x2000;")
    r = diff_texts(base, after)
    # exactly one BLOCK-MOVED, no per-register address spam
    assert rules_of(r) == ["BLOCK-MOVED"]
    assert r["changes"][0]["affectedRegisters"] == 3


def test_enum_semantics(diff_texts):
    base = """
enum m_e { OFF = 0; ON = 1; };
addrmap soc {
    reg { field { sw = rw; hw = r; encode = m_e; reset = 0; } m[1:0]; } c @ 0x0;
};
"""
    r = diff_texts(base, base.replace("ON = 1;", "ON = 1; AUTO = 2;"))
    assert rules_of(r) == ["ENUM-VALUE-ADDED"]
    r = diff_texts(base, base.replace("ON = 1;", "ON = 2;"))
    assert "ENUM-VALUE-CHANGED" in rules_of(r)
    r = diff_texts(base, base.replace("ON = 1;", "ENABLED = 1;"))
    assert rules_of(r) == ["ENUM-VALUE-RENAMED"]


def test_every_change_has_required_fields(diff_texts):
    after = BASE.replace("@ 0x4", "@ 0x8").replace("reset = 0x3", "reset = 0x1")
    r = diff_texts(BASE, after)
    assert r["changes"]
    for c in r["changes"]:
        assert c["ruleId"] and c["message"] and c["entityKey"]
        assert c["classification"] in ("breaking", "behavioural", "compatible",
                                       "documentation", "informational",
                                       "uncertain")
        assert c["policyVersion"]


def test_policy_override(tmp_path, diff_texts):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({"rules": {"RESET-VALUE-CHANGED": "breaking"}}))
    policy = load_policy(p)
    assert policy["RESET-VALUE-CHANGED"] == "breaking"
    assert DEFAULT_POLICY["RESET-VALUE-CHANGED"] == "behavioural"
    r = diff_texts(BASE, BASE.replace("reset = 0x3", "reset = 0x2"),
                   policy=policy)
    assert r["changes"][0]["classification"] == "breaking"


def test_source_locations_present(diff_texts):
    after = BASE.replace("@ 0x4", "@ 0x8")
    r = diff_texts(BASE, after)
    loc = r["changes"][0]["headLocation"]
    assert loc["file"].endswith("after.rdl")
