#!/usr/bin/env bats
# Mock end-to-end counting gate — runs the real counting paths of
# wiz-azure.sh / wiz-aws.sh / wiz-gcp.sh against fixture APIs (curl and the
# cloud CLIs are stubbed from tests/mocks/bin; no network, no credentials)
# and diffs the produced <csp>-resources.csv against hand-verified expected
# files. Every count in tests/mocks/expected/ is derivable by hand from the
# fixtures in tests/mocks/fixtures/.
#
# Beyond plain counting, this suite pins the three defects fixed after the
# first review pass:
#   - fast mode must NEVER silently zero: a mid-sequence index/ARG/CAI query
#     failure discards the partial fast counts and falls back to the accurate
#     path (the final CSV equals the accurate one, not a mix);
#   - --org on GCP scopes project enumeration (org + folder tree) — projects
#     outside the org are never contacted;
#   - Azure/GCP token acquisition happens once per audience per run (the
#     file-based cache survives the subshells every HTTP call runs in).

setup() {
  ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  export MOCK_FIXTURES="$ROOT/tests/mocks/fixtures"
  export MOCK_CALLS_LOG="$BATS_TEST_TMPDIR/calls.log"
  export MOCK_HTTP_LOG="$BATS_TEST_TMPDIR/http.log"
  : > "$MOCK_CALLS_LOG"
  : > "$MOCK_HTTP_LOG"
  unset MOCK_HTTP_FAIL
  export PATH="$ROOT/tests/mocks/bin:$PATH"
  EXPECTED="$ROOT/tests/mocks/expected"
  cd "$BATS_TEST_TMPDIR"
}

# --- Azure -------------------------------------------------------------------

@test "wiz-azure.sh accurate counting matches expected CSV; one token acquisition" {
  run "${BASH:-bash}" "$ROOT/wiz-azure.sh" cloud \
    --subscription 00000000-0000-0000-0000-000000000001 --no-azdo \
    --max-parallel 1 --output-dir "$BATS_TEST_TMPDIR/out"
  [ "$status" -eq 0 ]
  diff "$EXPECTED/azure-resources.csv" "$BATS_TEST_TMPDIR/out/azure-resources.csv"
  # File-cached ARM token: az must have been invoked exactly once
  [ "$(grep -c 'get-access-token' "$MOCK_CALLS_LOG")" -eq 1 ]
}

@test "wiz-azure.sh --fast falls back to accurate when a mid-sequence ARG query fails" {
  # First two ARG queries succeed (12 fake VMs), the scale-set query 403s;
  # the partial fast rows must be discarded, not merged or zeroed.
  export MOCK_HTTP_FAIL='sku\.capacity'
  run "${BASH:-bash}" "$ROOT/wiz-azure.sh" cloud --fast \
    --subscription 00000000-0000-0000-0000-000000000001 --no-azdo \
    --max-parallel 1 --output-dir "$BATS_TEST_TMPDIR/out"
  [ "$status" -eq 0 ]
  [[ "$output" == *"[FALLBACK]"* ]]
  diff "$EXPECTED/azure-resources.csv" "$BATS_TEST_TMPDIR/out/azure-resources.csv"
}

# --- AWS ---------------------------------------------------------------------

@test "wiz-aws.sh accurate counting matches expected CSV" {
  run "${BASH:-bash}" "$ROOT/wiz-aws.sh" cloud --regions us-east-1 \
    --max-parallel 1 --output-dir "$BATS_TEST_TMPDIR/out"
  [ "$status" -eq 0 ]
  diff "$EXPECTED/aws-resources.csv" "$BATS_TEST_TMPDIR/out/aws-resources.csv"
}

@test "wiz-aws.sh --fast falls back to accurate when a later Resource Explorer query fails" {
  # The EC2 index query succeeds (9 fake instances), the Lambda query fails;
  # the 9 must be discarded and the accurate path recount everything.
  run "${BASH:-bash}" "$ROOT/wiz-aws.sh" cloud --fast --regions us-east-1 \
    --max-parallel 1 --output-dir "$BATS_TEST_TMPDIR/out"
  [ "$status" -eq 0 ]
  [[ "$output" == *"falling back to the accurate path"* ]]
  diff "$EXPECTED/aws-resources.csv" "$BATS_TEST_TMPDIR/out/aws-resources.csv"
}

# --- GCP ---------------------------------------------------------------------

@test "wiz-gcp.sh --org scopes enumeration to the org's folder tree; one token acquisition" {
  run "${BASH:-bash}" "$ROOT/wiz-gcp.sh" cloud --org 123 \
    --max-parallel 1 --output-dir "$BATS_TEST_TMPDIR/out"
  [ "$status" -eq 0 ]
  diff "$EXPECTED/gcp-resources-org.csv" "$BATS_TEST_TMPDIR/out/gcp-resources.csv"
  # proj-x (parent: another org) and proj-dead (inactive) must never be touched
  ! grep -q 'proj-x' "$MOCK_HTTP_LOG"
  ! grep -q 'proj-dead' "$MOCK_HTTP_LOG"
  # File-cached token: gcloud must have been invoked exactly once
  [ "$(grep -c 'print-access-token' "$MOCK_CALLS_LOG")" -eq 1 ]
}

@test "wiz-gcp.sh --projects counting matches expected CSV" {
  run "${BASH:-bash}" "$ROOT/wiz-gcp.sh" cloud --projects proj-a \
    --max-parallel 1 --output-dir "$BATS_TEST_TMPDIR/out"
  [ "$status" -eq 0 ]
  diff "$EXPECTED/gcp-resources-proj-a.csv" "$BATS_TEST_TMPDIR/out/gcp-resources.csv"
}

@test "wiz-gcp.sh --fast falls back to accurate when a mid-sequence CAI query fails" {
  # CAI instance queries succeed (5 fake results), the CloudFunction query
  # 403s — at the org sweep AND at each per-project retry. Both partial fast
  # count sets must be discarded; the final CSV is the accurate org result.
  export MOCK_HTTP_FAIL='cloudasset.*CloudFunction'
  run "${BASH:-bash}" "$ROOT/wiz-gcp.sh" cloud --fast --org 123 \
    --max-parallel 1 --output-dir "$BATS_TEST_TMPDIR/out"
  [ "$status" -eq 0 ]
  [[ "$output" == *"[FALLBACK]"* ]]
  diff "$EXPECTED/gcp-resources-org.csv" "$BATS_TEST_TMPDIR/out/gcp-resources.csv"
}
