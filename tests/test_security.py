"""Specifications and descriptions are untrusted input."""

import http.client
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from peakrdl_check.server import make_server
from peakrdl_check.storage import IndexWriter, RegIndex

HOSTILE_SPEC = r"""
addrmap soc {
    reg {
        desc = "<script>alert(1)</script><img src=x onerror=alert(2)>";
        field { sw = rw; hw = r;
                desc = "&lt;iframe&gt; ' \" ` ${curly} {{jinja}} </textarea>"; } en[0:0];
    } ctrl @ 0x0;
};
"""


@pytest.fixture()
def hostile_server(tmp_path, compile_model):
    model = compile_model(HOSTILE_SPEC)
    db = tmp_path / "idx.sqlite"
    IndexWriter(db).write_model(model)
    httpd, port, _ = make_server(db, port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port
    httpd.shutdown()


def get(port, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def test_api_is_json_only_never_html(hostile_server):
    status, headers, body = get(hostile_server, "/api/entities/ctrl")
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert headers.get("X-Content-Type-Options") == "nosniff"
    # payload is JSON-encoded; script text is data, not markup
    data = json.loads(body)
    assert "<script>" in data["definition"]["desc"]


def test_path_traversal_blocked(hostile_server):
    for path in ("/../../../etc/passwd", "/..%2f..%2f..%2fetc%2fpasswd",
                 "/assets/../../server.py", "/%2e%2e/%2e%2e/etc/passwd"):
        status, _, body = get(hostile_server, path)
        assert status == 404, path
        assert b"root:" not in body


def test_unknown_static_types_rejected(hostile_server):
    status, _, _ = get(hostile_server, "/viewer.py")
    assert status == 404


def test_url_length_limited(hostile_server):
    status, _, _ = get(hostile_server, "/api/search?q=" + "a" * 8000)
    assert status == 414


def test_query_limit_clamped(hostile_server):
    status, _, body = get(hostile_server,
                          "/api/children?parent=root&limit=99999999")
    assert status == 200
    assert len(json.loads(body)["items"]) <= 1000


def test_bad_address_range_rejected(hostile_server):
    for q in ("start=zz&end=0", "start=0&end=zz", "start=100&end=0",
              f"start=0&end={1 << 70}"):
        status, _, _ = get(hostile_server, f"/api/address-range?{q}")
        assert status == 400, q


def test_search_operators_handled(hostile_server):
    for q in ('%22quoted%22', "a%20OR%20b", "NEAR(", "%2A", "()%3B--"):
        status, _, _ = get(hostile_server, f"/api/search?q={q}")
        assert status == 200


def test_deep_hierarchy_and_long_descriptions(tmp_path, compile_model):
    # 24-deep nesting and a 100 KB description must not break build or query
    inner = 'reg { field { sw = rw; hw = r; desc = "%s"; } f[0:0]; } leaf @ 0x0;' % (
        "x" * 100_000)
    text = inner
    for i in range(24):
        text = "regfile { %s } rf%d;" % (text, i)
    spec = "addrmap soc { %s };" % text
    model = compile_model(spec)
    db = tmp_path / "deep.sqlite"
    IndexWriter(db).write_model(model)
    idx = RegIndex(db)
    path = ".".join(f"rf{i}" for i in range(23, -1, -1)) + ".leaf"
    node = idx.register_detail(path)
    assert node is not None
    assert len(node["definition"]["fields"][0]["desc"]) == 100_000


def test_server_binds_localhost_only(tmp_path, compile_model):
    model = compile_model(HOSTILE_SPEC)
    db = tmp_path / "idx.sqlite"
    IndexWriter(db).write_model(model)
    httpd, port, _ = make_server(db, port=0)
    assert httpd.server_address[0] == "127.0.0.1"
    httpd.server_close()


def test_viewer_never_uses_innerhtml():
    js = (Path(__file__).parent.parent / "peakrdl_check" / "viewer" / "viewer.js").read_text()
    assert "innerHTML" not in js
    assert "outerHTML" not in js
    assert "document.write" not in js
    assert "insertAdjacentHTML" not in js


def test_viewer_renders_bitfields_and_change_annotations_safely():
    root = Path(__file__).parent.parent / "peakrdl_check" / "viewer"
    js = (root / "viewer.js").read_text()
    html = (root / "index.html").read_text()

    assert "document.createElementNS" in js
    assert "function renderBitfield" in js
    assert "function segmentLabel" in js
    assert "function changesForRegister" in js
    assert "FIELD-ADDED" not in html  # report content remains data, never markup
    assert ".change-summary" in html
    assert ".bit-segment.removed" in html


def test_viewer_includes_bounded_review_and_address_views():
    root = Path(__file__).parent.parent / "peakrdl_check" / "viewer"
    js = (root / "viewer.js").read_text()
    html = (root / "index.html").read_text()

    assert 'id="tab-overview"' in html
    assert "function renderOverview" in js
    assert "function buildChangeImpactIndex" in js
    assert "function changeImpactForPath" in js
    assert "function renderAddressMap" in js
    assert "const ADDRESS_MAP_LIMIT = 200" in js
    assert "limit=${ADDRESS_MAP_LIMIT}" in js
    assert ".row .impact.descendant" in html


def test_empty_search_keeps_results_mode_active():
    js = (Path(__file__).parent.parent / "peakrdl_check" / "viewer" / "viewer.js").read_text()

    empty_search = js[js.index("async function runSearch"):js.index("async function runAddrFilter")]
    assert 'setMode("results")' in empty_search
    assert "Enter a search term" in empty_search
    assert 'if (!q) { switchMode("tree")' not in empty_search


def test_viewer_has_accessible_persistent_splitter():
    root = Path(__file__).parent.parent / "peakrdl_check" / "viewer"
    js = (root / "viewer.js").read_text()
    html = (root / "index.html").read_text()

    assert 'id="splitter" role="separator"' in html
    assert 'aria-orientation="vertical"' in html
    assert "function setLeftPanelWidth" in js
    assert "setPointerCapture" in js
    assert 'event.key === "ArrowLeft"' in js
    assert 'event.key === "ArrowRight"' in js
    assert "localStorage.setItem(PANEL_WIDTH_KEY" in js
    assert 'splitterEl.addEventListener("dblclick"' in js


def test_viewer_routes_restore_tabs_and_reveal_deep_links(hostile_server):
    js = (Path(__file__).parent.parent / "peakrdl_check" / "viewer" / "viewer.js").read_text()

    assert "function updateViewUrl" in js
    assert 'new URLSearchParams({ view: mode })' in js
    assert 'if (view === "changes")' in js
    assert 'if (view === "results")' in js
    assert "return await revealInHierarchy(path)" in js

    for route in ("/?view=changes", "/?view=results", "/r/ctrl"):
        status, headers, body = get(hostile_server, route)
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert b'id="tabs"' in body


def test_viewer_assets_use_absolute_paths_for_deep_link_refreshes():
    html = (Path(__file__).parent.parent / "peakrdl_check" / "viewer" / "index.html").read_text()
    assert 'src="/viewer.js"' in html
    assert 'src="viewer.js"' not in html
