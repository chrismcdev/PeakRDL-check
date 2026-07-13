"""Specifications and descriptions are untrusted input."""

import http.client
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from regreview.server import make_server
from regreview.storage import IndexWriter, RegIndex

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
    js = (Path(__file__).parent.parent / "regreview" / "viewer" / "viewer.js").read_text()
    assert "innerHTML" not in js
    assert "outerHTML" not in js
    assert "document.write" not in js
    assert "insertAdjacentHTML" not in js
