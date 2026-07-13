# Security policy

## Threat model

RegReview's primary untrusted input is the **specification itself**. Register
maps arrive from vendors, contractors and generated flows; descriptions and
names may contain hostile content. The tool must assume any `.rdl` file — and
any index built from one — is attacker-influenced.

Secondary surface: the local HTTP server (bound to localhost, but any local
process or browser tab can reach it) and index files received from others.

## Mitigations (all enforced by tests in `tests/test_security.py`)

### XSS via descriptions/names

- The API returns **JSON only** — no endpoint ever renders spec text into
  HTML (`test_api_is_json_only_never_html`; `X-Content-Type-Options: nosniff`
  on every response).
- The viewer inserts all untrusted text via **`textContent` exclusively**.
  `innerHTML`, `outerHTML`, `document.write` and `insertAdjacentHTML` are
  absent from the codebase and their absence is asserted by test
  (`test_viewer_never_uses_innerhtml`).
- Hostile payloads (`<script>`, event-handler attributes, template syntax)
  are round-tripped as inert data in the test fixture.

### Path traversal

Static serving is restricted to the packaged viewer directory: the resolved
target must be inside `regreview/viewer/`, must exist, and must have an
allow-listed extension (`.html/.js/.css/.svg`). Encoded and plain `../`
probes return 404 (`test_path_traversal_blocked`,
`test_unknown_static_types_rejected`).

### Network exposure

The server binds **127.0.0.1** unless explicitly overridden
(`test_server_binds_localhost_only`). No accounts, no cookies, no state; the
index is opened read-only.

### Resource abuse / malformed queries

- URL length is capped at 4096 (HTTP 414, `test_url_length_limited`).
- All `limit` parameters are clamped server-side (children/address-range max
  1000, search max 500 — `test_query_limit_clamped`).
- Address ranges are validated: non-numeric, inverted, or > 2^64-wide ranges
  are rejected with 400 (`test_bad_address_range_rejected`).
- Search input is tokenised into a sanitised FTS5 prefix query — FTS
  operators cannot be injected (`test_search_operators_handled`).
- Deep hierarchies (24+ levels) and 100 KB descriptions build and query
  without pathological behaviour (`test_deep_hierarchy_and_long_descriptions`).
- Unhandled exceptions return a generic 500 with the exception *type* only;
  tracebacks are never sent to the client.

### Corrupt or foreign index files

`RegIndex` refuses databases without a readable `storage_schema_version`
matching the supported version, and opens indexes read-only (`mode=ro` URI).
Treat `.sqlite` indexes from untrusted parties like any untrusted file:
schema-version rejection is an integrity check, not a sandbox.

## Known non-mitigations

- SQLite itself parses the index file; a maliciously crafted database
  exercises SQLite's file-format robustness, which RegReview inherits from
  the platform's SQLite build.
- The server offers no authentication; anything on localhost can query a
  served index. Do not serve confidential maps on shared machines, or bind to
  a non-default host.

## Reporting a vulnerability

Report suspected vulnerabilities privately to the maintainers (repository
owner contact or the security contact in the repository metadata) rather than
opening a public issue. Include a minimal reproducing spec or request
sequence. You should receive an acknowledgement within 7 days; please allow
90 days for a fix before public disclosure.
