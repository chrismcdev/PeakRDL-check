"""Diff report formatters: text, json, markdown, sarif.

All formatters consume the canonical diff result dict produced by
peakrdl_check.diff and never recompute anything — one source of truth.
"""

from __future__ import annotations

import json

from .policy import CLASSIFICATION_ORDER

_ICONS = {
    "breaking": "✖",
    "behavioural": "△",
    "compatible": "✚",
    "documentation": "✎",
    "informational": "ℹ",
    "uncertain": "?",
}

_SARIF_LEVEL = {
    "breaking": "error",
    "behavioural": "warning",
    "uncertain": "warning",
    "compatible": "note",
    "documentation": "note",
    "informational": "note",
}


def format_text(result: dict) -> str:
    lines = []
    s = result.get("summary", {})
    lines.append("Semantic diff: "
                 + (", ".join(f"{v} {k}" for k, v in s.items()) or "no changes")
                 + f"  (policy {result.get('policyVersion', '?')})")
    lines.append("")
    for c in result.get("changes", []):
        icon = _ICONS.get(c["classification"], "·")
        lines.append(f"{icon} [{c['classification'].upper():13s}] {c['ruleId']:26s} {c['entityKey']}")
        lines.append(f"    {c['message']}")
        if c.get("before") is not None or c.get("after") is not None:
            lines.append(f"    before: {c.get('before')}    after: {c.get('after')}")
        loc = c.get("headLocation") or c.get("baseLocation")
        if loc:
            lines.append(f"    at {loc['file']}"
                         + (f":{loc['line']}" if loc.get("line") else ""))
        if c.get("confidence") != "certain":
            lines.append(f"    confidence: {c['confidence']}")
        if c.get("candidates"):
            lines.append(f"    candidates: {', '.join(c['candidates'])}")
    return "\n".join(lines) + "\n"


def format_json(result: dict) -> str:
    return json.dumps(result, indent=2) + "\n"


def format_markdown(result: dict) -> str:
    s = result.get("summary", {})
    if not s:
        return "# Register interface changes\n\nNo semantic changes detected.\n"
    md = ["# Register interface changes", ""]
    md.append("| Classification | Count |")
    md.append("|---|---|")
    for k in CLASSIFICATION_ORDER:
        if s.get(k):
            md.append(f"| {_ICONS[k]} {k} | {s[k]} |")
    md.append("")
    for k in CLASSIFICATION_ORDER:
        group = [c for c in result.get("changes", []) if c["classification"] == k]
        if not group:
            continue
        md.append(f"## {_ICONS[k]} {k.capitalize()} ({len(group)})")
        md.append("")
        for c in group:
            loc = c.get("headLocation") or c.get("baseLocation")
            loc_s = (f" — `{loc['file']}`"
                     + (f":{loc['line']}" if loc.get("line") else "")) if loc else ""
            md.append(f"- **`{c['entityKey']}`** `{c['ruleId']}`"
                      + (f" _(confidence: {c['confidence']})_"
                         if c.get("confidence") != "certain" else ""))
            md.append(f"  - {c['message']}{loc_s}")
            if c.get("before") is not None or c.get("after") is not None:
                md.append(f"  - before: `{c.get('before')}` → after: `{c.get('after')}`")
        md.append("")
    return "\n".join(md) + "\n"


def format_sarif(result: dict) -> str:
    rules_seen = {}
    results = []
    for c in result.get("changes", []):
        rid = c["ruleId"]
        rules_seen.setdefault(rid, {
            "id": rid,
            "shortDescription": {"text": rid.replace("-", " ").title()},
            "defaultConfiguration": {"level": _SARIF_LEVEL.get(c["classification"], "note")},
        })
        r = {
            "ruleId": rid,
            "level": _SARIF_LEVEL.get(c["classification"], "note"),
            "message": {"text": c["message"]},
            "properties": {
                "classification": c["classification"],
                "entityKey": c["entityKey"],
                "confidence": c.get("confidence"),
                "before": c.get("before"),
                "after": c.get("after"),
            },
        }
        loc = c.get("headLocation") or c.get("baseLocation")
        if loc and loc.get("file"):
            r["locations"] = [{
                "physicalLocation": {
                    "artifactLocation": {"uri": loc["file"]},
                    "region": {"startLine": max(1, loc.get("line") or 1),
                               "startColumn": max(1, loc.get("column") or 1)},
                }
            }]
        results.append(r)
    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "peakrdl-check",
                "informationUri": "https://github.com/chrismcdev/PeakRDL-check",
                "rules": sorted(rules_seen.values(), key=lambda r: r["id"]),
            }},
            "results": results,
        }],
    }
    return json.dumps(sarif, indent=2) + "\n"


FORMATTERS = {
    "text": format_text,
    "json": format_json,
    "markdown": format_markdown,
    "sarif": format_sarif,
}
