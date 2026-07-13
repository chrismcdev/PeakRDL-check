"""`peakrdl check` subcommand (PeakRDL CLI plugin integration)."""

import json
import subprocess
import sys

PEAKRDL = [sys.executable, "-m", "peakrdl"]

BASE = """
addrmap soc {
    reg { desc = "Control."; field { sw = rw; hw = r; reset = 0x0; } en[0:0]; } ctrl @ 0x0;
    reg { field { sw = r; hw = w; } busy[0:0]; } status @ 0x4;
};
"""


def run(*args):
    return subprocess.run([*PEAKRDL, "check", *args],
                          capture_output=True, text=True)


def test_subcommand_registered():
    p = subprocess.run([*PEAKRDL, "--help"], capture_output=True, text=True)
    assert "check" in p.stdout
    assert "Semantic compatibility check" in p.stdout


def test_breaking_fails_and_docs_passes(tmp_path):
    base = tmp_path / "base.rdl"
    base.write_text(BASE)
    breaking = tmp_path / "brk.rdl"
    breaking.write_text(BASE.replace("@ 0x4", "@ 0x40"))
    docs = tmp_path / "docs.rdl"
    docs.write_text(BASE.replace("Control.", "Primary control."))

    p = run(str(breaking), "--base", str(base))
    assert p.returncode == 1
    assert "REG-ADDRESS-CHANGED" in p.stdout

    p = run(str(docs), "--base", str(base))
    assert p.returncode == 0
    assert "DESC-CHANGED" in p.stdout


def test_report_file_and_sarif(tmp_path):
    base = tmp_path / "base.rdl"
    base.write_text(BASE)
    breaking = tmp_path / "brk.rdl"
    breaking.write_text(BASE.replace("@ 0x4", "@ 0x40"))
    out = tmp_path / "report.sarif"
    p = run(str(breaking), "--base", str(base),
            "--format", "sarif", "-o", str(out), "--fail-on", "none")
    assert p.returncode == 0
    sarif = json.loads(out.read_text())
    assert sarif["runs"][0]["results"][0]["ruleId"] == "REG-ADDRESS-CHANGED"


def test_broken_base_gates(tmp_path):
    base = tmp_path / "broken.rdl"
    base.write_text("addrmap bad {")
    head = tmp_path / "head.rdl"
    head.write_text(BASE)
    p = run(str(head), "--base", str(base))
    assert p.returncode == 1
    assert "SPEC-COMPILE-FAILED" in p.stdout
