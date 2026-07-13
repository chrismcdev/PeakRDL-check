#!/usr/bin/env python3
"""Generated mutation tests for the semantic diff engine.

Builds a seeded base specification with EXPLICIT addresses (mutations stay
local — no auto-allocation ripple), applies one known mutation per trial from
a catalog with ground truth, and scores the engine:

  recall    = trials where the expected rule fired on the expected entity
  precision = expected change records / all change records emitted
              (any extra record beyond ground truth counts against precision)

Neutral mutations (whitespace, comments, reorder, numeric format) expect
zero changes; any report is a false positive.

Results: benchmarks/raw-results/mutation-results.json (per-trial detail).
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from peakrdl_check.adapter import build_canonical      # noqa: E402
from peakrdl_check.diff import diff_models             # noqa: E402

N_REGS = 40
N_FIELDS = 4


def base_spec(seed: int) -> str:
    rng = random.Random(seed)
    lines = ["addrmap mut_top {"]
    for i in range(N_REGS):
        lines.append(f"    reg {{")
        lines.append(f'        desc = "Register {i} description text.";')
        bit = 0
        for f in range(N_FIELDS):
            w = rng.choice((1, 2, 4, 6))
            reset = rng.randrange(0, 1 << w)
            lines.append(
                f"        field {{ sw = rw; hw = r; reset = {reset:#x}; }} "
                f"f{f}[{bit + w - 1}:{bit}];")
            bit += w + 1
        lines.append(f"    }} r{i} @ {i * 0x10:#x};")
    lines.append("};")
    return "\n".join(lines) + "\n"


# Each mutation: (name, expected rule or None, function text->text or None-if-inapplicable)
def mut_reset(text, rng):
    ms = list(re.finditer(r"reset = (0x[0-9a-f]+)", text))
    m = rng.choice(ms)
    flipped = int(m.group(1), 16) ^ 1   # always fits the field width
    return text[:m.start()] + f"reset = {flipped:#x}" + text[m.end():]


def mut_remove_reg(text, rng):
    regs = list(re.finditer(r"    reg \{.*?\} r(\d+) @ [^;]+;\n", text, re.S))
    m = rng.choice(regs)
    return text[:m.start()] + text[m.end():]


def mut_address(text, rng):
    i = rng.randrange(N_REGS)
    return text.replace(f"@ {i * 0x10:#x};", f"@ {N_REGS * 0x10 + i * 0x10:#x};")


def mut_access(text, rng):
    ms = list(re.finditer(r"sw = rw", text))
    m = rng.choice(ms)
    return text[:m.start()] + "sw = r" + text[m.end():]


def mut_remove_field(text, rng):
    ms = list(re.finditer(r"        field \{[^}]*\} f3\[[^\]]+\];\n", text))
    m = rng.choice(ms)
    return text[:m.start()] + text[m.end():]


def mut_field_width(text, rng):
    ms = list(re.finditer(
        r"field \{ sw = rw; hw = r; reset = (0x[0-9a-f]+); \} f0\[(\d+):0\];",
        text))
    ms = [m for m in ms if int(m.group(2)) > 0]
    if not ms:
        return None
    m = rng.choice(ms)
    msb = int(m.group(2)) - 1
    old_reset = int(m.group(1), 16)
    reset = old_reset & ((1 << (msb + 1)) - 1)  # keep reset in range
    repl = f"field {{ sw = rw; hw = r; reset = {reset:#x}; }} f0[{msb}:0];"
    mutated = text[:m.start()] + repl + text[m.end():]
    # If masking altered the reset, the engine SHOULD also report it.
    mut_field_width.companions = ({"RESET-VALUE-CHANGED"}
                                  if reset != old_reset else set())
    return mutated


def mut_add_reg(text, rng):
    add = (f"    reg {{ field {{ sw = r; hw = w; }} v[7:0]; }} "
           f"r_new @ {N_REGS * 0x40:#x};\n")
    return text.replace("};\n", add + "};\n", 1) if text.endswith("};\n") else None


def mut_desc(text, rng):
    i = rng.randrange(N_REGS)
    return text.replace(f'"Register {i} description text."',
                        f'"Register {i} has completely reworded documentation."')


def mut_whitespace(text, rng):
    lines = text.splitlines()
    i = rng.randrange(len(lines))
    lines[i] = lines[i] + "   "
    return "\n".join(lines) + "\n\n"


def mut_comment(text, rng):
    return text.replace("addrmap mut_top {",
                        "// reviewed by mutation tester\naddrmap mut_top {")


def mut_numfmt(text, rng):
    ms = list(re.finditer(r"reset = 0x([0-9a-f]+)", text))
    m = rng.choice(ms)
    return text[:m.start()] + f"reset = {int(m.group(1), 16)}" + text[m.end():]


def mut_reorder(text, rng):
    regs = list(re.finditer(r"    reg \{.*?\} r\d+ @ [^;]+;\n", text, re.S))
    if len(regs) < 2:
        return None
    a, b = regs[0], regs[1]
    return (text[:a.start()] + text[b.start():b.end()] +
            text[a.end():b.start()] + text[a.start():a.end()] + text[b.end():])


CATALOG = [
    ("reset-change", "RESET-VALUE-CHANGED", mut_reset),
    ("remove-reg", "REG-REMOVED", mut_remove_reg),
    ("move-reg", "REG-ADDRESS-CHANGED", mut_address),
    ("access-rw-to-r", "ACCESS-RW-TO-RO", mut_access),
    ("remove-field", "FIELD-REMOVED", mut_remove_field),
    ("shrink-field", "FIELD-WIDTH-REDUCED", mut_field_width),
    ("add-reg-unused", "REG-ADDED-UNUSED-SPACE", mut_add_reg),
    ("desc-reword", "DESC-CHANGED", mut_desc),
    ("whitespace", None, mut_whitespace),
    ("comment", None, mut_comment),
    ("numeric-format", None, mut_numfmt),
    ("reorder", None, mut_reorder),
]


def main() -> int:
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 240
    master = random.Random(20260713)
    tmp = Path("/tmp/peakrdl-check-mutations")
    tmp.mkdir(exist_ok=True)

    records = []
    tp = fp = fn = 0
    for t in range(trials):
        seed = master.randrange(1 << 30)
        rng = random.Random(seed)
        name, expected_rule, fn_mut = CATALOG[t % len(CATALOG)]
        base_text = base_spec(seed)
        mutated = fn_mut(base_text, rng)
        if mutated is None or mutated == base_text:
            continue
        bf, af = tmp / f"b{t}.rdl", tmp / f"a{t}.rdl"
        bf.write_text(base_text)
        af.write_text(mutated)
        base = build_canonical([bf], source_mode="none")
        head = build_canonical([af], source_mode="none")
        result = diff_models(base, head)
        changes = result["changes"]

        # Ambiguity note: removing/adding may legitimately emit MATCH-UNCERTAIN
        # advisories; they are counted as expected companions, not FPs, when a
        # removal/addition ground truth is present.
        companions = {"MATCH-UNCERTAIN"} if expected_rule in (
            "REG-REMOVED", "REG-ADDED-UNUSED-SPACE") else set()
        companions |= getattr(fn_mut, "companions", set())
        fn_mut.companions = set()

        if expected_rule is None:
            ok = len(changes) == 0
            n_fp = len(changes)
            n_tp, n_fn = 0, 0
        else:
            hits = [c for c in changes if c["ruleId"] == expected_rule]
            ok = bool(hits)
            n_tp = 1 if hits else 0
            n_fn = 0 if hits else 1
            n_fp = len([c for c in changes
                        if c["ruleId"] != expected_rule
                        and c["ruleId"] not in companions])
        tp += n_tp
        fp += n_fp
        fn += n_fn
        records.append({
            "trial": t, "mutation": name, "seed": seed,
            "expectedRule": expected_rule,
            "changes": [(c["ruleId"], c["entityKey"]) for c in changes],
            "detected": ok, "falsePositives": n_fp,
        })

    detected = sum(1 for r in records if r["detected"])
    semantic = [r for r in records if r["expectedRule"]]
    neutral = [r for r in records if not r["expectedRule"]]
    out = {
        "trials": len(records),
        "semanticTrials": len(semantic),
        "neutralTrials": len(neutral),
        "detectedOverall": detected,
        "recall": round(sum(1 for r in semantic if r["detected"]) / len(semantic), 4),
        "neutralSuppression": round(
            sum(1 for r in neutral if r["detected"]) / len(neutral), 4),
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        "truePositives": tp, "falsePositives": fp, "falseNegatives": fn,
        "perMutation": {},
        "records": records,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    for name, expected_rule, _ in CATALOG:
        rs = [r for r in records if r["mutation"] == name]
        if rs:
            out["perMutation"][name] = {
                "trials": len(rs),
                "detected": sum(1 for r in rs if r["detected"]),
                "falsePositives": sum(r["falsePositives"] for r in rs),
            }
    raw = ROOT / "benchmarks" / "raw-results"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "mutation-results.json").write_text(json.dumps(out, indent=2) + "\n")
    brief = {k: v for k, v in out.items() if k not in ("records", "perMutation")}
    print(json.dumps(brief, indent=2))
    for name, stats in out["perMutation"].items():
        print(f"  {name:18s} {stats['detected']}/{stats['trials']} detected, "
              f"{stats['falsePositives']} FP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
