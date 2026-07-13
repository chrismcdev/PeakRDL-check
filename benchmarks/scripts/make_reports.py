#!/usr/bin/env python3
"""Generate benchmark reports from raw result files.

Reads every benchmarks/raw-results/*.json (the source of truth; never
hand-edited) and produces:
    benchmarks/results.json   — aggregated medians/variance per (tool, fixture)
    benchmarks/results.csv    — one row per raw run
    benchmarks/report.html    — self-contained comparison tables
    diff-corpus/report.html   — corpus outcome table

No numbers are typed by hand anywhere in this file.
"""

from __future__ import annotations

import csv
import html
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "benchmarks" / "raw-results"


def load_runs() -> list:
    runs = []
    for p in sorted(RAW.glob("*.json")):
        if p.name in ("mutation-results.json",):
            continue
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        data["_file"] = str(p.relative_to(ROOT))
        runs.append(data)
    return runs


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def variance_pct(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2 or not statistics.median(xs):
        return None
    return round(100 * (max(xs) - min(xs)) / statistics.median(xs), 1)


def aggregate(runs: list) -> dict:
    builds = [r for r in runs if r.get("tool") in ("regreview", "peakrdl-html")
              and "wallClockMs" in r]
    groups: dict[tuple, list] = {}
    for r in builds:
        groups.setdefault((r["tool"], r["fixture"], r.get("sourceMode", "default")),
                          []).append(r)
    agg = []
    for (tool, fixture, mode), rs in sorted(groups.items()):
        ok = [r for r in rs if not r.get("timeout") and r.get("exitCode") == 0]
        entry = {
            "tool": tool, "fixture": fixture, "sourceMode": mode,
            "runs": len(rs),
            "succeeded": len(ok),
            "timeouts": sum(1 for r in rs if r.get("timeout")),
            "failures": sum(1 for r in rs
                            if not r.get("timeout") and r.get("exitCode") != 0),
            "registerCount": rs[0].get("registerCount"),
            "wallClockMsMedian": med([r["wallClockMs"] for r in ok]),
            "wallClockVariancePct": variance_pct([r["wallClockMs"] for r in ok]),
            "peakRssBytesMedian": med([r.get("timePeakRssBytes") for r in ok]),
            "fileCountMedian": med([r.get("fileCount") for r in ok]),
            "outputBytesMedian": med([r.get("outputBytes") for r in ok]),
            "rawFiles": [r["_file"] for r in rs],
        }
        # stage timings from tool reports
        stages = {}
        for r in ok:
            tr = r.get("toolReport") or {}
            if tool == "peakrdl-html":
                for k in ("parseMs", "elaborationMs", "generationMs"):
                    stages.setdefault(k, []).append(tr.get(k))
            else:
                st = tr.get("stages") or {}
                for k, v in st.items():
                    stages.setdefault(k, []).append(
                        v * 1000 if isinstance(v, (int, float)) else None)
        entry["stagesMsMedian"] = {k: med(v) for k, v in stages.items() if med(v)}
        agg.append(entry)

    interactive = [r for r in runs if r.get("benchmark") == "interactive"]
    inter = []
    for r in interactive:
        inter.append({
            "label": r["label"],
            "dbBytes": r["dbBytes"],
            "serverReadySecondsMedian": r["serverReadySeconds"]["median"],
            "firstUsableSecondsMedian": r["firstUsableResponseSeconds"]["median"],
            "queries": {k: {"p50Ms": v["p50Ms"], "p95Ms": v["p95Ms"]}
                        for k, v in r["queries"].items()},
            "rawFile": r["_file"],
        })
    return {"builds": agg, "interactive": inter}


def write_csv(runs: list, path: Path):
    cols = ["timestamp", "tool", "fixture", "sourceMode", "run", "wallClockMs",
            "cpuTimeMs", "timePeakRssBytes", "fileCount", "outputBytes",
            "exitCode", "timeout", "registerCount", "command", "_file"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in runs:
            if "wallClockMs" in r:
                w.writerow(r)


def fmt_bytes(b):
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def write_html(agg: dict, path: Path):
    rows = []
    fixtures = sorted({e["fixture"] for e in agg["builds"]},
                      key=lambda f: ({"1k": 1, "10k": 2, "uniq10k": 3,
                                      "100k": 4, "400k": 5, "800k": 6}.get(f, 99)))
    for fx in fixtures:
        for e in [x for x in agg["builds"] if x["fixture"] == fx
                  and x["sourceMode"] in ("registers", "default")]:
            wall = (f"{e['wallClockMsMedian'] / 1000:.1f}s"
                    if e["wallClockMsMedian"] else
                    ("TIMEOUT" if e["timeouts"] else "FAILED"))
            rows.append(
                f"<tr><td>{fx}</td><td>{e['registerCount']:,}</td>"
                f"<td>{e['tool']}</td><td>{wall}</td>"
                f"<td>{e['wallClockVariancePct'] or '—'}</td>"
                f"<td>{fmt_bytes(e['peakRssBytesMedian'])}</td>"
                f"<td>{int(e['fileCountMedian']) if e['fileCountMedian'] else '—'}</td>"
                f"<td>{fmt_bytes(e['outputBytesMedian'])}</td>"
                f"<td>{e['succeeded']}/{e['runs']}</td></tr>")
    inter_rows = []
    for e in agg["interactive"]:
        qs = e["queries"]
        inter_rows.append(
            f"<tr><td>{e['label']}</td>"
            f"<td>{fmt_bytes(e['dbBytes'])}</td>"
            f"<td>{e['serverReadySecondsMedian'] * 1000:.0f} ms</td>"
            f"<td>{e['firstUsableSecondsMedian'] * 1000:.0f} ms</td>"
            + "".join(f"<td>{qs[k]['p50Ms']:.2f} / {qs[k]['p95Ms']:.2f}</td>"
                      for k in ("exactLookup", "childrenPage", "search",
                                "addressRange") if k in qs)
            + "</tr>")
    doc = f"""<!doctype html><meta charset="utf-8">
<title>RegReview benchmark report</title>
<style>body{{font:14px system-ui;margin:2rem auto;max-width:70rem;padding:0 1rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}
th,td{{border:1px solid #ccc;padding:4px 10px;text-align:left;font-variant-numeric:tabular-nums}}
th{{background:#f0f4ff}}</style>
<h1>RegReview benchmark report</h1>
<p>Generated from raw run records in <code>benchmarks/raw-results/</code>.
Medians over successful runs; variance = (max−min)/median.</p>
<h2>Build benchmarks (cold process, warm FS cache)</h2>
<table><tr><th>Fixture</th><th>Registers</th><th>Tool</th><th>Wall (median)</th>
<th>Var %</th><th>Peak RSS</th><th>Files</th><th>Output</th><th>OK</th></tr>
{''.join(rows)}</table>
<h2>Interactive (existing index; p50 / p95 ms)</h2>
<table><tr><th>Index</th><th>DB size</th><th>Server ready</th><th>First usable</th>
<th>Exact lookup</th><th>Children page</th><th>Search</th><th>Addr range</th></tr>
{''.join(inter_rows)}</table>
"""
    path.write_text(doc)


def write_corpus_html():
    res = json.loads((ROOT / "diff-corpus" / "results.json").read_text())
    rows = []
    for r in sorted(res["records"], key=lambda x: x["scenario"]):
        mark = "✓" if r["pass"] else "✗"
        rows.append(f"<tr><td>{mark}</td><td>{html.escape(r['scenario'])}</td>"
                    f"<td>{html.escape(str(r.get('title', '')))}</td>"
                    f"<td>{r.get('gitDiffLines', '?')}</td>"
                    f"<td>{r.get('totalChanges', '?')}</td>"
                    f"<td>{html.escape(json.dumps(r.get('summary', {})))}</td></tr>")
    doc = f"""<!doctype html><meta charset="utf-8">
<title>RegReview semantic-diff corpus</title>
<style>body{{font:14px system-ui;margin:2rem auto;max-width:70rem;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:4px 8px;text-align:left}}
th{{background:#f0f4ff}}</style>
<h1>Semantic-diff corpus: {res['passed']}/{res['total']} scenarios pass</h1>
<table><tr><th></th><th>Scenario</th><th>Title</th><th>git diff lines</th>
<th>semantic changes</th><th>summary</th></tr>{''.join(rows)}</table>"""
    (ROOT / "diff-corpus" / "report.html").write_text(doc)


def main() -> int:
    runs = load_runs()
    agg = aggregate(runs)
    (ROOT / "benchmarks" / "results.json").write_text(
        json.dumps(agg, indent=2) + "\n")
    write_csv(runs, ROOT / "benchmarks" / "results.csv")
    write_html(agg, ROOT / "benchmarks" / "report.html")
    write_corpus_html()
    print(f"aggregated {len(runs)} raw records -> benchmarks/results.json, "
          f"results.csv, report.html, diff-corpus/report.html")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
