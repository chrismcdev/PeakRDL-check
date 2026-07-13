import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGREVIEW = [str(ROOT / ".venv" / "bin" / "regreview")]

BASE = """
addrmap soc {
    reg { field { sw = rw; hw = r; reset = 0x0; } en[0:0]; } ctrl @ 0x0;
};
"""


def run(*args):
    return subprocess.run(REGREVIEW + list(args), capture_output=True, text=True)


def test_check_exit_codes(tmp_path):
    b = tmp_path / "b.rdl"
    b.write_text(BASE)
    same = tmp_path / "same.rdl"
    same.write_text(BASE)
    breaking = tmp_path / "brk.rdl"
    breaking.write_text(BASE.replace("@ 0x0", "@ 0x40"))
    behav = tmp_path / "bhv.rdl"
    behav.write_text(BASE.replace("reset = 0x0", "reset = 0x1"))

    assert run("check", "--base", str(b), "--head", str(same)).returncode == 0
    assert run("check", "--base", str(b), "--head", str(breaking)).returncode == 1
    assert run("check", "--base", str(b), "--head", str(behav)).returncode == 0
    assert run("check", "--base", str(b), "--head", str(behav),
               "--fail-on", "behavioural").returncode == 1


def test_check_invalid_input_exit_code(tmp_path):
    b = tmp_path / "b.rdl"
    b.write_text(BASE)
    bad = tmp_path / "bad.rdl"
    bad.write_text("addrmap soc { this is not rdl }")
    # head fails to compile -> SPEC-COMPILE-FAILED (breaking) -> exit 1
    assert run("check", "--base", str(b), "--head", str(bad)).returncode == 1


def test_diff_formats(tmp_path):
    b = tmp_path / "b.rdl"
    b.write_text(BASE)
    h = tmp_path / "h.rdl"
    h.write_text(BASE.replace("@ 0x0", "@ 0x40"))
    for fmt in ("text", "json", "markdown", "sarif"):
        p = run("diff", "--base", str(b), "--head", str(h), "--format", fmt)
        assert p.returncode == 0, p.stderr
        assert "REG-ADDRESS-CHANGED" in p.stdout
    sarif = json.loads(run("diff", "--base", str(b), "--head", str(h),
                           "--format", "sarif").stdout)
    assert sarif["runs"][0]["results"][0]["level"] == "error"


def test_diff_fail_on(tmp_path):
    b = tmp_path / "b.rdl"
    b.write_text(BASE)
    h = tmp_path / "h.rdl"
    h.write_text(BASE.replace("@ 0x0", "@ 0x40"))
    assert run("diff", "--base", str(b), "--head", str(h)).returncode == 0
    assert run("diff", "--base", str(b), "--head", str(h),
               "--fail-on", "breaking").returncode == 1


def test_build_and_inspect(tmp_path):
    b = tmp_path / "b.rdl"
    b.write_text(BASE)
    out = tmp_path / "out"
    p = run("build", str(b), "--output", str(out))
    assert p.returncode == 0, p.stderr
    report = json.loads(p.stdout)
    assert report["registers"] == 1
    assert (out / "register-map.sqlite").is_file()
    p = run("inspect", str(out))
    assert p.returncode == 0
    assert json.loads(p.stdout)["counts"]["registers"] == 1


def test_missing_index_exit_code(tmp_path):
    p = run("inspect", str(tmp_path / "nope"))
    assert p.returncode == 2
