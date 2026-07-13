#!/bin/bash
# Local end-to-end exercise of the GitHub Action logic (Gate G evidence).
#
# Creates a throwaway git repo with a UART spec, makes (a) a breaking PR and
# (b) a documentation-only PR, and runs action/review.py exactly as the
# composite action would — with GITHUB_STEP_SUMMARY / GITHUB_OUTPUT wired to
# files. Asserts the breaking PR fails and the docs PR passes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
WORK="$(mktemp -d /tmp/peakrdl-check-pr-sim.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

cd "$WORK"
git init -q -b main
git config user.email ci@example.com
git config user.name CI

mkdir -p specs
cat > specs/uart.rdl <<'EOF'
addrmap uart {
    reg {
        desc = "Control register.";
        field { sw = rw; hw = r; reset = 0x0; } en[0:0];
        field { sw = rw; hw = r; reset = 0x3; } baud[3:1];
    } ctrl @ 0x0;
    reg { field { sw = r; hw = w; } busy[0:0]; } status @ 0x4;
};
EOF
git add -A && git commit -qm "base spec"
BASE_SHA=$(git rev-parse HEAD)

# --- PR 1: breaking (register moved) ---
git checkout -qb pr-breaking
sed -i '' 's/} status @ 0x4;/} status @ 0x40;/' specs/uart.rdl
git commit -qam "move status register"
HEAD_SHA=$(git rev-parse HEAD)

run_review() {
  local base=$1 head=$2 outdir=$3
  mkdir -p "$outdir"
  rm -rf peakrdl-check-out
  env BASE_REF="$base" HEAD_REF="$head" FAIL_ON=breaking \
      GITHUB_STEP_SUMMARY="$outdir/summary.md" \
      GITHUB_OUTPUT="$outdir/outputs.txt" \
      "$PY" "$ROOT/action/review.py" > "$outdir/annotations.txt" 2> "$outdir/stderr.txt"
}

echo "== PR 1: breaking change =="
if run_review "$BASE_SHA" "$HEAD_SHA" "$WORK/pr1"; then
  echo "FAIL: breaking PR did not fail the check"; exit 1
else
  echo "ok: exited nonzero as expected"
fi
grep -q "::error" "$WORK/pr1/annotations.txt" && echo "ok: error annotation emitted"
grep -q "breaking-count=1" "$WORK/pr1/outputs.txt" && echo "ok: breaking-count output"
grep -q "REG-ADDRESS-CHANGED" "$WORK/pr1/summary.md" && echo "ok: job summary explains the change"

# --- PR 2: documentation-only ---
git checkout -q main
git checkout -qb pr-docs
sed -i '' 's/Control register./Primary control register for the UART./' specs/uart.rdl
git commit -qam "reword description"
DOCS_SHA=$(git rev-parse HEAD)

echo "== PR 2: documentation-only change =="
if run_review "$BASE_SHA" "$DOCS_SHA" "$WORK/pr2"; then
  echo "ok: docs-only PR passed"
else
  echo "FAIL: docs-only PR failed the check"; exit 1
fi
grep -q "DESC-CHANGED" "$WORK/pr2/summary.md" && echo "ok: summary reports documentation change"
grep -q "breaking-count=0" "$WORK/pr2/outputs.txt" && echo "ok: zero breaking"

# preserve evidence
DEST="$ROOT/benchmarks/raw-results/pr-workflow-simulation"
rm -rf "$DEST" && mkdir -p "$DEST"
cp -r "$WORK/pr1" "$WORK/pr2" "$DEST/"
echo "evidence preserved in $DEST"
echo "PR workflow simulation: ALL CHECKS PASSED"
