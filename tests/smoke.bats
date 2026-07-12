#!/usr/bin/env bats
# No-creds smoke gate — every shipped script must be drivable with NO cloud
# session at all. We go further than "no credentials": az/aws/gcloud/kubectl
# are stubbed to exit 127, so any help/list/dry-run/menu path that shells out
# to a cloud CLI fails loudly here instead of silently needing one in CI.
#
# Scripts that are not built yet are skipped (phases land one at a time).

setup() {
  ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  STUB="$BATS_TEST_TMPDIR/stub-bin"
  mkdir -p "$STUB"
  for cli in az aws gcloud kubectl pwsh; do
    printf '#!/usr/bin/env bash\necho "%s invoked during a no-session smoke test" >&2\nexit 127\n' "$cli" > "$STUB/$cli"
    chmod +x "$STUB/$cli"
  done
  export PATH="$STUB:$PATH"
  cd "$BATS_TEST_TMPDIR"
}

# Every script × { --help, --list } must exit 0 and print substance.
# --dry-run (default mode) must exit 0 and print the calls it would make.
# The no-arg interactive menu must render and exit cleanly on 'q'.

check_help()   { run bash "$ROOT/$1" --help;  [ "$status" -eq 0 ]; [[ "$output" == *Usage* || "$output" == *USAGE* ]]; }
check_list()   { run bash "$ROOT/$1" --list;  [ "$status" -eq 0 ]; [ -n "$output" ]; }
check_menu()   { run bash "$ROOT/$1" <<< "q"; [ "$status" -eq 0 ]; }

check_dry_run() { # $1 = script, rest = args; asserts exit 0 + mentions dry run
  local script="$1"; shift
  run bash "$ROOT/$script" "$@" --dry-run
  if [ "$status" -ne 0 ]; then
    echo "--- $script $* --dry-run failed ($status) ---" >&2
    echo "$output" >&2
    return 1
  fi
  [[ "$output" == *"dry-run"* || "$output" == *"DRY RUN"* || "$output" == *"dry run"* ]]
}

# --- wiz-azure.sh -----------------------------------------------------------

@test "wiz-azure.sh --help / --list / menu without az" {
  [ -f "$ROOT/wiz-azure.sh" ] || skip "not built yet"
  check_help wiz-azure.sh
  check_list wiz-azure.sh
  check_menu wiz-azure.sh
}

@test "wiz-azure.sh dry-runs every documented mode without az" {
  [ -f "$ROOT/wiz-azure.sh" ] || skip "not built yet"
  check_dry_run wiz-azure.sh
  check_dry_run wiz-azure.sh all
  check_dry_run wiz-azure.sh cloud
  check_dry_run wiz-azure.sh defend
  check_dry_run wiz-azure.sh cloud --fast
  check_dry_run wiz-azure.sh all --data --images
  check_dry_run wiz-azure.sh all --resume
  check_dry_run wiz-azure.sh all --azdo
  check_dry_run wiz-azure.sh all --no-azdo
  check_dry_run wiz-azure.sh all --m365
}

@test "wiz-azure.sh rejects unknown flags" {
  [ -f "$ROOT/wiz-azure.sh" ] || skip "not built yet"
  run bash "$ROOT/wiz-azure.sh" --no-such-flag
  [ "$status" -ne 0 ]
}

# --- wiz-aws.sh -------------------------------------------------------------

@test "wiz-aws.sh --help / --list / menu without aws" {
  [ -f "$ROOT/wiz-aws.sh" ] || skip "not built yet"
  check_help wiz-aws.sh
  check_list wiz-aws.sh
  check_menu wiz-aws.sh
}

@test "wiz-aws.sh dry-runs every documented mode without aws" {
  [ -f "$ROOT/wiz-aws.sh" ] || skip "not built yet"
  check_dry_run wiz-aws.sh
  check_dry_run wiz-aws.sh all
  check_dry_run wiz-aws.sh cloud
  check_dry_run wiz-aws.sh defend
  check_dry_run wiz-aws.sh cloud --fast
  check_dry_run wiz-aws.sh all --data --images
  check_dry_run wiz-aws.sh all --resume
  check_dry_run wiz-aws.sh all --org
  check_dry_run wiz-aws.sh all --org --role-name CustomRole
  check_dry_run wiz-aws.sh defend --defend-detailed
  check_dry_run wiz-aws.sh defend --defend-cloudtrail-bucket my-bucket
}

@test "wiz-aws.sh rejects unknown flags" {
  [ -f "$ROOT/wiz-aws.sh" ] || skip "not built yet"
  run bash "$ROOT/wiz-aws.sh" --no-such-flag
  [ "$status" -ne 0 ]
}

# --- wiz-gcp.sh -------------------------------------------------------------

@test "wiz-gcp.sh --help / --list / menu without gcloud" {
  [ -f "$ROOT/wiz-gcp.sh" ] || skip "not built yet"
  check_help wiz-gcp.sh
  check_list wiz-gcp.sh
  check_menu wiz-gcp.sh
}

@test "wiz-gcp.sh dry-runs every documented mode without gcloud" {
  [ -f "$ROOT/wiz-gcp.sh" ] || skip "not built yet"
  check_dry_run wiz-gcp.sh
  check_dry_run wiz-gcp.sh all
  check_dry_run wiz-gcp.sh cloud
  check_dry_run wiz-gcp.sh defend
  check_dry_run wiz-gcp.sh cloud --fast
  check_dry_run wiz-gcp.sh all --data --images
  check_dry_run wiz-gcp.sh all --resume
  check_dry_run wiz-gcp.sh all --org 123456789012
  check_dry_run wiz-gcp.sh all --projects proj-a,proj-b
}

@test "wiz-gcp.sh rejects unknown flags" {
  [ -f "$ROOT/wiz-gcp.sh" ] || skip "not built yet"
  run bash "$ROOT/wiz-gcp.sh" --no-such-flag
  [ "$status" -ne 0 ]
}

# --- wiz-code.sh ------------------------------------------------------------

@test "wiz-code.sh --help / --list / menu without tokens" {
  [ -f "$ROOT/wiz-code.sh" ] || skip "not built yet"
  check_help wiz-code.sh
  check_list wiz-code.sh
  check_menu wiz-code.sh
}

@test "wiz-code.sh dry-runs all three providers with no token" {
  [ -f "$ROOT/wiz-code.sh" ] || skip "not built yet"
  unset GITHUB_TOKEN GITLAB_TOKEN HCP_TOKEN
  check_dry_run wiz-code.sh github
  check_dry_run wiz-code.sh gitlab
  check_dry_run wiz-code.sh hcp
  check_dry_run wiz-code.sh all
}

@test "wiz-code.sh rejects unknown flags" {
  [ -f "$ROOT/wiz-code.sh" ] || skip "not built yet"
  run bash "$ROOT/wiz-code.sh" --no-such-flag
  [ "$status" -ne 0 ]
}

# --- cross-cutting ----------------------------------------------------------

@test "all shipped scripts pass shellcheck" {
  command -v shellcheck >/dev/null || skip "shellcheck not installed"
  local found=0 script
  for script in "$ROOT"/wiz-*.sh; do
    [ -f "$script" ] || continue
    found=1
    shellcheck "$script"
  done
  [ "$found" -eq 1 ] || skip "no bash scripts built yet"
}
