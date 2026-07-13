"""Deterministic SystemRDL benchmark fixture generator.

Generates seeded, reproducible SystemRDL sources with an exactly known
elaborated register count. The generator computes expected entity counts
analytically during generation and a separate `verify` subcommand re-derives
them from the elaborated model via systemrdl-compiler.

Design notes
------------
* All randomness flows from a single ``random.Random(seed)`` instance; the
  same parameters + seed always produce byte-identical output.
* A fixture is a set of *block types* instantiated one or more times under
  intermediate address maps. ``duplicate_ratio`` controls what fraction of
  block *instances* reuse shared block types (realistic SoCs repeat IP).
* Within a block, ``array_ratio`` controls what fraction of elaborated
  registers come from register arrays vs. individually declared registers.
  Arrays are how real designs reach large register counts (channel banks,
  buffer descriptor rings) without proportionally large source text.
* Register counts are exact: the generator solves for array sizes / scalar
  counts so the elaborated model contains precisely ``--registers`` registers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

WORDS = (
    "control status interrupt enable mask clear pending threshold watermark "
    "buffer descriptor channel stream transfer burst priority arbitration "
    "clock reset domain power gating retention voltage frequency divider "
    "phase lock calibration trim margin error corrupt parity checksum crc "
    "timeout latency credit flow window sequence acknowledge negotiate link "
    "lane symbol alignment training equalization emphasis swing detect"
).split()

ACCESS_CHOICES = ("rw", "r", "w", "rw1", "r_w1")  # weighted later


@dataclass
class FixtureParams:
    registers: int = 1000
    fields_per_register: int = 8
    blocks: int = 8
    duplicate_ratio: float = 0.4
    hierarchy_depth: int = 3          # top addrmap -> group addrmaps -> block -> (regfiles...)
    address_maps: int = 2             # intermediate group addrmaps under the top
    array_ratio: float = 0.9          # fraction of elaborated regs realized via arrays
    enum_ratio: float = 0.15          # fraction of fields carrying an enum encode
    desc_words: int = 12              # words per description
    include_files: int = 4            # number of type-definition include files (0 = single file)
    param_ratio: float = 0.25         # fraction of shared block types that are parameterized
    seed: int = 12345
    name: str = "fixture"

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class GenStats:
    register_defs: int = 0            # register declarations in source
    elaborated_registers: int = 0     # registers after array expansion
    elaborated_fields: int = 0
    block_types: int = 0
    block_instances: int = 0
    enum_types: int = 0
    source_lines: int = 0
    files: list = field(default_factory=list)


class FixtureGenerator:
    def __init__(self, params: FixtureParams):
        self.p = params
        self.rng = random.Random(params.seed)
        self.stats = GenStats()
        self._enum_count = 0

    # ---------------- description / naming helpers ----------------

    def _desc(self) -> str:
        n = self.p.desc_words
        if n <= 0:
            return ""
        words = [self.rng.choice(WORDS) for _ in range(n)]
        words[0] = words[0].capitalize()
        return " ".join(words) + "."

    def _field_access(self) -> str:
        r = self.rng.random()
        if r < 0.70:
            return "sw = rw; hw = r;"
        if r < 0.85:
            return "sw = r; hw = w;"
        if r < 0.95:
            return "sw = rw; hw = rw;"
        return "sw = w; hw = r;"

    # ---------------- component emitters ----------------

    def _emit_enum(self, out: list, block_idx: int) -> str:
        name = f"enum_b{block_idx}_e{self._enum_count}"
        self._enum_count += 1
        self.stats.enum_types += 1
        n_values = self.rng.randint(2, 5)
        out.append(f"    enum {name} {{")
        for v in range(n_values):
            out.append(
                f'        VAL_{v} = {v} {{ desc = "{self.rng.choice(WORDS)} option {v}"; }};'
            )
        out.append("    };")
        return name

    def _emit_reg_def(self, out: list, name: str, block_idx: int,
                      enums: list, regwidth: int = 32) -> None:
        """Emit one `reg` type definition with fields_per_register fields."""
        p = self.p
        nf = p.fields_per_register
        # Partition regwidth bits into nf contiguous fields (deterministic).
        avail = regwidth
        base_w = max(1, avail // nf)
        out.append(f"    reg {name}_t {{")
        out.append(f"        regwidth = {regwidth};")
        out.append(f'        desc = "{self._desc()}";')
        bit = 0
        for fi in range(nf):
            w = base_w if fi < nf - 1 else avail - base_w * (nf - 1)
            hi, lo = bit + w - 1, bit
            fname = f"f{fi}_{self.rng.choice(WORDS)}"
            acc = self._field_access()
            reset = self.rng.randrange(0, 1 << min(w, 30))
            parts = [f"field {{ {acc}"]
            parts.append(f'desc = "{self._desc()}";')
            if enums and w >= 3 and self.rng.random() < p.enum_ratio:
                parts.append(f"encode = {self.rng.choice(enums)};")
            parts.append(f"reset = 0x{reset:x};")
            parts.append(f"}} {fname}[{hi}:{lo}];")
            out.append("        " + " ".join(parts))
            bit += w
        out.append("    };")

    def _emit_block_type(self, out: list, type_name: str, block_idx: int,
                         regs_in_block: int, parameterized: bool) -> tuple:
        """Emit an addrmap block type containing exactly regs_in_block registers.

        Returns (elaborated_regs, elaborated_fields, reg_defs).
        """
        p = self.p
        # Split into array-realized and scalar-realized registers.
        array_regs = int(round(regs_in_block * p.array_ratio))
        scalar_regs = regs_in_block - array_regs

        # Choose number of array declarations: aim for arrays of ~64-512 elements.
        arrays = []  # list of (count_per_array)
        remaining = array_regs
        while remaining > 0:
            size = min(remaining, self.rng.choice((64, 128, 256, 512)))
            # Avoid a tiny trailing array; fold remainder into scalars if < 8
            if remaining - size < 8:
                size = remaining
            arrays.append(size)
            remaining -= size

        param_decl = ""
        if parameterized:
            param_decl = " #(longint unsigned RESET_BASE = 0x0)"

        out.append(f"addrmap {type_name}{param_decl} {{")
        out.append(f'    desc = "{self._desc()}";')

        # A couple of shared enums per block type
        enums = []
        for _ in range(2):
            enums.append(self._emit_enum(out, block_idx))

        reg_defs = 0
        elaborated = 0
        fields = 0

        # Nested regfile wrappers to realize hierarchy depth beyond addrmap level.
        depth_extra = max(0, p.hierarchy_depth - 3)
        indent_units = []
        for d in range(depth_extra):
            out.append("    " * (d + 1) + f"regfile {{")
            indent_units.append(d)
        pad = "    " * (depth_extra + 1)

        # Scalar register definitions + instances
        for i in range(scalar_regs):
            rname = f"r{i}_{self.rng.choice(WORDS)}"
            self._emit_reg_def(out, rname, block_idx, enums)
            out.append(f"{pad}{rname}_t {rname};")
            reg_defs += 1
            elaborated += 1
            fields += p.fields_per_register

        # Array register definitions + instances
        for ai, size in enumerate(arrays):
            rname = f"arr{ai}_{self.rng.choice(WORDS)}"
            self._emit_reg_def(out, rname, block_idx, enums)
            out.append(f"{pad}{rname}_t {rname}[{size}];")
            reg_defs += 1
            elaborated += size
            fields += size * p.fields_per_register

        for d in reversed(indent_units):
            out.append("    " * (d + 1) + f"}} rf_l{d};")

        out.append("};")
        out.append("")
        return elaborated, fields, reg_defs

    # ---------------- top-level generation ----------------

    def generate(self, output: Path) -> dict:
        p = self.p
        t0 = time.time()
        output.parent.mkdir(parents=True, exist_ok=True)

        n_unique_types = max(1, round(p.blocks * (1.0 - p.duplicate_ratio)))
        n_shared_types = max(0, min(p.blocks - n_unique_types,
                                    max(1, n_unique_types // 3))) if p.duplicate_ratio > 0 else 0
        # Instances: unique types instantiated once; shared types cover the rest.
        n_shared_instances = p.blocks - n_unique_types

        regs_per_block = p.registers // p.blocks
        remainder = p.registers - regs_per_block * p.blocks

        # Build block type plan. Shared types are assigned instance counts.
        type_plan = []  # (type_name, regs_in_block, n_instances, parameterized)
        for i in range(n_unique_types):
            extra = 1 if i < remainder else 0
            type_plan.append((f"blk_u{i}", regs_per_block + extra, 1, False))
        if n_shared_instances > 0 and n_shared_types > 0:
            per = n_shared_instances // n_shared_types
            rem = n_shared_instances - per * n_shared_types
            for i in range(n_shared_types):
                inst = per + (1 if i < rem else 0)
                if inst == 0:
                    continue
                parameterized = self.rng.random() < p.param_ratio
                type_plan.append((f"blk_s{i}", regs_per_block, inst, parameterized))

        # Emit type definitions, split across include files.
        n_files = max(0, p.include_files)
        file_bufs = [[] for _ in range(max(1, n_files))]
        per_type_meta = []
        for idx, (tname, regs_in_block, inst, parameterized) in enumerate(type_plan):
            buf = file_bufs[idx % len(file_bufs)]
            el, fl, rd = self._emit_block_type(buf, tname, idx, regs_in_block, parameterized)
            per_type_meta.append((tname, el, fl, rd, inst, parameterized))
            self.stats.block_types += 1
            self.stats.register_defs += rd

        # Top-level file: includes + instantiation hierarchy.
        top = []
        # Tool-name-free header: fixture bytes stay stable across tool renames
        top.append(f"// Generated benchmark fixture (seed={p.seed}); do not edit.")
        include_names = []
        if n_files > 0:
            for i, buf in enumerate(file_bufs):
                fname = f"{output.stem}_types_{i}.rdl"
                include_names.append(fname)
                (output.parent / fname).write_text("\n".join(buf) + "\n")
                top.append(f'`include "{fname}"')
        else:
            for buf in file_bufs:
                top.extend(buf)
        top.append("")

        # Distribute instances across intermediate group addrmaps.
        instances = []
        for tname, el, fl, rd, inst_count, parameterized in per_type_meta:
            for k in range(inst_count):
                instances.append((tname, el, fl, parameterized, k))
        self.rng.shuffle(instances)

        n_groups = max(1, p.address_maps)
        top.append(f"addrmap {p.name}_top {{")
        top.append(f'    desc = "{self._desc()}";')
        gsize = math.ceil(len(instances) / n_groups)
        total_regs = 0
        total_fields = 0
        for g in range(n_groups):
            chunk = instances[g * gsize:(g + 1) * gsize]
            if not chunk:
                continue
            top.append(f"    addrmap {{")
            top.append(f'        desc = "{self._desc()}";')
            for j, (tname, el, fl, parameterized, k) in enumerate(chunk):
                iname = f"{tname}_i{k}" if k or True else tname
                if parameterized:
                    base = self.rng.randrange(0, 1 << 16)
                    top.append(f"        {tname} #(.RESET_BASE(0x{base:x})) {iname};")
                else:
                    top.append(f"        {tname} {iname};")
                total_regs += el
                total_fields += fl
                self.stats.block_instances += 1
            top.append(f"    }} grp_{g};")
        top.append("};")
        top.append("")

        output.write_text("\n".join(top))
        self.stats.elaborated_registers = total_regs
        self.stats.elaborated_fields = total_fields

        # Checksums + manifest
        files = [output.name] + include_names
        checksums = {}
        total_lines = 0
        total_bytes = 0
        for fn in files:
            fp = output.parent / fn
            data = fp.read_bytes()
            checksums[fn] = hashlib.sha256(data).hexdigest()
            total_lines += data.count(b"\n")
            total_bytes += len(data)
        self.stats.source_lines = total_lines
        self.stats.files = files

        manifest = {
            "generator": "peakrdl-check-fixture",
            "generatorVersion": 1,
            "params": p.to_dict(),
            "topComponent": f"{p.name}_top",
            "files": files,
            "checksums": checksums,
            "sourceLines": total_lines,
            "sourceBytes": total_bytes,
            "expected": {
                "registers": total_regs,
                "fields": total_fields,
                "registerDefs": self.stats.register_defs,
                "blockTypes": self.stats.block_types,
                "blockInstances": self.stats.block_instances,
                "enumTypes": self.stats.enum_types,
            },
            "generationSeconds": round(time.time() - t0, 3),
        }
        manifest_path = output.with_suffix(".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest


# ---------------- verification ----------------

def count_elaborated(rdl_file: Path, top: str | None = None) -> dict:
    """Compile a fixture and count elaborated registers/fields exactly.

    Walks the non-unrolled tree and multiplies array dimensions, which yields
    the exact unrolled count without materializing every array element.
    """
    from systemrdl import RDLCompiler
    from systemrdl.node import RegNode, AddressableNode

    rdlc = RDLCompiler()
    rdlc.compile_file(str(rdl_file))
    root = rdlc.elaborate(top_def_name=top)

    regs = 0
    fields = 0

    def walk(node, mult: int):
        nonlocal regs, fields
        for child in node.children(unroll=False):
            m = mult
            if isinstance(child, AddressableNode) and child.is_array:
                for d in child.array_dimensions:
                    m *= d
            if isinstance(child, RegNode):
                regs += m
                nf = sum(1 for _ in child.fields())
                fields += m * nf
            else:
                walk(child, m)

    walk(root, 1)
    return {"registers": regs, "fields": fields}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="peakrdl-check-fixture",
                                 description="Deterministic SystemRDL benchmark fixture generator")
    sub = ap.add_subparsers(dest="cmd")

    gen = sub.add_parser("generate", help="generate a fixture")
    gen.add_argument("--registers", type=int, default=1000)
    gen.add_argument("--fields-per-register", type=int, default=8)
    gen.add_argument("--blocks", type=int, default=8)
    gen.add_argument("--duplicate-ratio", type=float, default=0.4)
    gen.add_argument("--hierarchy-depth", type=int, default=3)
    gen.add_argument("--address-maps", type=int, default=2)
    gen.add_argument("--array-ratio", type=float, default=0.9)
    gen.add_argument("--enum-ratio", type=float, default=0.15)
    gen.add_argument("--desc-words", type=int, default=12)
    gen.add_argument("--include-files", type=int, default=4)
    gen.add_argument("--param-ratio", type=float, default=0.25)
    gen.add_argument("--seed", type=int, default=12345)
    gen.add_argument("--name", default="fixture")
    gen.add_argument("--output", required=True, type=Path)

    ver = sub.add_parser("verify", help="verify a manifest against the elaborated model")
    ver.add_argument("manifest", type=Path)

    # Back-compat: bare invocation == generate
    args, extra = ap.parse_known_args(argv)
    if args.cmd is None:
        args = ap.parse_args(["generate"] + (argv if argv is not None else sys.argv[1:]))

    if args.cmd == "generate":
        params = FixtureParams(
            registers=args.registers,
            fields_per_register=args.fields_per_register,
            blocks=args.blocks,
            duplicate_ratio=args.duplicate_ratio,
            hierarchy_depth=args.hierarchy_depth,
            address_maps=args.address_maps,
            array_ratio=args.array_ratio,
            enum_ratio=args.enum_ratio,
            desc_words=args.desc_words,
            include_files=args.include_files,
            param_ratio=args.param_ratio,
            seed=args.seed,
            name=args.name,
        )
        manifest = FixtureGenerator(params).generate(args.output)
        print(json.dumps(manifest["expected"], indent=2))
        print(f"wrote {args.output} ({manifest['sourceLines']} lines, "
              f"{len(manifest['files'])} files)", file=sys.stderr)
        return 0

    if args.cmd == "verify":
        manifest = json.loads(args.manifest.read_text())
        rdl = args.manifest.parent / manifest["files"][0]
        # Verify checksums first
        for fn, expect in manifest["checksums"].items():
            actual = hashlib.sha256((args.manifest.parent / fn).read_bytes()).hexdigest()
            if actual != expect:
                print(f"CHECKSUM MISMATCH: {fn}", file=sys.stderr)
                return 2
        t0 = time.time()
        counts = count_elaborated(rdl, manifest["topComponent"])
        dt = time.time() - t0
        ok = (counts["registers"] == manifest["expected"]["registers"]
              and counts["fields"] == manifest["expected"]["fields"])
        print(json.dumps({"expected": manifest["expected"],
                          "actual": counts,
                          "compileSeconds": round(dt, 2),
                          "ok": ok}, indent=2))
        return 0 if ok else 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
