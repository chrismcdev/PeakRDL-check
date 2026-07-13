"""Local review server.

Localhost-only by default, offline, no accounts, no cloud. Serves the
paginated query API plus the bundled single-file viewer. Never serializes
the full hierarchy: every endpoint is paginated or single-entity.

Security posture: specifications are untrusted input. The API returns JSON
only (the viewer inserts all text via textContent, never innerHTML); static
serving is restricted to the packaged viewer directory with traversal checks;
query limits are clamped server-side; the server binds to 127.0.0.1 unless
explicitly overridden.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .storage import PathResolveError, RegIndex

_VIEWER_DIR = Path(__file__).parent / "viewer"
_MAX_URL = 4096

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "peakrdl-check"
    protocol_version = "HTTP/1.1"
    # Buffer the whole response and disable Nagle: header+body written as
    # separate segments otherwise interacts with delayed ACK and adds a flat
    # ~50 ms to every keep-alive request on macOS (measured in the viewer).
    wbufsize = 64 * 1024
    disable_nagle_algorithm = True

    # These are set by make_server()
    index: RegIndex = None
    changes_path: Path = None
    ready_at: float = 0.0

    def log_message(self, fmt, *args):  # quiet by default
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # ---- helpers ----

    def _json(self, obj, status=200, cache=False):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control",
                         "max-age=3600" if cache else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, status, msg):
        self._json({"error": msg}, status=status)

    # ---- routing ----

    def do_GET(self):
        try:
            if len(self.path) > _MAX_URL:
                return self._err(414, "URL too long")
            url = urlparse(self.path)
            q = parse_qs(url.query)
            route = url.path
            if route.startswith("/api/"):
                return self._api(route, q)
            return self._static(route)
        except BrokenPipeError:
            pass
        except Exception as e:  # never leak a traceback to the client
            try:
                self._err(500, f"internal error: {type(e).__name__}")
            except Exception:
                pass

    def _api(self, route, q):
        idx = self.index

        def qint(name, default, lo=0, hi=1_000_000):
            try:
                return max(lo, min(hi, int(q.get(name, [default])[0])))
            except (TypeError, ValueError):
                return default

        if route == "/api/health":
            return self._json({"status": "ok"})
        if route == "/api/ready":
            return self._json({"status": "ready", "readySeconds": round(self.ready_at, 3)})
        if route == "/api/metadata":
            return self._json(idx.metadata())
        if route == "/api/children":
            parent = q.get("parent", [None])[0]
            parent_id = int(parent) if parent not in (None, "", "root") else None
            return self._json(idx.children(parent_id,
                                           cursor=qint("cursor", -1, lo=-1),
                                           limit=qint("limit", 200, 1, 1000)))
        if route == "/api/search":
            term = q.get("q", [""])[0][:256]
            if not term:
                return self._err(400, "missing q")
            return self._json(idx.search(term, cursor=qint("cursor", 0),
                                         limit=qint("limit", 50, 1, 500)))
        if route == "/api/address-range":
            try:
                start = int(q.get("start", ["0"])[0], 0)
                end = int(q.get("end", ["0"])[0], 0)
            except ValueError:
                return self._err(400, "bad start/end")
            if end < start or end - start > (1 << 64):
                return self._err(400, "bad range")
            cursor = q.get("cursor", [None])[0]
            return self._json(idx.address_range(start, end, cursor=cursor,
                                                limit=qint("limit", 200, 1, 1000)))
        if route.startswith("/api/entities/"):
            key = unquote(route[len("/api/entities/"):])[:1024]
            if key.endswith("/children"):
                node = idx.node_by_path(key[:-len("/children")])
                if not node:
                    return self._err(404, "not found")
                return self._json(idx.children(node["node_id"],
                                               cursor=qint("cursor", -1, lo=-1),
                                               limit=qint("limit", 200, 1, 1000)))
            try:
                node = idx.register_detail(key)
            except PathResolveError as e:
                return self._err(400, str(e))
            if not node:
                return self._err(404, "not found")
            return self._json(node)
        if route == "/api/changes":
            if self.changes_path and self.changes_path.is_file():
                data = json.loads(self.changes_path.read_text())
                offset = qint("cursor", 0)
                limit = qint("limit", 200, 1, 1000)
                changes = data.get("changes", [])
                page = changes[offset:offset + limit]
                return self._json({
                    "summary": data.get("summary", {}),
                    "items": page,
                    "nextCursor": offset + limit if offset + limit < len(changes) else None,
                })
            return self._json({"summary": {}, "items": [], "nextCursor": None})
        return self._err(404, "unknown endpoint")

    def _static(self, route):
        if route in ("/", ""):
            route = "/index.html"
        # SPA deep-link fallback: /r/<path> serves the viewer shell.
        if route.startswith("/r/"):
            route = "/index.html"
        rel = route.lstrip("/")
        target = (_VIEWER_DIR / rel).resolve()
        if not str(target).startswith(str(_VIEWER_DIR.resolve())) or not target.is_file():
            return self._err(404, "not found")
        ctype = _STATIC_TYPES.get(target.suffix)
        if ctype is None:
            return self._err(404, "not found")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def make_server(db_path: Path, host: str = "127.0.0.1", port: int = 0,
                changes_path: Path = None, verbose: bool = False):
    """Create (but don't start) the server. Returns (httpd, actual_port, ready_s)."""
    t0 = time.perf_counter()
    index = RegIndex(db_path)
    handler = type("BoundHandler", (_Handler,), {
        "index": index,
        "changes_path": changes_path,
    })
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    httpd.verbose = verbose
    ready_s = time.perf_counter() - t0
    handler.ready_at = ready_s
    return httpd, httpd.server_address[1], ready_s


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 0,
          changes_path: Path = None, verbose: bool = False,
          open_browser: bool = False) -> None:
    httpd, actual_port, ready_s = make_server(db_path, host, port,
                                              changes_path, verbose)
    url = f"http://{host}:{actual_port}/"
    print(f"peakrdl-check: serving {db_path} at {url} (ready in {ready_s * 1000:.0f} ms)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
