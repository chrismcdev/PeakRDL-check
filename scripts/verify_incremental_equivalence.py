#!/usr/bin/env python3
"""Prove an incrementally-updated index is semantically equal to a clean build.

Compares canonical dumps: every node keyed by path with its kind, addresses,
sizes, array geometry, register counts, source location, and the full JSON
body of its definition. node_id/def_id assignment is allowed to differ (they
are storage details); everything semantic must be identical.

Usage: verify_incremental_equivalence.py A.sqlite B.sqlite
Exit 0 if equivalent, 1 with a bounded diff sample otherwise.
"""

from __future__ import annotations

import json
import sqlite3
import sys


def canonical_dump(db: str) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    defs = {r["def_id"]: r["body"] for r in con.execute("SELECT def_id, body FROM definition")}
    files = {r["file_id"]: r["path"] for r in con.execute("SELECT file_id, path FROM src_file")}
    out = {}
    parent_paths = {r["node_id"]: r["path"] for r in con.execute("SELECT node_id, path FROM node")}
    for r in con.execute("SELECT * FROM node"):
        out[r["path"]] = {
            "kind": r["kind"],
            "name": r["name"],
            "parent": parent_paths.get(r["parent_id"]),
            "addr": r["addr"],
            "addr_end": r["addr_end"],
            "offset": r["offset"],
            "size": r["size"],
            "array_dims": r["array_dims"],
            "array_stride": r["array_stride"],
            "reg_count": r["reg_count"],
            "src": (files.get(r["src_file_id"]), r["src_line"], r["src_col"]),
            "def": defs[r["def_id"]],
        }
    meta = {k: v for k, v in con.execute(
        "SELECT key, value FROM meta WHERE key IN ('counts', 'addr_min', 'addr_max')")}
    con.close()
    return {"nodes": out, "meta": meta}


def main() -> int:
    a, b = sys.argv[1], sys.argv[2]
    da, db_ = canonical_dump(a), canonical_dump(b)
    ok = True
    if json.loads(da["meta"]["counts"]) != json.loads(db_["meta"]["counts"]):
        print(f"META counts differ: {da['meta']['counts']} vs {db_['meta']['counts']}")
        ok = False
    na, nb = da["nodes"], db_["nodes"]
    only_a = sorted(set(na) - set(nb))[:10]
    only_b = sorted(set(nb) - set(na))[:10]
    if only_a:
        print(f"paths only in {a}: {only_a}")
        ok = False
    if only_b:
        print(f"paths only in {b}: {only_b}")
        ok = False
    diffs = 0
    for p in na:
        if p in nb and na[p] != nb[p]:
            if diffs < 10:
                for k in na[p]:
                    if na[p][k] != nb[p][k]:
                        print(f"DIFF {p}.{k}: {str(na[p][k])[:80]} != {str(nb[p][k])[:80]}")
            diffs += 1
            ok = False
    if diffs:
        print(f"{diffs} differing nodes total")
    print("EQUIVALENT" if ok else "NOT EQUIVALENT",
          f"({len(na)} nodes vs {len(nb)} nodes)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
