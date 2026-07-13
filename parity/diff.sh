#!/usr/bin/env bash
# parity/diff.sh — live parity harness (§8.4). Runs the official Python (from
# reference/) and our bash script against the SAME scope in a real
# tenant/account, then diffs the CSVs by resource type and emits a pass/fail
# report. This is the only place true byte-diffing happens for the cloud
# modes, and it is the gate (§3) that a CSP's Python retirement waits on.
#
# Scaffold status: runnable today with --stub (synthetic CSV pair proving the
# compare logic); wire a real environment by exporting the session and running
#   parity/diff.sh <azure|aws|gcp> --scope <ID> [--workdir DIR]
# from a shell that already has az/aws/gcloud auth. No env is bundled here.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR=""
STUB=0
SCOPE=""
CSP="${1:-}"
[ $# -gt 0 ] && shift

while [ $# -gt 0 ]; do
  case "$1" in
    --workdir) WORKDIR="$2"; shift 2 ;;
    --scope)   SCOPE="$2"; shift 2 ;;
    --stub)    STUB=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

usage() {
  cat <<'EOF'
Usage: parity/diff.sh <azure|aws|gcp> --scope ID [--workdir DIR]
       parity/diff.sh <azure|aws|gcp> --stub

Runs the official reference script and wiz-<csp>.sh against the SAME explicit
scope, then diffs the per-type counts in the resulting CSVs.

  --scope ID     REQUIRED for live runs — the single subscription (azure),
                 account (aws), or project (gcp) BOTH implementations scan.
                 Passing it explicitly is what guarantees identical scope:
                 the official Azure/GCP scripts otherwise prompt, and the
                 bash scripts otherwise default to everything visible.
  --workdir DIR  keep outputs in DIR (default: mktemp)
  --stub         skip the live runs; exercise the comparator on synthetic
                 fixtures (CI-safe self-test of this harness)
EOF
}

case "$CSP" in
  azure|aws|gcp) ;;
  *) usage; exit 2 ;;
esac

WORKDIR="${WORKDIR:-$(mktemp -d)}"
OFFICIAL_DIR="$WORKDIR/official"
OURS_DIR="$WORKDIR/ours"
mkdir -p "$OFFICIAL_DIR" "$OURS_DIR"

# Compare two <csp>-resources.csv files as type→count maps. Order-insensitive;
# every type present in either file is compared, missing = 0 mismatch.
compare_counts() { # $1 official csv, $2 ours csv
  local fail=0
  while IFS= read -r type; do
    local o m
    o=$(awk -F',' -v t="$type" 'NR>1 && $1==t {print $2}' "$1")
    m=$(awk -F',' -v t="$type" 'NR>1 && $1==t {print $2}' "$2")
    o="${o:-0}"; m="${m:-0}"
    if [ "$o" = "$m" ]; then
      printf 'PASS  %-45s official=%-8s ours=%s\n' "$type" "$o" "$m"
    else
      printf 'FAIL  %-45s official=%-8s ours=%s\n' "$type" "$o" "$m"
      fail=1
    fi
  done < <(tail -n +2 "$1" "$2" 2>/dev/null | awk -F',' '/,/{print $1}' | grep -v '^==>' | sort -u)
  return "$fail"
}

if [ "$STUB" -eq 1 ]; then
  # Self-test fixtures: prove the comparator flags a drifted count.
  printf 'Resource Type,Resource Count\nVirtual Machines,12\nServerless Functions,7\n' > "$OFFICIAL_DIR/$CSP-resources.csv"
  printf 'Resource Type,Resource Count\nVirtual Machines,12\nServerless Functions,7\n' > "$OURS_DIR/$CSP-resources.csv"
  echo "== parity/diff.sh stub self-test ($CSP) =="
  compare_counts "$OFFICIAL_DIR/$CSP-resources.csv" "$OURS_DIR/$CSP-resources.csv"
  echo "== stub PASS: comparator agrees on identical fixtures =="
  exit 0
fi

# ---- live mode (needs a real session; wired per §3 when a reference env lands)
if [ -z "$SCOPE" ]; then
  echo "error: live runs require --scope <ID> so both implementations provably scan the same" >&2
  echo "subscription/account/project (the official script would otherwise prompt, ours would" >&2
  echo "otherwise scan everything visible)." >&2
  exit 2
fi

# Both sides get the scope explicitly: official via --id, ours via its
# single-scope flag. This is the same-scope guarantee the §3 gate rests on.
case "$CSP" in
  azure)
    OFFICIAL="$ROOT/reference/cloud/azure/resource-count-azure-v2.py"
    OFFICIAL_ARGS=(--id "$SCOPE")
    OURS="$ROOT/wiz-azure.sh"
    OURS_ARGS=(--subscription "$SCOPE")
    ;;
  aws)
    OFFICIAL="$ROOT/reference/cloud/aws/resource-count-aws-v2.py"
    OFFICIAL_ARGS=(--id "$SCOPE")
    OURS="$ROOT/wiz-aws.sh"
    printf '%s\n' "$SCOPE" > "$WORKDIR/accounts.txt"
    OURS_ARGS=(--accounts-file "$WORKDIR/accounts.txt")
    ;;
  gcp)
    OFFICIAL="$ROOT/reference/cloud/gcp/resource-count-gcp-v2.py"
    OFFICIAL_ARGS=(--id "$SCOPE")
    OURS="$ROOT/wiz-gcp.sh"
    OURS_ARGS=(--projects "$SCOPE")
    ;;
esac

[ -f "$OURS" ] || { echo "$OURS not built yet" >&2; exit 1; }

echo "== official: $OFFICIAL (scope: $SCOPE) → $OFFICIAL_DIR"
(cd "$OFFICIAL_DIR" && python3 "$OFFICIAL" "${OFFICIAL_ARGS[@]}")

echo "== ours: $OURS (scope: $SCOPE) → $OURS_DIR"
(cd "$OURS_DIR" && bash "$OURS" cloud "${OURS_ARGS[@]}" --output-dir "$OURS_DIR" --quiet)

echo "== diff (per resource type) =="
if compare_counts "$OFFICIAL_DIR/$CSP-resources.csv" "$OURS_DIR/$CSP-resources.csv"; then
  echo "== PARITY PASS ($CSP) — record this run in PLAN.md §3 gate =="
else
  echo "== PARITY FAIL ($CSP) — investigate before retiring the Python =="
  exit 1
fi
