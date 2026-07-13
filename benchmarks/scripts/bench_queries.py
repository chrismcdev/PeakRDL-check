#!/usr/bin/env python3
"""Interactive-use benchmark: existing-index startup + query latencies.

Measures against a live peakrdl-check server (fresh process per trial):
  * time from process spawn to /api/ready answering (server ready)
  * time to first usable viewer response (index.html + metadata + roots)
  * p50/p95 for exact lookup, register detail, paginated children, search,
    address-range over N keep-alive requests with randomized (seeded)
    parameters — so results are not flattered by SQLite page cache hits on
    a single row.

Raw samples are preserved in benchmarks/raw-results/.
"""

from __future__ import annotations

import http.client
import json
import random
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV = ROOT / ".venv" / "bin"
RAW = ROOT / "benchmarks" / "raw-results"


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * len(xs) + 0.5)) - 1)]


def sample_entities(db: Path, n: int, seed: int):
    """Deterministically sample register paths + parent ids + addresses."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    total = con.execute("SELECT COUNT(*) FROM node").fetchone()[0]
    rng = random.Random(seed)
    ids = sorted(rng.sample(range(1, total), min(n, total - 1)))
    paths, parents, addrs = [], [], []
    for node_id in ids:
        row = con.execute(
            "SELECT path, parent_id, addr, kind FROM node WHERE node_id=?",
            (node_id,)).fetchone()
        if not row:
            continue
        paths.append(row[0])
        if row[1] is not None:
            parents.append(row[1])
        addrs.append(int(row[2], 16))
    con.close()
    return paths, parents, addrs


WORDS = ("control status interrupt enable mask threshold watermark buffer "
         "channel transfer burst priority clock reset power frequency "
         "calibration error parity checksum timeout credit window link").split()


def main() -> int:
    index_dir = Path(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 else index_dir.name
    reps = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    db = index_dir / "register-map.sqlite" if index_dir.is_dir() else index_dir

    # --- startup trials (5 fresh processes) ---
    startup_ready, startup_first = [], []
    for trial in range(5):
        port = 8700 + trial
        t0 = time.perf_counter()
        proc = subprocess.Popen([str(VENV / "peakrdl-check"), "serve", str(db),
                                 "--port", str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ready = None
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    c = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
                    c.request("GET", "/api/ready")
                    if c.getresponse().status == 200:
                        ready = time.perf_counter() - t0
                        break
                except OSError:
                    time.sleep(0.005)
            # first usable viewer response: shell + metadata + first tree page
            t1 = time.perf_counter()
            c = http.client.HTTPConnection("127.0.0.1", port)
            for path in ("/", "/api/metadata", "/api/children?parent=root&limit=200"):
                c.request("GET", path)
                c.getresponse().read()
            first = time.perf_counter() - t1
            startup_ready.append(ready)
            startup_first.append(ready + first)
        finally:
            proc.terminate()
            proc.wait()

    # --- query latency trials (1 server, randomized params, keep-alive) ---
    port = 8710
    proc = subprocess.Popen([str(VENV / "peakrdl-check"), "serve", str(db),
                             "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    paths, parents, addrs = sample_entities(db, reps, seed=42)
    rng = random.Random(43)
    results = {}
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)

        def timed(path):
            t0 = time.perf_counter()
            conn.request("GET", path)
            r = conn.getresponse()
            body = r.read()
            return (time.perf_counter() - t0) * 1000, r.status, len(body)

        suites = {
            "exactLookup": lambda i: f"/api/entities/{paths[i % len(paths)]}",
            "registerDetail": lambda i: f"/api/entities/{paths[i % len(paths)]}",
            "childrenPage": lambda i: f"/api/children?parent={parents[i % len(parents)]}&limit=200",
            "search": lambda i: f"/api/search?q={WORDS[i % len(WORDS)]}&limit=50",
            "addressRange": lambda i: (
                lambda a: f"/api/address-range?start={a}&end={a + 0x4000}&limit=200")(
                addrs[i % len(addrs)]),
        }
        for name, mk in suites.items():
            samples = []
            max_body = 0
            for i in range(reps):
                ms, status, blen = timed(mk(rng.randrange(10 ** 6)))
                samples.append(ms)
                max_body = max(max_body, blen)
            results[name] = {
                "n": reps,
                "p50Ms": round(statistics.median(samples), 3),
                "p95Ms": round(pctl(samples, 95), 3),
                "maxMs": round(max(samples), 3),
                "maxResponseBytes": max_body,
                "samplesMs": [round(s, 3) for s in samples],
            }
    finally:
        proc.terminate()
        proc.wait()

    record = {
        "benchmark": "interactive",
        "index": str(db),
        "label": label,
        "dbBytes": db.stat().st_size,
        "serverReadySeconds": {
            "trials": [round(x, 4) for x in startup_ready],
            "median": round(statistics.median(startup_ready), 4),
        },
        "firstUsableResponseSeconds": {
            "trials": [round(x, 4) for x in startup_first],
            "median": round(statistics.median(startup_first), 4),
        },
        "queries": results,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"{time.strftime('%Y%m%d-%H%M%S')}-interactive-{label}.json"
    out.write_text(json.dumps(record, indent=2) + "\n")
    brief = {k: {"p50Ms": v["p50Ms"], "p95Ms": v["p95Ms"]}
             for k, v in results.items()}
    print(json.dumps({"label": label,
                      "readyMedianS": record["serverReadySeconds"]["median"],
                      "firstUsableMedianS": record["firstUsableResponseSeconds"]["median"],
                      "queries": brief}, indent=2))
    print(f"raw: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
