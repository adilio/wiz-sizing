#!/usr/bin/env bash
# wiz-code.sh — Wiz Code sizing: active developer counts for GitHub, GitLab,
# and HCP Terraform.
#
#   bash <(curl -sL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-code.sh)
#
# Requires bash 4+, jq, curl. Token-based and read-only: reuses GITHUB_TOKEN /
# GITLAB_TOKEN / HCP_TOKEN, or prompts (input masked). Counting logic
# reproduces the official Wiz active-developer scripts (see reference/ and
# parity/mapping.md in the repo); output filenames and headers are identical.
# Developer emails are sha256-hashed on disk unless --decrypt is given.
#
# This is the opt-in code-sizing domain (PLAN §5) — deliberately separate from
# the per-CSP cloud scripts. Azure DevOps counting lives in wiz-azure.sh.

set -uo pipefail

if (( BASH_VERSINFO[0] < 4 )); then
  echo "wiz-code.sh needs bash 4+ (cloud shells have it; on macOS use 'brew install bash')." >&2
  exit 1
fi

VERSION='1.0.0'

####
# Defaults and globals
####

MODE=''                 # github | gitlab | hcp | all
DAYS=90
DECRYPT=0
DRY_RUN=0
QUIET=0
OUTPUT_DIR='.'
GH_ORG=''
GH_REPO=''
GH_URL='https://api.github.com'
GL_GROUP=''
GL_PROJECT=''
GL_URL='https://gitlab.com'
HCP_URL='https://app.terraform.io/api/v2'

GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITLAB_TOKEN="${GITLAB_TOKEN:-}"
HCP_TOKEN="${HCP_TOKEN:-}"

RUN_STARTED_AT=$SECONDS
TMP_DIR=''
ERRORS_F=''

####
# Usage / list / contract
####

