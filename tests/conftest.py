import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def tmp_rdl(tmp_path):
    """Write RDL text to a temp file and return its path."""
    def _write(text: str, name: str = "test.rdl") -> Path:
        p = tmp_path / name
        p.write_text(text)
        return p
    return _write


@pytest.fixture()
def compile_model(tmp_rdl):
    from regreview.adapter import build_canonical

    def _compile(text: str, top=None, source_mode="registers", name="test.rdl"):
        return build_canonical([tmp_rdl(text, name)], top=top,
                               source_mode=source_mode)
    return _compile


@pytest.fixture()
def diff_texts(tmp_path):
    from regreview.adapter import build_canonical
    from regreview.diff import diff_models

    def _diff(before: str, after: str, **kw):
        b = tmp_path / "before.rdl"
        a = tmp_path / "after.rdl"
        b.write_text(before)
        a.write_text(after)
        return diff_models(build_canonical([b], source_mode="registers"),
                           build_canonical([a], source_mode="registers"), **kw)
    return _diff
