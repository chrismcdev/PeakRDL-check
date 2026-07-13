"""regreview command-line interface."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from . import __version__

EXIT_OK = 0
EXIT_FINDINGS = 1        # `check` found changes at/above the failure threshold
EXIT_ERROR = 2           # bad input / internal error
EXIT_USAGE = 3


def _peak_rss_bytes() -> int:
    # ru_maxrss is bytes on macOS, kilobytes on Linux.
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return v if sys.platform == "darwin" else v * 1024


def _hash_inputs(files, model) -> dict:
    import hashlib

    paths = {str(Path(f).resolve()) for f in files}
    paths.update(str(Path(p).resolve()) for p in model.src_files)
    out = {}
    for p in sorted(paths):
        try:
            out[p] = hashlib.sha256(Path(p).read_bytes()).hexdigest()
        except OSError:
            pass
    return out


def cmd_build(args) -> int:
    from .adapter import build_canonical
    from .storage import IndexWriter

    if args.mode == "static":
        print("error: static mode (in-browser SQLite) is not implemented in "
              "this release; use --mode server (see docs/adr/0008)",
              file=sys.stderr)
        return EXIT_USAGE

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "register-map.sqlite"

    if args.incremental:
        from .incremental import FullRebuildRequired, incremental_build
        try:
            report = incremental_build(args.files, out_dir, args.top,
                                       args.source_locations)
            report["peakRssBytes"] = _peak_rss_bytes()
            print(json.dumps(report, indent=2))
            return EXIT_OK
        except FullRebuildRequired as e:
            print(f"incremental: full rebuild required ({e.reason})",
                  file=sys.stderr)

    t_total = time.perf_counter()
    model = build_canonical(args.files, top=args.top, source_mode=args.source_locations)
    writer = IndexWriter(db_path)
    stats = writer.write_model(model, build_inputs=_hash_inputs(args.files, model))
    total_s = time.perf_counter() - t_total

    timings = model.timings.to_dict()
    report = {
        "output": str(db_path),
        "sourceMode": args.source_locations,
        "registers": stats["registers"],
        "decls": stats["nodes"],
        "definitions": stats["definitions"],
        "dbBytes": db_path.stat().st_size,
        "stages": {
            "parseSeconds": timings["parseSeconds"],
            "elaborateSeconds": timings["elaborateSeconds"],
            "traverseSeconds": timings["traverseSeconds"],
            "writeRowsSeconds": stats["writeRowsSeconds"],
            "createIndexSeconds": stats["createIndexSeconds"],
        },
        "totalSeconds": round(total_s, 3),
        "peakRssBytes": _peak_rss_bytes(),
    }
    print(json.dumps(report, indent=2))
    return EXIT_OK


def cmd_serve(args) -> int:
    from .server import serve

    p = Path(args.index)
    db = p / "register-map.sqlite" if p.is_dir() else p
    changes = Path(args.changes) if args.changes else (
        db.parent / "changes.json" if (db.parent / "changes.json").is_file() else None)
    serve(db, host=args.host, port=args.port, changes_path=changes,
          verbose=args.verbose)
    return EXIT_OK


def cmd_inspect(args) -> int:
    from .storage import RegIndex

    idx = RegIndex(Path(args.index) / "register-map.sqlite"
                   if Path(args.index).is_dir() else Path(args.index))
    meta = idx.metadata()
    print(json.dumps(meta, indent=2))
    return EXIT_OK


def _diff_result(args):
    """Compile base and head, run the semantic diff. Shared by diff/check."""
    from .adapter import build_canonical
    from .diff import compile_failed_result, diff_models
    from .policy import load_policy
    from systemrdl import RDLCompileError

    policy = load_policy(getattr(args, "policy", None))
    try:
        base = build_canonical([args.base], top=getattr(args, "base_top", None),
                               source_mode="all")
    except RDLCompileError as e:
        return compile_failed_result("base", str(e)), None
    try:
        head = build_canonical([args.head], top=getattr(args, "head_top", None),
                               source_mode="all")
    except RDLCompileError as e:
        return compile_failed_result("head", str(e)), None
    return diff_models(base, head, policy=policy,
                       rename_detection=not getattr(args, "no_rename_detection", False)), (base, head)


def cmd_diff(args) -> int:
    from .report import FORMATTERS

    result, _ = _diff_result(args)
    text = FORMATTERS[args.format](result)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
        print(f"wrote {args.output} ({result['totalChanges']} changes)")
    else:
        sys.stdout.write(text)
    if args.fail_on:
        return _severity_exit(result, args.fail_on)
    return EXIT_OK


def _severity_exit(result, threshold) -> int:
    fail_sets = {
        "breaking": {"breaking"},
        "behavioural": {"breaking", "behavioural", "uncertain"},
        "validation-error": {"breaking"},
    }
    trigger = fail_sets.get(threshold, {"breaking"})
    summary = result.get("summary", {})
    hits = sum(summary.get(c, 0) for c in trigger)
    if threshold == "validation-error":
        hits = 1 if result.get("compileError") else 0
    return EXIT_FINDINGS if hits else EXIT_OK


def cmd_check(args) -> int:
    from .report import format_text

    result, _ = _diff_result(args)
    sys.stdout.write(format_text(result))
    code = _severity_exit(result, args.fail_on)
    if code != EXIT_OK:
        print(f"check failed: changes at or above '{args.fail_on}' present",
              file=sys.stderr)
    return code


def cmd_query(args) -> int:
    """Ad-hoc query helper used by tests and benchmarks."""
    from .storage import RegIndex
    idx = RegIndex(Path(args.index) / "register-map.sqlite"
                   if Path(args.index).is_dir() else Path(args.index))
    t0 = time.perf_counter()
    if args.path:
        out = idx.register_detail(args.path)
    elif args.search:
        out = idx.search(args.search)
    elif args.children is not None:
        out = idx.children(args.children if args.children >= 0 else None)
    elif args.addr_range:
        lo, hi = (int(x, 0) for x in args.addr_range.split(":"))
        out = idx.address_range(lo, hi)
    else:
        out = idx.metadata()
    dt = (time.perf_counter() - t0) * 1000
    print(json.dumps(out, indent=2, default=str))
    print(f"# query time: {dt:.2f} ms", file=sys.stderr)
    return EXIT_OK


def cmd_doctor(args) -> int:
    import shutil
    import sqlite3

    checks = []

    def check(name, ok, detail):
        checks.append((name, bool(ok), detail))

    check("python", sys.version_info >= (3, 10),
          f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    try:
        import systemrdl
        check("systemrdl-compiler", True, systemrdl.__version__)
    except ImportError:
        check("systemrdl-compiler", False, "not importable")
    try:
        from peakrdl_html.__about__ import __version__ as prh_version
        check("peakrdl-html (baseline)", True, prh_version)
    except ImportError:
        check("peakrdl-html (baseline)", False, "not installed (benchmarks only)")
    v = sqlite3.sqlite_version_info
    check("sqlite", v >= (3, 43), f"{sqlite3.sqlite_version} "
          f"(contentless-delete FTS needs >= 3.43)")
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
        check("sqlite FTS5", True, "available")
    except sqlite3.OperationalError:
        check("sqlite FTS5", False, "missing")
    con.close()
    check("/usr/bin/time", Path("/usr/bin/time").exists(), "for benchmark RSS")
    try:
        import resource
        mem = None
        if sys.platform == "darwin":
            import subprocess as sp
            mem = int(sp.run(["sysctl", "-n", "hw.memsize"],
                             capture_output=True, text=True).stdout)
        check("memory", mem is None or mem >= 8 << 30,
              f"{mem / (1 << 30):.0f} GiB" if mem else "unknown")
    except Exception:
        check("memory", True, "unknown")

    ok = all(c[1] for c in checks if "baseline" not in c[0])
    for name, good, detail in checks:
        print(f"  [{'ok' if good else '!!'}] {name:28s} {detail}")
    print("doctor:", "ready" if ok else "problems found")
    return EXIT_OK if ok else EXIT_FINDINGS


def cmd_cache(args) -> int:
    import hashlib
    import sqlite3

    p = Path(args.index)
    db = p / "register-map.sqlite" if p.is_dir() else p
    if args.action == "clear":
        if db.exists():
            db.unlink()
            print(f"removed {db}")
        return EXIT_OK
    if not db.is_file():
        print("no index found", file=sys.stderr)
        return EXIT_ERROR
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")}
    con.close()
    inputs = json.loads(meta.get("build_inputs") or "{}")
    roots = json.loads(meta.get("block_roots") or "[]")
    if args.action == "list":
        for r in roots:
            print(f"  {r['path']:40s} type={r['type']} regs={r['regs']} "
                  f"file={r['file']}")
        return EXIT_OK
    if args.action == "stats":
        print(json.dumps({
            "units": len(roots),
            "trackedInputs": len(inputs),
            "dbBytes": db.stat().st_size,
            "schemaVersion": meta.get("storage_schema_version"),
            "sourceMode": meta.get("source_mode"),
        }, indent=2))
        return EXIT_OK
    if args.action == "verify":
        stale = []
        for path, digest in inputs.items():
            fp = Path(path)
            if not fp.is_file():
                stale.append((path, "missing"))
            elif hashlib.sha256(fp.read_bytes()).hexdigest() != digest:
                stale.append((path, "changed"))
        for path, why in stale:
            print(f"  stale ({why}): {path}")
        print("cache:", "valid" if not stale else f"{len(stale)} stale inputs")
        return EXIT_OK if not stale else EXIT_FINDINGS
    return EXIT_USAGE


def cmd_benchmark(args) -> int:
    import subprocess
    script = Path(__file__).parent.parent / "benchmarks" / "scripts" / "bench.py"
    cmd = [sys.executable, str(script), "--fixture", args.fixture,
           "--runs", str(args.runs)]
    if args.compare:
        cmd += ["--tools", f"regreview,{args.compare}"]
    else:
        cmd += ["--tools", "regreview"]
    return subprocess.call(cmd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="regreview")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build an index from SystemRDL sources")
    b.add_argument("files", nargs="+")
    b.add_argument("--output", "-o", required=True)
    b.add_argument("--top", default=None)
    b.add_argument("--source-locations", choices=("none", "registers", "all"),
                   default="registers")
    b.add_argument("--mode", choices=("server", "static"), default="server")
    b.add_argument("--incremental", action="store_true",
                   help="reuse an existing index, rebuilding only changed blocks")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("serve", help="serve an index locally")
    s.add_argument("index")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--changes", default=None,
                   help="changes.json from `regreview diff` to display")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=cmd_serve)

    i = sub.add_parser("inspect", help="show index metadata")
    i.add_argument("index")
    i.set_defaults(func=cmd_inspect)

    d = sub.add_parser("diff", help="semantic diff between two specifications")
    d.add_argument("--base", required=True)
    d.add_argument("--head", required=True)
    d.add_argument("--base-top", default=None)
    d.add_argument("--head-top", default=None)
    d.add_argument("--format", choices=("text", "json", "markdown", "sarif"),
                   default="text")
    d.add_argument("--output", "-o", default=None)
    d.add_argument("--policy", default=None)
    d.add_argument("--no-rename-detection", action="store_true")
    d.add_argument("--fail-on", choices=("breaking", "behavioural",
                                         "validation-error"), default=None)
    d.set_defaults(func=cmd_diff)

    c = sub.add_parser("check", help="CI gate: fail when changes exceed threshold")
    c.add_argument("--base", required=True)
    c.add_argument("--head", required=True)
    c.add_argument("--base-top", default=None)
    c.add_argument("--head-top", default=None)
    c.add_argument("--policy", default=None)
    c.add_argument("--no-rename-detection", action="store_true")
    c.add_argument("--fail-on", choices=("breaking", "behavioural",
                                         "validation-error"),
                   default="breaking")
    c.set_defaults(func=cmd_check)

    q = sub.add_parser("query", help="ad-hoc index queries (testing)")
    q.add_argument("index")
    q.add_argument("--path")
    q.add_argument("--search")
    q.add_argument("--children", type=int, default=None,
                   help="parent node id (-1 for roots)")
    q.add_argument("--addr-range", help="start:end (any int base)")
    q.set_defaults(func=cmd_query)

    doc = sub.add_parser("doctor", help="environment checks")
    doc.set_defaults(func=cmd_doctor)

    ca = sub.add_parser("cache", help="inspect or manage the incremental cache")
    ca.add_argument("action", choices=("list", "stats", "clear", "verify"))
    ca.add_argument("index")
    ca.set_defaults(func=cmd_cache)

    be = sub.add_parser("benchmark", help="run the benchmark suite")
    be.add_argument("--fixture", default="1k")
    be.add_argument("--compare", default=None, help="e.g. peakrdl-html")
    be.add_argument("--runs", type=int, default=3)
    be.set_defaults(func=cmd_benchmark)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
