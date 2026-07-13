# Reproducing the peakrdl-html large-map problems

The motivating claim behind RegReview is that the standard HTML exporter does
not scale to large register maps. That claim was **re-verified on the current
releases** (peakrdl 1.5.0, peakrdl-html 2.12.2, systemrdl-compiler 1.32.2) on
2026-07-13, not taken on historical faith.

## Fixture profiles

Fixtures are generated deterministically (`regreview-fixture`, seeded; manifests
with checksums in `fixtures/generated/`). Two profiles matter:

- **Mixed realistic** (`1k`, `10k`, `100k`, `400k`, `800k`): ~90 % of elaborated
  registers come from register arrays, and 40 % of block instances reuse shared
  block types (`duplicate_ratio: 0.4`) — the way real SoCs repeat IP. Register
  counts are exact by construction.
- **Unique profile** (`uniq10k`): `duplicate_ratio: 0.0`, `array_ratio: 0.0` —
  every one of the 10,000 registers is a distinct type. This isolates how tools
  behave when definition dedup cannot help.

## Commands used

```bash
# What was actually run (staged driver, identical to `peakrdl html`):
/usr/bin/time -l .venv/bin/python benchmarks/scripts/peakrdl_driver.py \
    fixtures/generated/100k.rdl benchmarks/out/bench-peakrdl-html-100k bench100k_top

# Equivalent CLI form:
peakrdl html fixtures/generated/100k.rdl -o out
```

The harness form (fresh subprocess per run, raw record per run):

```bash
.venv/bin/python benchmarks/scripts/bench.py \
    --fixture 1k,10k,100k,uniq10k --tools peakrdl-html --runs 3
```

## Measured results (medians, current 2.12.2)

| Fixture | Wall time | Output files | Output size | Peak RSS |
|---|---:|---:|---:|---:|
| 1k mixed | 0.66 s | 186 | 9.4 MB | 88 MB |
| 10k mixed | 4.2 s | 1,136 | 22 MB | 395 MB |
| 10k unique | 65 s | 10,078 | 147 MB | 3.7 GB |
| 100k mixed | 57.1 s | 10,603 | 154 MB | 3.1 GB |

Raw evidence: `benchmarks/raw-results/*peakrdl-html*.json` and
`benchmarks/out/prh-100k.log` (the `/usr/bin/time -l` capture of the 100k run:
57.12 s real, 3,133,521,920 bytes max RSS).

Both historical problems are confirmed in the current release:

1. **File-count explosion.** One `content/<uid>.html` per node: 10,603 files at
   100k mixed, 10,078 files at just 10k unique. Directory trees of this size
   are hostile to archiving, artifact upload, and file-share hosting.
2. **Eager full-model memory.** The exporter builds the complete RAL data
   structure in memory before writing (then chunks it to `data/ral-data-N.json`),
   so peak RSS tracks distinct-definition count: 3.7 GB for only 10k *unique*
   registers vs 395 MB for 10k mixed.

## Memory trajectory vs this machine

Peak RSS scales with distinct definitions, not raw register count:

- 100k mixed → 3.1 GB
- 10k unique → 3.7 GB

Extrapolating the mixed profile linearly, 800k mixed lands in the ~25 GB
region — at or beyond the 24 GB physically present on this machine — and a
mostly-unique 100k+ design blows past it far earlier (10k unique already costs
3.7 GB, so ~100k unique extrapolates to ~37 GB). The 800k peakrdl-html cell in
the full matrix is therefore run with a 1800 s timeout and its outcome recorded
as-is (timeout or completion), never extrapolated silently — see
[benchmarking.md](benchmarking.md).

For contrast, RegReview's clean 800k mixed build completes in ~210 s producing
one 337 MB SQLite file (85,151 node rows; `build/800k-build.json`), and its
peak RSS is dominated by the shared systemrdl-compiler front end, not the
index writer.
