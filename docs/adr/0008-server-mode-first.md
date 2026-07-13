# ADR-0008: Server mode first; static in-browser mode deferred

Status: accepted (2026-07-13)

## Context

Two ways to put a SQLite index in front of a reviewer:

1. **Local server**: a tiny localhost HTTP process queries the index and
   serves a paginated JSON API to the viewer.
2. **Static viewer**: ship SQLite compiled to WASM and query the `.sqlite`
   file directly in the browser — no process at all, hostable on any file
   share.

## Decision

Ship **server mode** in v1; defer the static SQLite-WASM mode.

- The product must work fully offline with no external dependencies.
  SQLite-WASM means vendoring and maintaining a compiled WASM artifact
  (~1 MB+, its own build/update/security lifecycle) inside the repo — real
  cost, and the OPFS/Range-request access patterns for large DB files need
  their own performance validation.
- The server is nearly free: Python stdlib `ThreadingHTTPServer`, no
  dependencies, binds 127.0.0.1 by default, read-only over the index. It also
  gives a natural place for server-side clamps on untrusted queries.

## The TCP_NODELAY fix

The stdlib server initially showed a flat **~50 ms on every keep-alive
request** regardless of query cost: response headers and body were written as
separate TCP segments, interacting with Nagle's algorithm + delayed ACK on
macOS. Fix (in `_Handler`): buffer the whole response (`wbufsize = 64 KiB`)
and set `disable_nagle_algorithm = True`. Measured effect: the flat penalty
disappeared and API p95s dropped to sub-millisecond on built indexes
(measured with `benchmarks/scripts/bench_queries.py`). Worth documenting
because every stdlib `BaseHTTPRequestHandler` user hits this.

## Consequences

- One command (`regreview serve build/100k --port 8642`), works air-gapped;
  `--mode static` is reserved in the CLI but not yet implemented.
- Viewer and API co-designed: everything paginated, JSON-only, no
  full-hierarchy responses.
- **For the future static mode**: the practical maximum DB size a browser can
  handle over WASM/OPFS is unknown and must be *measured then*, not assumed —
  the 337 MB 800k index is well beyond what typical in-browser SQLite demos
  exercise.
