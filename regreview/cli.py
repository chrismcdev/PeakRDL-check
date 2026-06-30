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


def cmd_build(args) -> int:
    from .adapter import build_canonical
    from .storage import IndexWriter

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "register-map.sqlite"

    t_total = time.perf_counter()
    model = build_canonical(args.files, top=args.top, source_mode=args.source_locations)
    writer = IndexWriter(db_path)
    stats = writer.write_model(model)
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


def cmd_inspect(args) -> int:
    from .storage import RegIndex

    idx = RegIndex(Path(args.index) / "register-map.sqlite"
                   if Path(args.index).is_dir() else Path(args.index))
    meta = idx.metadata()
    print(json.dumps(meta, indent=2))
    return EXIT_OK


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
    b.set_defaults(func=cmd_build)

    i = sub.add_parser("inspect", help="show index metadata")
    i.add_argument("index")
    i.set_defaults(func=cmd_inspect)

    q = sub.add_parser("query", help="ad-hoc index queries (testing)")
    q.add_argument("index")
    q.add_argument("--path")
    q.add_argument("--search")
    q.add_argument("--children", type=int, default=None,
                   help="parent node id (-1 for roots)")
    q.add_argument("--addr-range", help="start:end (any int base)")
    q.set_defaults(func=cmd_query)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