usage() {
  cat <<EOF
Usage: wiz-code.sh [PROVIDER] [flags]

Count active developers (distinct commit authors / run creators in the last
N days) for Wiz Code sizing. Token-based, read-only.

Providers:
  github              GitHub organization or user repositories
  gitlab              GitLab group or membership projects
  hcp                 HCP Terraform organizations
  all                 All three (providers without a token are skipped)

Tokens (reused from the environment, otherwise prompted with masked input):
  GITHUB_TOKEN        repo metadata + commits read (classic: repo; fine-grained:
                      Contents+Metadata read; read:org improves accuracy)
  GITLAB_TOKEN        read_api
  HCP_TOKEN           user or team API token

Flags:
  --days N            Count developers active in the last N days (default: 90)
  --org ORG           GitHub: organization (default: the token's repositories)
  --repo REPO         GitHub: a single repository
  --github-url URL    GitHub Enterprise API base (default: https://api.github.com)
  --group GROUP       GitLab: group (includes subgroups)
  --project PROJECT   GitLab: a single project
  --gitlab-url URL    Self-managed GitLab base (default: https://gitlab.com)
  --decrypt           Write developer emails in plaintext (default: sha256)
  --output-dir DIR    Directory for output files (default: current directory)
  --dry-run           Print the API calls this run would make, then exit.
                      Needs no token.
  --quiet             Suppress progress output
  --list              List providers
  --version           Print version
  --help              This help

Output files (identical to the official Wiz scripts):
  github<-org><-repo>-developers.txt + github...-developers-log.txt
  gitlab<-group><-project>-developers.txt + gitlab...-developers-log.txt
  hcpt-developers.txt
  active-developers.txt          (deduplicated union across *-developers.txt)

Run with no arguments for an interactive menu.
EOF
}

list_modes() {
  cat <<EOF
Providers:
  github   Active developers across GitHub repositories
  gitlab   Active developers across GitLab projects
  hcp      Active developers across HCP Terraform organizations
  all      All three in one pass (skips providers without a token)
EOF
}

print_csv_contract() {
  # filename<TAB>header — pinned by tests/contract.bats against reference/.
  printf 'github-developers.txt\t(no header; one hashed developer email per line)\n'
  printf 'github-developers-log.txt\tOrganization,Repository,Developers (Last %s Days)\n' "$DAYS"
  printf 'gitlab-developers.txt\t(no header; one hashed developer email per line)\n'
  printf 'gitlab-developers-log.txt\tGroup,Project,Developers (Last %s Days)\n' "$DAYS"
  printf 'hcpt-developers.txt\t(no header; one hashed developer email per line)\n'
  printf 'active-developers.txt\t(no header; deduplicated hashed developer emails across *-developers.txt)\n'
}

####
# Small utilities
####

elapsed() {
  local secs=$(( SECONDS - RUN_STARTED_AT )) h m s
  h=$(( secs / 3600 )); m=$(( (secs % 3600) / 60 )); s=$(( secs % 60 ))
  if (( h )); then printf '%02d:%02d:%02d' "$h" "$m" "$s"; else printf '%02d:%02d' "$m" "$s"; fi
}

status() {
  (( QUIET )) && return 0
  printf '+%s %s\n' "$(elapsed)" "$*" >&2
}

err() {
  printf 'ERROR: %s\n' "$*" >&2
  [[ -n "$ERRORS_F" ]] && printf 'ERROR: %s\n' "$*" >> "$ERRORS_F"
}

csv_field() {
  local f="$1"
  if [[ "$f" == *[\",]* ]]; then
    f=${f//\"/\"\"}
    printf '"%s"' "$f"
  else
    printf '%s' "$f"
  fi
}

csv_row() {
  local out='' f first=1
  for f in "$@"; do
    if (( first )); then out=$(csv_field "$f"); first=0
    else out+=","$(csv_field "$f"); fi
  done
  printf '%s\n' "$out"
}

utc_days_ago_iso() {
  local out
  if out=$(date -u -d "$1 days ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null); then
    printf '%s' "$out"
  else
    date -u -v-"$1"d +%Y-%m-%dT%H:%M:%SZ
  fi
}

sha256_hex() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  else
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  fi
}

slugify() { # official slugify: -<alnum-only> per non-empty part (github.py:179-186)
  local out='' part
  for part in "$@"; do
    [[ -n "$part" ]] || continue
    out+="-${part//[^[:alnum:]]/}"
  done
  printf '%s' "$out"
}

urlencode() { jq -rn --arg v "$1" '$v | @uri'; }

require_tools() {
  local missing=0 t
  for t in jq curl; do
    if ! command -v "$t" >/dev/null 2>&1; then
      echo "ERROR: '$t' not found." >&2
      missing=1
    fi
  done
  (( missing )) && exit 1
  return 0
}

prompt_token() { # $1 label, $2 env var name → token on stdout ('' if declined)
  local current="${!2:-}"
  if [[ -n "$current" ]]; then
    status "$1: using token from \$$2"
    printf '%s' "$current"
    return 0
  fi
  local token=''
  if [[ -t 0 ]]; then
    read -r -s -p "$1 token (or set \$$2; Enter to skip): " token >&2 || token=''
    echo >&2
  fi
  printf '%s' "$token"
}

# Write a developer file: hashed (default) or plaintext with --decrypt
write_developer_file() { # $1 out path, $2 input file (one email/key per line)
  local out="$1" input="$2" line
  : > "$out"
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    if (( DECRYPT )); then
      printf '%s\n' "$line" >> "$out"
    else
      sha256_hex "$line" >> "$out"
    fi
  done < <(sort -u "$input")
}

# Cross-VCS rollup — union of *-developers.txt, re-hashed like the officials
write_rollup() {
  local rollup="$OUTPUT_DIR/active-developers.txt" f line
  : > "$TMP_DIR/rollup.in"
  for f in "$OUTPUT_DIR"/*-developers.txt; do
    [[ -f "$f" && "$(basename "$f")" != 'active-developers.txt' ]] || continue
    cat "$f" >> "$TMP_DIR/rollup.in"
  done
  [[ -s "$TMP_DIR/rollup.in" ]] || return 0
  : > "$rollup"
  local total=0
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    if (( DECRYPT )); then
      printf '%s\n' "$line" >> "$rollup"
    else
      sha256_hex "$line" >> "$rollup"
    fi
    total=$(( total + 1 ))
  done < <(sort -u "$TMP_DIR/rollup.in")
  echo
  echo "- $total Total Developers across all Version Control Systems scanned in this directory"
  echo "To reset the Total Developers count, delete all of the '*-developers.txt' files in this directory"
}

####
# HTTP — GET with retries; provider-specific auth headers
####

http_get() { # $1 url, $2.. extra curl args (headers) → body
  local url="$1"; shift
  local attempt resp code payload
  for attempt in 1 2 3 4 5; do
    resp=$(curl -sS "$@" -w $'\n%{http_code}' "$url" 2>/dev/null) || resp=$'\n000'
    code=${resp##*$'\n'}
    payload=${resp%$'\n'*}
    case "$code" in
      2*) printf '%s' "$payload"; return 0 ;;
      429|5*|000) sleep $(( attempt * attempt )) ;;
      *)
        err "HTTP $code from $url: $(head -c 200 <<<"$payload" | tr '\n' ' ')"
        return 1 ;;
    esac
  done
  err "HTTP retries exhausted for $url"
  return 1
}

####
# Dry-run
####

dry_run_plan() {
  echo "wiz-code.sh v$VERSION — dry-run: the calls this run would make (none are made now)."
  echo "Window: developers active in the last $DAYS days."
  echo
  if [[ "$MODE" == github || "$MODE" == all ]]; then
    echo "GitHub ($GH_URL; token from \$GITHUB_TOKEN or masked prompt):"
    if [[ -n "$GH_ORG" ]]; then
      echo "  GET /orgs/$GH_ORG/repos?type=all&sort=full_name        # paged"
    else
      echo '  GET /user/repos?type=all&sort=full_name               # paged'
    fi
    [[ -n "$GH_REPO" ]] && echo "  (limited to repository: $GH_REPO)"
    echo '  GET /repos/{repo}/collaborators                        # membership check (optional)'
    echo "  GET /repos/{repo}/commits?since=<${DAYS}d ago>            # paged; distinct authors"
    echo '  Emails: single → as-is; multiple → drop users.noreply, keep most-active'
    echo
  fi
  if [[ "$MODE" == gitlab || "$MODE" == all ]]; then
    echo "GitLab ($GL_URL; token from \$GITLAB_TOKEN or masked prompt):"
    if [[ -n "$GL_GROUP" ]]; then
      echo "  GET /api/v4/groups?search=$GL_GROUP ; /groups/{id}/projects?include_subgroups=true"
    elif [[ -n "$GL_PROJECT" ]]; then
      echo "  GET /api/v4/projects?search=$GL_PROJECT"
    else
      echo '  GET /api/v4/projects?membership=true&archived=false    # paged'
    fi
    echo '  GET /api/v4/projects/{id}/members/all                  # active-member check'
    echo "  GET /api/v4/projects/{id}/repository/commits?since=<${DAYS}d ago>"
    echo
  fi
  if [[ "$MODE" == hcp || "$MODE" == all ]]; then
    echo "HCP Terraform ($HCP_URL; token from \$HCP_TOKEN or masked prompt):"
    echo '  GET /organizations ; /organization-memberships ; /workspaces'
    echo '  GET /workspaces/{id}/runs + /organizations/{org}/runs'
    echo '      filter[source]=tfe-ui,tfe-api,tfe-configuration-version&filter[timeframe]=year'
    echo '  GET /users/{id}                                        # skip service accounts'
    echo '  GET /configuration-versions/{id}/ingress-attributes    # VCS committer'
    echo
  fi
  echo "Output: *-developers.txt (sha256-hashed unless --decrypt), per-provider -log.txt, active-developers.txt in $OUTPUT_DIR"
  echo 'dry-run complete — no API calls were made.'
}

####
# GitHub (port of active-developer-count-github.py)
####

gh_get() { http_get "$1" -H "Authorization: Bearer $GITHUB_TOKEN" -H 'Accept: application/vnd.github+json'; }

gh_get_paged() { # $1 base url (with query, no page param) → combined JSON array
  local url="$1" sep page out='[]' n=1 count
  [[ "$url" == *\?* ]] && sep='&' || sep='?'
  while :; do
    page=$(gh_get "${url}${sep}per_page=100&page=$n") || break
    count=$(jq 'length' <<<"$page" 2>/dev/null) || break
    out=$(jq -c --argjson acc "$out" '$acc + .' <<<"$page")
    (( count < 100 )) && break
    n=$(( n + 1 ))
  done
  printf '%s' "$out"
}

run_github() {
  status 'GitHub: counting active developers'
  local since devs_all="$TMP_DIR/gh.devs" log_rows="$TMP_DIR/gh.log"
  since=$(utc_days_ago_iso "$DAYS")
  : > "$devs_all"; : > "$log_rows"

  # Repositories (github.py:296-328)
  local repos
  if [[ -n "$GH_ORG" && -n "$GH_REPO" ]]; then
    repos=$(gh_get "$GH_URL/repos/$GH_ORG/$GH_REPO" | jq -c '[ . ]')
  elif [[ -n "$GH_ORG" ]]; then
    repos=$(gh_get_paged "$GH_URL/orgs/$GH_ORG/repos?type=all&sort=full_name")
    [[ "$repos" == '[]' ]] && repos=$(gh_get_paged "$GH_URL/users/$GH_ORG/repos?sort=full_name")
  else
    repos=$(gh_get_paged "$GH_URL/user/repos?type=all&sort=full_name")
  fi
  local repo_count
  repo_count=$(jq 'length' <<<"$repos")
  status "GitHub: $repo_count repositories"

  local full_name private
  while IFS=$'\t' read -r full_name private; do
    [[ -n "$full_name" ]] || continue
    local vis=Public
    [[ "$private" == true ]] && vis=Private
    status "Found $vis Repository: $full_name"

    # Collaborators — org-membership gate when readable (github.py:354-386)
    local collab_ids org_access=1
    if ! collab_ids=$(gh_get "$GH_URL/repos/$full_name/collaborators?per_page=100" | jq -c '[ .[].id ]' 2>/dev/null) \
       || [[ -z "$collab_ids" || "$collab_ids" == '[]' ]]; then
      org_access=0
      collab_ids='[]'
      status '    Unable to get Collaborators — not checking Developers for Organization Membership.'
    fi

    # Commits since the window start; group by author id (github.py:388-445)
    local commits
    commits=$(gh_get_paged "$GH_URL/repos/$full_name/commits?since=$since")
    # Per developer (author id): pick the export email with the official rule —
    # one email → itself; several → drop users.noreply unless nothing is left,
    # then the most-commits email.
    local dev_emails dev_count
    dev_emails=$(jq -r --argjson collabs "$collab_ids" --argjson gate "$org_access" '
      [ .[]
        | select(.author.id != null)
        | select(.commit.author.email != null)
        | select($gate == 0 or (.author.id as $id | $collabs | index($id) != null))
        | { id: .author.id, email: (.commit.author.email | gsub("^\""; "") | gsub("\"$"; "")) }
      ]
      | group_by(.id)
      | map(
          ( group_by(.email) | map({ email: .[0].email, n: length }) ) as $emails
          | if ($emails | length) == 1 then $emails[0].email
            else
              ( [ $emails[] | select(.email | contains("users.noreply") | not) ] ) as $filtered
              | (if ($filtered | length) > 0 then $filtered else $emails end)
              | max_by(.n) | .email
            end
        )
      | .[]' <<<"$commits")
    dev_count=$(grep -c . <<<"$dev_emails" || true)
    [[ -n "$dev_emails" ]] && printf '%s\n' "$dev_emails" >> "$devs_all"
    csv_row "$GH_ORG" "$full_name" "$dev_count" >> "$log_rows"
    (( dev_count > 0 )) && status "    Total $dev_count Developers in Repository: $full_name"
  done < <(jq -r '.[] | [ .full_name, (.private | tostring) ] | @tsv' <<<"$repos")

  local slug
  slug=$(slugify "$GH_ORG" "$GH_REPO")
  write_developer_file "$OUTPUT_DIR/github${slug}-developers.txt" "$devs_all"
  {
    csv_row 'Organization' 'Repository' "Developers (Last $DAYS Days)"
    cat "$log_rows"
  } > "$OUTPUT_DIR/github${slug}-developers-log.txt"
  echo "GitHub: $(sort -u "$devs_all" | grep -c . || true) developers → github${slug}-developers.txt"
}

####
# GitLab (port of active-developer-count-gitlab.py)
####

gl_get() { http_get "$1" -H "PRIVATE-TOKEN: $GITLAB_TOKEN"; }

gl_get_paged() {
  local url="$1" sep page out='[]' n=1 count
  [[ "$url" == *\?* ]] && sep='&' || sep='?'
  while :; do
    page=$(gl_get "${url}${sep}per_page=100&page=$n") || break
    count=$(jq 'length' <<<"$page" 2>/dev/null) || break
    out=$(jq -c --argjson acc "$out" '$acc + .' <<<"$page")
    (( count < 100 )) && break
    n=$(( n + 1 ))
  done
  printf '%s' "$out"
}

run_gitlab() {
  status 'GitLab: counting active developers'
  local since devs_all="$TMP_DIR/gl.devs" log_rows="$TMP_DIR/gl.log"
  since=$(utc_days_ago_iso "$DAYS")
  : > "$devs_all"; : > "$log_rows"

  # Projects (gitlab.py:300-373)
  local projects
  if [[ -n "$GL_GROUP" ]]; then
    local group_id
    group_id=$(gl_get "$GL_URL/api/v4/groups?search=$(urlencode "$GL_GROUP")&all_available=true&per_page=1" \
      | jq -r '.[0].id // empty')
    if [[ -z "$group_id" ]]; then
      err "GitLab: group not found: $GL_GROUP"
      return 1
    fi
    projects=$(gl_get_paged "$GL_URL/api/v4/groups/$group_id/projects?archived=false&include_subgroups=true&order_by=path&sort=asc")
  elif [[ -n "$GL_PROJECT" ]]; then
    projects=$(gl_get "$GL_URL/api/v4/projects?search=$(urlencode "$GL_PROJECT")&archived=false&order_by=path&sort=asc&per_page=1")
  else
    projects=$(gl_get_paged "$GL_URL/api/v4/projects?archived=false&membership=true&order_by=path&sort=asc")
  fi
  status "GitLab: $(jq 'length' <<<"$projects") projects"

  local proj_id path vis
  while IFS=$'\t' read -r proj_id path vis; do
    [[ -n "$proj_id" ]] || continue
    status "Found ${vis^} Project: $path ($proj_id)"

    # Active project members, keyed by display name (gitlab.py:390-405,469-476)
    local members commits dev_emails dev_count
    members=$(gl_get_paged "$GL_URL/api/v4/projects/$proj_id/members/all" \
      | jq -c '[ .[] | { name, state } ]')
    commits=$(gl_get_paged "$GL_URL/api/v4/projects/$proj_id/repository/commits?since=$since")
    dev_emails=$(jq -r --argjson members "$members" '
      [ .[]
        | select(.committer_name != null and .committer_email != null)
        | .committer_name as $n
        | select([ $members[] | select(.name == $n and .state == "active") ] | length > 0)
        | (.committer_email | gsub("^\""; "") | gsub("\"$"; ""))
      ] | unique | .[]' <<<"$commits")
    dev_count=$(grep -c . <<<"$dev_emails" || true)
    [[ -n "$dev_emails" ]] && printf '%s\n' "$dev_emails" >> "$devs_all"
    csv_row "$GL_GROUP" "$path" "$dev_count" >> "$log_rows"
    (( dev_count > 0 )) && status "    Total $dev_count Developers in Project: $path"
  done < <(jq -r '.[] | [ (.id | tostring), .path_with_namespace, (.visibility // "private") ] | @tsv' <<<"$projects")

  local slug
  slug=$(slugify "$GL_GROUP" "$GL_PROJECT")
  write_developer_file "$OUTPUT_DIR/gitlab${slug}-developers.txt" "$devs_all"
  {
    csv_row 'Group' 'Project' "Developers (Last $DAYS Days)"
    cat "$log_rows"
  } > "$OUTPUT_DIR/gitlab${slug}-developers-log.txt"
  echo "GitLab: $(sort -u "$devs_all" | grep -c . || true) developers → gitlab${slug}-developers.txt"
}

####
# HCP Terraform (port of active-developer-count-hcp.py)
####

hcp_get() { http_get "$1" -H "Authorization: Bearer $HCP_TOKEN" -H 'Content-Type: application/vnd.api+json'; }

hcp_get_paged() { # JSON:API links.next pagination → combined .data array
  local url="$1" page out='[]' next
  next="$url"
  while [[ -n "$next" && "$next" != null ]]; do
    page=$(hcp_get "$next") || break
    out=$(jq -c --argjson acc "$out" '$acc + (.data // [])' <<<"$page")
    next=$(jq -r '.links.next // empty' <<<"$page")
  done
  printf '%s' "$out"
}

run_hcp() {
  status 'HCP Terraform: counting active developers'
  local since devs_all="$TMP_DIR/hcp.devs" runs_seen="$TMP_DIR/hcp.runs"
  since=$(utc_days_ago_iso "$DAYS")
  : > "$devs_all"; : > "$runs_seen"

  # Caches shared across runs, like the official's dicts (hcp.py:398-410)
  declare -A user_kind=()      # user id → developer|service
  declare -A member_email=()   # user id → org membership email

  local run_filter='filter%5Bsource%5D=tfe-ui%2Ctfe-api%2Ctfe-configuration-version&filter%5Btimeframe%5D=year'

  process_runs() { # $1 = runs JSON array, $2 = context label
    local runs="$1" label="$2"
    # Empty fields are emitted as '-' because bash collapses consecutive tabs
    # when splitting (tab is IFS whitespace), which would shift the columns.
    local run_id created source created_by_id cv_id
    while IFS=$'\t' read -r run_id created source created_by_id cv_id; do
      [[ -n "$run_id" ]] || continue
      [[ "$created_by_id" == - ]] && created_by_id=''
      [[ "$cv_id" == - ]] && cv_id=''
      grep -q "^$run_id\$" "$runs_seen" && continue
      echo "$run_id" >> "$runs_seen"
      [[ "$created" < "$since" ]] && continue
      case "$source" in
        tfe-ui|'tfe-ui,tfe-api')
          [[ -n "$created_by_id" ]] || continue
          if [[ -z "${user_kind[$created_by_id]:-}" ]]; then
            local user is_sa
            user=$(hcp_get "$HCP_URL/users/$created_by_id") || continue
            is_sa=$(jq -r '.data.attributes["is-service-account"] // false' <<<"$user")
            if [[ "$is_sa" == true ]]; then user_kind[$created_by_id]=service
            else user_kind[$created_by_id]=developer; fi
          fi
          [[ "${user_kind[$created_by_id]}" == service ]] && continue
          # Developer key: org-membership email when known, else the user id
          # (hcp.py:349-355)
          printf '%s\n' "${member_email[$created_by_id]:-$created_by_id}" >> "$devs_all"
          status "        $label Run: $run_id by user ${member_email[$created_by_id]:-$created_by_id}"
          ;;
        tfe-configuration-version)
          [[ -n "$cv_id" ]] || continue
          local sender
          sender=$(hcp_get "$HCP_URL/configuration-versions/$cv_id/ingress-attributes" \
            | jq -r '.data.attributes["sender-username"] // empty') || sender=''
          if [[ -n "$sender" ]]; then
            printf '%s\n' "$sender" >> "$devs_all"
            status "        $label Run: $run_id by committer $sender"
          fi
          ;;
      esac
    done < <(jq -r '.[] | [
        .id,
        (.attributes["created-at"] // "-"),
        (.attributes.source // "-"),
        (if (.relationships["created-by"].data.type // "") == "users"
           then .relationships["created-by"].data.id else "-" end),
        (.relationships["configuration-version"].data.id // "-")
      ] | @tsv' <<<"$runs")
  }

  local orgs org_id org_name
  orgs=$(hcp_get_paged "$HCP_URL/organizations")
  status "HCP: $(jq 'length' <<<"$orgs") organizations"
  while IFS=$'\t' read -r org_id org_name; do
    [[ -n "$org_id" ]] || continue
    status "Organization: $org_name"

    # Memberships → user id → email map (hcp.py:434-441)
    local memberships uid email
    memberships=$(hcp_get_paged "$HCP_URL/organizations/$org_id/organization-memberships")
    while IFS=$'\t' read -r uid email; do
      [[ -n "$uid" ]] && member_email[$uid]="$email"
    done < <(jq -r '.[] | [ (.relationships.user.data.id // ""), (.attributes.email // "") ] | @tsv' <<<"$memberships")

    # Workspace-level runs, then organization-level runs (hcp.py:443-457)
    local workspaces ws_id runs
    workspaces=$(hcp_get_paged "$HCP_URL/organizations/$org_id/workspaces")
    while IFS= read -r ws_id; do
      [[ -n "$ws_id" ]] || continue
      runs=$(hcp_get_paged "$HCP_URL/workspaces/$ws_id/runs?$run_filter")
      process_runs "$runs" 'Workspace'
    done < <(jq -r '.[].id' <<<"$workspaces")

    runs=$(hcp_get_paged "$HCP_URL/organizations/$org_id/runs?$run_filter")
    process_runs "$runs" 'Organization'
  done < <(jq -r '.[] | [ .id, (.attributes.name // .id) ] | @tsv' <<<"$orgs")

  write_developer_file "$OUTPUT_DIR/hcpt-developers.txt" "$devs_all"
  echo "HCP Terraform: $(sort -u "$devs_all" | grep -c . || true) developers → hcpt-developers.txt"
}

####
# Interactive menu (§4)
####

menu() {
  cat <<EOF

wiz-code.sh v$VERSION — Wiz Code sizing (active developers)

  1) All providers      GitHub + GitLab + HCP Terraform (skips missing tokens)
  2) GitHub
  3) GitLab
  4) HCP Terraform
  q) Quit

EOF
  local choice
  read -r -p 'Select: ' choice || choice=q
  case "$choice" in
    1) MODE=all ;;
    2) MODE=github ;;
    3) MODE=gitlab ;;
    4) MODE=hcp ;;
    q|Q|'') echo 'Bye.'; exit 0 ;;
    *) echo "Unknown selection: $choice"; exit 2 ;;
  esac
}

####
# Argument parsing and main
####

main() {
  local had_args=$#

  while [[ $# -gt 0 ]]; do
    case "$1" in
      github|gitlab|hcp|all) MODE="$1"; shift ;;
      --days) DAYS="${2:?--days needs a value}"; shift 2 ;;
      --org) GH_ORG="${2:?--org needs a value}"; shift 2 ;;
      --repo) GH_REPO="${2:?--repo needs a value}"; shift 2 ;;
      --github-url) GH_URL="${2:?--github-url needs a value}"; shift 2 ;;
      --group) GL_GROUP="${2:?--group needs a value}"; shift 2 ;;
      --project) GL_PROJECT="${2:?--project needs a value}"; shift 2 ;;
      --gitlab-url) GL_URL="${2:?--gitlab-url needs a value}"; shift 2 ;;
      --token)
        # Applies to the single selected provider; kept for parity with the
        # official scripts' --token.
        case "$MODE" in
          github) GITHUB_TOKEN="${2:?--token needs a value}" ;;
          gitlab) GITLAB_TOKEN="${2:?--token needs a value}" ;;
          hcp)    HCP_TOKEN="${2:?--token needs a value}" ;;
          *) echo '--token needs a provider first (e.g. wiz-code.sh github --token ...)' >&2; exit 2 ;;
        esac
        shift 2 ;;
      --decrypt) DECRYPT=1; shift ;;
      --output-dir) OUTPUT_DIR="${2:?--output-dir needs a value}"; shift 2 ;;
      --dry-run) DRY_RUN=1; shift ;;
      --quiet) QUIET=1; shift ;;
      --print-csv-contract) print_csv_contract; exit 0 ;;
      --list) list_modes; exit 0 ;;
      --version) echo "wiz-code.sh $VERSION"; exit 0 ;;
      --help|-h) usage; exit 0 ;;
      *) echo "Unknown argument: $1 (see --help)" >&2; exit 2 ;;
    esac
  done

  if (( had_args == 0 )); then
    menu
  fi
  [[ -z "$MODE" ]] && MODE=all

  if (( DRY_RUN )); then
    dry_run_plan
    exit 0
  fi

  require_tools
  mkdir -p "$OUTPUT_DIR"
  TMP_DIR=$(mktemp -d)
  ERRORS_F="$TMP_DIR/errors"
  touch "$ERRORS_F"
  trap 'rm -rf "$TMP_DIR"' EXIT

  local ran=0
  if [[ "$MODE" == github || "$MODE" == all ]]; then
    GITHUB_TOKEN=$(prompt_token 'GitHub' GITHUB_TOKEN)
    if [[ -n "$GITHUB_TOKEN" ]]; then run_github; ran=1
    else status 'GitHub: no token — skipped'; fi
  fi
  if [[ "$MODE" == gitlab || "$MODE" == all ]]; then
    GITLAB_TOKEN=$(prompt_token 'GitLab' GITLAB_TOKEN)
    if [[ -n "$GITLAB_TOKEN" ]]; then run_gitlab; ran=1
    else status 'GitLab: no token — skipped'; fi
  fi
  if [[ "$MODE" == hcp || "$MODE" == all ]]; then
    HCP_TOKEN=$(prompt_token 'HCP Terraform' HCP_TOKEN)
    if [[ -n "$HCP_TOKEN" ]]; then run_hcp; ran=1
    else status 'HCP Terraform: no token — skipped'; fi
  fi

  if (( ! ran )); then
    echo 'No provider had a token. Set GITHUB_TOKEN / GITLAB_TOKEN / HCP_TOKEN or rerun interactively.' >&2
    exit 1
  fi

  write_rollup
  if [[ -s "$ERRORS_F" ]]; then
    sort -u "$ERRORS_F" > "$OUTPUT_DIR/code-errors-log.txt"
    echo "Errors logged to code-errors-log.txt"
  fi
  status 'Scan complete.'
}

main "$@"
