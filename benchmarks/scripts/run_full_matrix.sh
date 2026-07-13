#!/bin/bash
# Full benchmark matrix. Runs sequentially so measurements never contend.
# Raw results land in benchmarks/raw-results/ (one JSON per run).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
B="$PY $ROOT/benchmarks/scripts/bench.py"
Q="$PY $ROOT/benchmarks/scripts/bench_queries.py"

echo "=== build matrix: small sizes, both tools, 3 runs ==="
$B --fixture 1k,10k,100k --tools regreview,peakrdl-html --runs 3 --timeout 1800

echo "=== 400k: both tools, 3 runs ==="
$B --fixture 400k --tools regreview --runs 3 --timeout 1800
$B --fixture 400k --tools peakrdl-html --runs 3 --timeout 1800

echo "=== 800k: regreview 3 runs ==="
$B --fixture 800k --tools regreview --runs 3 --timeout 1800

echo "=== 800k: peakrdl-html 3 runs (30 min timeout each) ==="
$B --fixture 800k --tools peakrdl-html --runs 3 --timeout 1800

echo "=== source-location modes at 100k (3 runs each) ==="
for mode in none registers all; do
  $B --fixture 100k --tools regreview --runs 3 --source-mode $mode
done

echo "=== unique-register profile (10k), both tools ==="
$B --fixture uniq10k --tools regreview,peakrdl-html --runs 3 --timeout 1800

echo "=== interactive query benchmarks (indexes from the matrix runs) ==="
$Q "$ROOT/benchmarks/out/bench-regreview-100k" 100k 200
$Q "$ROOT/benchmarks/out/bench-regreview-400k" 400k 200
$Q "$ROOT/benchmarks/out/bench-regreview-800k" 800k 200

echo "=== incremental rebuild benchmark (3 preserved runs) ==="
$PY "$ROOT/benchmarks/scripts/bench_incremental.py"

echo "MATRIX COMPLETE"
