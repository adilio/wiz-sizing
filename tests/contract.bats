#!/usr/bin/env bats
# §8.2 CSV contract — the hard gate.
#
# Every wiz-<csp>.sh must emit the official scripts' exact default CSV
# filenames and header rows. Each script exposes `--print-csv-contract`,
# which prints one line per output file:
#
#   <default filename><TAB><exact header row, or (no header) for plain lists>
#
# The expected values below are transcribed from the official scripts under
# reference/ (the parity oracle) — see each stanza's source citation. Dynamic
# filename timestamps print as the literal placeholder YYYYMMDD-HHMMSS; the
# dynamic day window prints with its default (90 days for code counting).
#
# Runs with no cloud session. A script that does not exist yet is skipped
# (phases land one script at a time); a script that exists must comply.

setup() {
  ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
}

contract() { # $1 = script
  run bash "$ROOT/$1" --print-csv-contract
  [ "$status" -eq 0 ]
}

require_line() { # $1 = exact expected line
  local expected="$1" line found=1
  while IFS= read -r line; do
    [ "$line" = "$expected" ] && found=0
  done <<< "$output"
  if [ "$found" -ne 0 ]; then
    echo "missing contract line: [$expected]" >&2
    echo "--- actual output ---" >&2
    echo "$output" >&2
    return 1
  fi
}

TAB=$'\t'

# --- wiz-azure.sh -----------------------------------------------------------
# reference/cloud/azure/resource-count-azure-v2.py:232-233,1134,1140
# reference/defend/azure/log-volume-estimation-azure.py:58,633
# reference/code/azure-devops/active-developer-count-ado.py:715,718

@test "wiz-azure.sh CSV contract" {
  [ -f "$ROOT/wiz-azure.sh" ] || skip "wiz-azure.sh not built yet"
  contract wiz-azure.sh
  require_line "azure-resources.csv${TAB}Resource Type,Resource Count"
  require_line "azure-resources-log.csv${TAB}Resource Type,Resource Count,Subscription"
  require_line "azure-defend-log-volume-YYYYMMDD-HHMMSS.csv${TAB}Log Source Type,Billable Category,Specific Metric,Resource/Scope Details,Estimated 30-Day Uncompressed Volume (GB)"
  require_line "azure_devops-<ORG>-developers.txt${TAB}(no header; one hashed developer email per line)"
  require_line "azure_devops-<ORG>-developers-log.txt${TAB}Organization,Project,Repository,Developers (Last 90 Days),Commits Scanned,Status,Error"
}

@test "wiz-azure.sh Defend GB values use %.2f" {
  [ -f "$ROOT/wiz-azure.sh" ] || skip "wiz-azure.sh not built yet"
  grep -q '%\.2f' "$ROOT/wiz-azure.sh"
}

# --- wiz-aws.sh -------------------------------------------------------------
# reference/cloud/aws/resource-count-aws-v2.py:209-210,1357,1363
# reference/defend/aws/log-volume-estimation-aws.py:148,834

@test "wiz-aws.sh CSV contract" {
  [ -f "$ROOT/wiz-aws.sh" ] || skip "wiz-aws.sh not built yet"
  contract wiz-aws.sh
  require_line "aws-resources.csv${TAB}Resource Type,Resource Count"
  require_line "aws-resources-log.csv${TAB}Resource Type,Resource Count,Account,Region"
  require_line "aws-defend-log-volume.csv${TAB}Log Source Type,Billable Category,Specific Metric,Bucket/Prefix Details,Estimated 30-Day Uncompressed Volume (GB)"
}

@test "wiz-aws.sh Defend GB values use %.2f" {
  [ -f "$ROOT/wiz-aws.sh" ] || skip "wiz-aws.sh not built yet"
  grep -q '%\.2f' "$ROOT/wiz-aws.sh"
}

# --- wiz-gcp.sh -------------------------------------------------------------
# reference/cloud/gcp/resource-count-gcp-v2.py:220-221,1092,1098
# reference/defend/gcp/log-volume-estimation-gcp.py:55,617

@test "wiz-gcp.sh CSV contract" {
  [ -f "$ROOT/wiz-gcp.sh" ] || skip "wiz-gcp.sh not built yet"
  contract wiz-gcp.sh
  require_line "gcp-resources.csv${TAB}Resource Type,Resource Count"
  require_line "gcp-resources-log.csv${TAB}Resource Type,Resource Count,Project,Region"
  require_line "gcp-defend-log-volume-YYYYMMDD-HHMMSS.csv${TAB}Log Source Type,Billable Category,Specific Metric,Resource/Scope Details,Estimated 30-Day Uncompressed Volume (GB)"
}

@test "wiz-gcp.sh Defend GB values use %.2f" {
  [ -f "$ROOT/wiz-gcp.sh" ] || skip "wiz-gcp.sh not built yet"
  grep -q '%\.2f' "$ROOT/wiz-gcp.sh"
}

# --- wiz-code.sh ------------------------------------------------------------
# reference/code/github/active-developer-count-github.py:457,466,468
# reference/code/gitlab/active-developer-count-gitlab.py:486,494,497
# reference/code/hcp-terraform/active-developer-count-hcp.py:71,373

@test "wiz-code.sh CSV contract" {
  [ -f "$ROOT/wiz-code.sh" ] || skip "wiz-code.sh not built yet"
  contract wiz-code.sh
  require_line "github-developers.txt${TAB}(no header; one hashed developer email per line)"
  require_line "github-developers-log.txt${TAB}Organization,Repository,Developers (Last 90 Days)"
  require_line "gitlab-developers.txt${TAB}(no header; one hashed developer email per line)"
  require_line "gitlab-developers-log.txt${TAB}Group,Project,Developers (Last 90 Days)"
  require_line "hcpt-developers.txt${TAB}(no header; one hashed developer email per line)"
  require_line "active-developers.txt${TAB}(no header; deduplicated hashed developer emails across *-developers.txt)"
}
