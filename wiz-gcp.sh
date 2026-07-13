#!/usr/bin/env bash
# wiz-gcp.sh — Wiz sizing for GCP: cloud resources + Defend ingest in one pass.
#
#   bash <(curl -sL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-gcp.sh)
#
# Requires only what Google Cloud Shell ships: bash 4+, gcloud (logged in), jq,
# curl. Counting logic reproduces the official Wiz sizing scripts (see
# reference/ and parity/mapping.md in the repo); output CSV filenames and
# headers are identical.
#
# Modes:   all (default) · cloud · defend
# Scope:   all listable ACTIVE projects by default; --projects / --org narrow it
#
# Everything is read-only.

set -uo pipefail

if (( BASH_VERSINFO[0] < 4 )); then
  echo "wiz-gcp.sh needs bash 4+ (Google Cloud Shell has it; on macOS use 'brew install bash')." >&2
  exit 1
fi

VERSION='1.0.0'

####
# Defaults and globals
####

MODE=''
FAST=0
DATA=0
IMAGES=0
RESUME=0
DRY_RUN=0
QUIET=0
OUTPUT_DIR='.'
PROJECTS=''            # comma-separated project IDs; empty → all listable
ORG_ID=''              # organization ID (fast-mode org-scope CAI; defend org scan)
DEFEND_DAYS=30
USE_SINK_METRICS=0
SINK_NAME=''
NO_EXCLUSION_ADJ=0
MAX_PARALLEL=8
MAX_IMAGE_TAGS=5

OUTPUT_FILE='gcp-resources.csv'
OUTPUT_FILE_LOG='gcp-resources-log.csv'
ERROR_LOG_FILE='gcp-errors-log.txt'
DEFEND_ERROR_LOG_FILE='gcp-defend-errors-log.txt'
PADDING=6

# CSV row order — matches the official totals dict exactly
# (reference/cloud/gcp/resource-count-gcp-v2.py:249-265).
TOTAL_KEYS=(
  'Virtual Machines'
  'Container Hosts'
  'Serverless Functions'
  'Serverless Containers'
  'Data Buckets'
  'PaaS Databases'
  'Data Warehouses'
  'Non-OS Disks'
  'Registry Container Images'
  'Kubernetes Sensors'
  'Virtual Machine Sensors'
  'Serverless Container Sensors'
)

# Defend log keys → display name|billable category
# (reference/defend/gcp/log-volume-estimation-gcp.py:126-133)
defend_log_info() {
  case "$1" in
    admin_activity_non_gke)  echo 'Admin Activity Logs (Non-GKE)|Management' ;;
    gke_audit)               echo 'GKE Audit Logs|Management' ;;
    data_access_non_storage) echo 'Data Access Logs (Non-Storage)|Management' ;;
    storage_data_access)     echo 'Cloud Storage Data Access Logs|Data' ;;
    workspace_audit)         echo 'Google Workspace Audit Logs|Identity' ;;
    measured_sink)           echo 'Log Sink (Actual Volume)|Total Ingestion (Actual)' ;;
    *)                       echo 'Unknown|Management' ;;
  esac
}

# Exclusion ratios (defend-gcp:136-146)
exclusion_ratio() { # $1 log key, $2 resource type
  case "$1:$2" in
    gke_audit:k8s_cluster) echo 0.14 ;;
    gke_audit:gke_cluster) echo 0.12 ;;
    data_access_non_storage:cloud_function) echo 0.20 ;;
    data_access_non_storage:gce_instance) echo 0.10 ;;
    data_access_non_storage:*) echo 0.14 ;;
    *) echo 1.0 ;;
  esac
}

RUN_STARTED_AT=$SECONDS
STATE_FILE=''
TMP_DIR=''
ERR_SINK=''
GLOBAL_ERRORS=''

####
# Usage / list / contract
####

usage() {
  cat <<EOF
Usage: wiz-gcp.sh [MODE] [flags]

Estimate Wiz billable units for GCP. Default run counts cloud resources AND
estimates Wiz Defend log ingest, in one pass, using your existing 'gcloud'
session (read-only).

Modes:
  all                 Cloud resources + Defend ingest (default)
  cloud               Cloud resources only
  defend              Defend ingest estimate only

Scope flags:
  --projects LIST     Comma-separated project IDs (default: every ACTIVE
                      project your credentials can list)
  --org ORG_ID        Organization ID — scopes every scan (accurate, Defend)
                      to the org's projects (including folders) and enables
                      the single-call org-scope fast path (--fast)

Cloud flags:
  --fast              Fast estimate via Cloud Asset Inventory searches; falls
                      back to the accurate path per project when the API is
                      not enabled (deviations D2/D6)
  --data              Also count Data Security resources (Buckets, Cloud SQL,
                      Spanner databases, BigQuery datasets, non-OS disks)
  --images            Also count Registry Container Images (Artifact Registry)
  --max-image-tags N  Image tags counted per image (default: 5)

Defend flags:
  --days N                   Analyze the last N days of logs (default: 30)
  --use-sink-metrics         Measure actual volume from Wiz log sinks
                             (auto-discovers sinks with 'wiz' in name/destination)
  --sink-name NAME           Measure this exact sink
  --no-exclusion-adjustment  Disable the GKE / Data Access exclusion ratios

General:
  --resume            Resume an interrupted scan (per-project checkpoints)
  --output-dir DIR    Directory for output CSVs (default: current directory)
  --max-parallel N    Concurrent project scans (default: 8)
  --dry-run           Print the API calls this run would make, then exit.
                      Makes no GCP calls and needs no gcloud session.
  --quiet             Suppress progress output
  --list              List modes and opt-in extras
  --version           Print version
  --help              This help

Output files (identical to the official Wiz sizing scripts):
  gcp-resources.csv, gcp-resources-log.csv, gcp-errors-log.txt
  gcp-defend-log-volume-<timestamp>.csv, gcp-defend-errors-log.txt

Run with no arguments for an interactive menu.
EOF
}

list_modes() {
  cat <<EOF
Modes:
  all      Cloud resources + Defend ingest (default)
  cloud    Cloud resources only
  defend   Defend ingest estimate only

Opt-in extras:
  --data     Buckets, Cloud SQL, Spanner, BigQuery, non-OS disks
  --images   Artifact Registry container images
  --fast     Cloud Asset Inventory estimate (D2/D6)
  --use-sink-metrics   Measure actual Wiz sink volume instead of estimating
EOF
}

print_csv_contract() {
  # filename<TAB>header — pinned by tests/contract.bats against reference/.
  printf 'gcp-resources.csv\tResource Type,Resource Count\n'
  printf 'gcp-resources-log.csv\tResource Type,Resource Count,Project,Region\n'
  printf 'gcp-defend-log-volume-YYYYMMDD-HHMMSS.csv\tLog Source Type,Billable Category,Specific Metric,Resource/Scope Details,Estimated 30-Day Uncompressed Volume (GB)\n'
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
  local msg="ERROR: $*"
  printf '%s\n' "$msg" >&2
  if [[ -n "$ERR_SINK" ]]; then printf '%s\n' "$msg" >> "$ERR_SINK"
  elif [[ -n "$GLOBAL_ERRORS" ]]; then printf '%s\n' "$msg" >> "$GLOBAL_ERRORS"
  fi
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

utc_now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }

utc_days_ago_iso() {
  local out
  if out=$(date -u -d "$1 days ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null); then
    printf '%s' "$out"
  else
    date -u -v-"$1"d +%Y-%m-%dT%H:%M:%SZ
  fi
}

urlencode() {
  jq -rn --arg v "$1" '$v | @uri'
}

require_tools() {
  local missing=0 t
  for t in gcloud jq curl; do
    if ! command -v "$t" >/dev/null 2>&1; then
      echo "ERROR: '$t' not found. Run from Google Cloud Shell, or install it." >&2
      missing=1
    fi
  done
  (( missing )) && exit 1
  return 0
}

emit_count() { printf '%s=%s\n' "$1" "$2" >> "$3"; }

progress_count() { # $1 count, $2 label, $3 project name, $4 region, $5 log file, $6 details
  local count="$1" label="$2" proj="$3" region="$4" logf="$5" details="${6:-}"
  (( count > 0 )) || return 0
  status "- $(printf "%${PADDING}s" "$count") $label in $proj${details:+ $details}"
  csv_row "$label" "$count" "$proj" "$region" >> "$logf"
}

####
# Token — single audience, re-fetched from gcloud near expiry (PLAN §6)
####

get_token() {
  # Cached as a file under $TMP_DIR (0600): every HTTP call chain runs inside
  # $(...) subshells, so shell-variable caches never survive back to the
  # parent — the file cache does, and it is shared across parallel workers.
  local now exp token cache=''
  now=$(date +%s)
  if [[ -n "$TMP_DIR" ]]; then
    cache="$TMP_DIR/token"
    if [[ -r "$cache" ]]; then
      { IFS= read -r exp && IFS= read -r token; } < "$cache" || token=''
      if [[ -n "$token" && "$exp" =~ ^[0-9]+$ ]] && (( exp - now > 300 )); then
        printf '%s' "$token"
        return 0
      fi
    fi
  fi
  if ! token=$(gcloud auth print-access-token 2>/dev/null); then
    err "cannot acquire a token — run 'gcloud auth login' first"
    return 1
  fi
  if [[ -n "$cache" ]]; then
    ( umask 077; printf '%s\n%s\n' "$(( now + 3000 ))" "$token" > "$cache.$$" ) && mv -f "$cache.$$" "$cache"
  fi
  printf '%s' "$token"
}

####
# HTTP — GET with retries; paged aggregation over nextPageToken
####

gcp_get() { # $1 url → body
  local url="$1" attempt resp code payload token
  for attempt in 1 2 3 4 5; do
    token=$(get_token) || return 1
    resp=$(curl -sS -H "Authorization: Bearer $token" \
      -w $'\n%{http_code}' "$url" 2>/dev/null) || resp=$'\n000'
    code=${resp##*$'\n'}
    payload=${resp%$'\n'*}
    case "$code" in
      2*) printf '%s' "$payload"; return 0 ;;
      429|5*|000) sleep $(( attempt * attempt )) ;;
      *)
        err "HTTP $code from $url: $(head -c 300 <<<"$payload" | tr '\n' ' ')"
        return 1 ;;
    esac
  done
  err "HTTP retries exhausted for $url"
  return 1
}

gcp_get_paged() { # $1 base url (may contain ?), $2 jq path of the item array → combined JSON array
  local url="$1" items_path="$2" sep page out='[]' token_param=''
  [[ "$url" == *\?* ]] && sep='&' || sep='?'
  while :; do
    page=$(gcp_get "${url}${token_param}") || { printf '%s' "$out"; return 1; }
    out=$(jq -c --argjson acc "$out" "\$acc + (${items_path} // [])" <<<"$page") || { printf '%s' "$out"; return 1; }
    local next
    next=$(jq -r '.nextPageToken // empty' <<<"$page")
    [[ -z "$next" ]] && break
    token_param="${sep}pageToken=$(urlencode "$next")"
    [[ "$token_param" == "${sep}pageToken="* && "$url" != *pageToken* ]] || break
  done
  printf '%s' "$out"
}

####
# Dry-run — prints the call plan; provably no GCP calls, no session needed
####

dry_run_plan() {
  echo "wiz-gcp.sh v$VERSION — dry-run: the calls this run would make (none are made now)."
  echo
  echo 'Token: gcloud auth print-access-token (re-fetched near expiry)'
  echo
  if [[ -n "$PROJECTS" ]]; then
    echo "Scope: projects $PROJECTS (names via cloudresourcemanager v1 projects.get)"
  elif [[ -n "$ORG_ID" ]]; then
    echo "Scope: ACTIVE projects under organization $ORG_ID (org + its folder tree)"
    echo '  GET https://cloudresourcemanager.googleapis.com/v2/folders?parent=organizations/'"$ORG_ID"' (recursive)'
    echo '  GET https://cloudresourcemanager.googleapis.com/v1/projects   # filtered by parent'
  else
    echo 'Scope: every ACTIVE project the credentials can list'
    echo '  GET https://cloudresourcemanager.googleapis.com/v1/projects'
  fi
  echo
  if [[ "$MODE" != defend ]]; then
    if (( FAST )); then
      echo 'Cloud resources (fast estimate — Cloud Asset Inventory, D2/D6):'
      local scope='projects/{project}'
      [[ -n "$ORG_ID" ]] && scope="organizations/$ORG_ID (single org-wide call per type)"
      echo "  GET https://cloudasset.googleapis.com/v1/$scope:searchAllResources"
      echo '    assetTypes: compute.googleapis.com/Instance (split VMs/GKE via labels.goog-gke-node)'
      echo '    assetTypes: cloudfunctions.googleapis.com/CloudFunction; run.googleapis.com/Revision'
      (( DATA )) && echo '    assetTypes: storage.googleapis.com/Bucket; sqladmin.googleapis.com/Instance; spanner.googleapis.com/Instance; bigquery.googleapis.com/Dataset'
      (( IMAGES )) && echo '    Registry images stay pending under --fast (rerun without --fast)'
      echo '  (per-project fallback to the accurate calls below when the CAI API is not enabled)'
    else
      echo 'Cloud resources (accurate — REST per project, gated on enabled services):'
      echo '  GET https://serviceusage.googleapis.com/v1/projects/{p}/services?filter=state:ENABLED'
      echo '  GET https://compute.googleapis.com/compute/v1/projects/{p}/aggregated/instances'
      echo '    (+ disks.get / images.get per boot disk for the Linux sensor check, cached)'
      echo '  GET https://container.googleapis.com/v1/projects/{p}/locations/-/clusters   # Autopilot'
      echo '  GET https://cloudfunctions.googleapis.com/v2/projects/{p}/locations/-/functions'
      echo '  GET https://run.googleapis.com/apis/serving.knative.dev/v1/namespaces/{p}/revisions?labelSelector=serving.knative.dev/revisionStatus=active'
      (( DATA )) && {
        echo '  GET https://storage.googleapis.com/storage/v1/b?project={p}'
        echo '  GET https://sqladmin.googleapis.com/v1/instances?project={p}'
        echo '  GET https://spanner.googleapis.com/v1/projects/{p}/instances ; .../databases'
        echo '  GET https://bigquery.googleapis.com/bigquery/v2/projects/{p}/datasets'
      }
      (( IMAGES )) && {
        echo '  GET https://compute.googleapis.com/compute/v1/projects/{p}/regions'
        echo '  GET https://artifactregistry.googleapis.com/v1/projects/{p}/locations/{r}/repositories ; .../dockerImages'
      }
    fi
    echo
  fi
  if [[ "$MODE" != cloud ]]; then
    echo 'Defend ingest (Cloud Monitoring byte_count metrics, normalized to 30 days):'
    if (( USE_SINK_METRICS )); then
      echo '  GET https://logging.googleapis.com/v2/projects/{p}/sinks    # sinks matching "wiz"'
      echo '  GET https://monitoring.googleapis.com/v3/projects/{p}/timeSeries'
      echo '    filter: logging.googleapis.com/exports/byte_count, resource.labels.name="{sink}"'
    else
      echo '  GET https://monitoring.googleapis.com/v3/projects/{p}/timeSeries'
      echo '    filter: logging.googleapis.com/byte_count, cloudaudit activity + data_access'
      echo '    aggregation: ALIGN_RATE 3600s, REDUCE_SUM by metric.labels.log + resource.type'
      echo '    + Google Workspace slice (activity AND resource.type=audited_resource)'
      (( NO_EXCLUSION_ADJ )) || echo '    exclusion ratios applied for GKE / Data Access resource types'
    fi
    echo "  Window: last $DEFEND_DAYS days"
    echo
  fi
  echo "Output: $OUTPUT_FILE, $OUTPUT_FILE_LOG$( [[ "$MODE" != cloud ]] && printf '%s' ', gcp-defend-log-volume-<timestamp>.csv' ) in $OUTPUT_DIR"
  echo 'dry-run complete — no GCP calls were made.'
}

####
# Cloud counting — accurate (REST), one worker per project
####

scan_project_accurate() { # $1 project id, $2 project name, $3 tmp prefix
  local proj="$1" name="$2" prefix="$3"
  local counts="$prefix.counts" logf="$prefix.log"
  ERR_SINK="$prefix.errors"
  : > "$counts"; : > "$logf"

  # Enabled services gate every domain (gcp-v2:1004-1009)
  local services
  services=$(gcp_get_paged "https://serviceusage.googleapis.com/v1/projects/$proj/services?filter=state:ENABLED&pageSize=200" '.services' \
    | jq -r '[ .[].config.name ] | join(" ")')
  if [[ -z "$services" ]]; then
    status "Skipping GCP Project: $proj no services enabled."
    ERR_SINK=''
    return 0
  fi
  has_service() { [[ " $services " == *" $1 "* ]]; }

  local json n

  if has_service compute.googleapis.com; then
    # Compute instances + GKE nodes in one aggregated list (gcp-v2:598-663).
    # GKE nodes (label key goog-gke-node) count as BOTH Virtual Machines and
    # Container Hosts, exactly like the oracle; Databricks label key skips.
    json=$(gcp_get_paged "https://compute.googleapis.com/compute/v1/projects/$proj/aggregated/instances?maxResults=500" '[ .items[]? | .instances // [] ] | add')
    local vms gke
    vms=$(jq '[ .[] | select((.labels // {}) | has("databricks") | not)
                    | select((.tags.Vendor // "") != "Databricks") ] | length' <<<"$json")
    gke=$(jq '[ .[] | select((.labels // {}) | has("databricks") | not)
                    | select((.labels // {}) | has("goog-gke-node")) ] | length' <<<"$json")

    # Non-OS disks + Linux sensors apply only to non-GKE instances; the Linux
    # check follows the oracle's boot-disk → source image walk (gcp-v2:638-650,
    # 666-686), with the same image cache.
    local nonos=0 linux=0 disk_src zone disk img img_proj img_name info
    declare -A image_cache=()
    while IFS=$'\t' read -r kind disk_src; do
      [[ -n "$disk_src" ]] || continue
      if [[ "$kind" == data ]]; then
        nonos=$(( nonos + 1 ))
        continue
      fi
      zone=$(awk -F/ '{print $(NF-2)}' <<<"$disk_src")
      disk=$(awk -F/ '{print $NF}' <<<"$disk_src")
      img=$(gcp_get "https://compute.googleapis.com/compute/v1/projects/$proj/zones/$zone/disks/$disk" \
        | jq -r '.sourceImage // empty')
      if [[ -z "$img" ]]; then
        linux=$(( linux + 1 ))   # UNKNOWN description/family → no 'win' → linux (oracle default)
        continue
      fi
      img_name=${img##*/}
      img_proj=$(awk -F/ '{print $(NF-3)}' <<<"$img")
      if [[ -z "${image_cache[$img_proj/$img_name]:-}" ]]; then
        info=$(gcp_get "https://compute.googleapis.com/compute/v1/projects/$img_proj/global/images/$img_name" \
          | jq -r '"\(.description // "UNKNOWN")|\(.family // "UNKNOWN")"')
        image_cache[$img_proj/$img_name]="${info:-UNKNOWN|UNKNOWN}"
      fi
      info="${image_cache[$img_proj/$img_name],,}"
      [[ "$info" == *win* ]] || linux=$(( linux + 1 ))
    done < <(jq -r '.[]
      | select((.labels // {}) | has("databricks") | not)
      | select((.tags.Vendor // "") != "Databricks")
      | select((.labels // {}) | has("goog-gke-node") | not)
      | (.disks // [])[]
      | [ (if .boot then "boot" else "data" end), .source ] | @tsv' <<<"$json")

    emit_count 'Virtual Machines' "$vms" "$counts"
    emit_count 'Non-OS Disks' "$nonos" "$counts"
    emit_count 'Virtual Machine Sensors' "$linux" "$counts"
    progress_count "$vms" 'Virtual Machines [Compute]' "$name" '' "$logf" "with $nonos Non-OS Disks"
    emit_count 'Container Hosts' "$gke" "$counts"
    emit_count 'Kubernetes Sensors' "$gke" "$counts"
    progress_count "$gke" 'Container Hosts [GKE]' "$name" '' "$logf"
  fi

  if has_service container.googleapis.com; then
    # GKE Autopilot (gcp-v2:752-789): nodes → Kubernetes Sensors; nodes ×
    # maxPodsPerNode → Serverless Containers.
    json=$(gcp_get "https://container.googleapis.com/v1/projects/$proj/locations/-/clusters") || json='{}'
    local ap_nodes ap_containers
    read -r ap_nodes ap_containers < <(jq -r '
      [ (.clusters // [])[] | select(.autopilot.enabled == true)
        | (.nodePools // [])[]
        | { n: (.currentNodeCount // .initialNodeCount // 0),
            p: (.config.maxPodsPerNode // 0) } ] as $pools
      | [ ([ $pools[].n ] | add // 0), ([ $pools[] | .n * .p ] | add // 0) ] | @tsv' <<<"$json" | tr '\t' ' ')
    emit_count 'Kubernetes Sensors' "${ap_nodes:-0}" "$counts"
    progress_count "${ap_nodes:-0}" 'Kubernetes Sensors [GKE Autopilot]' "$name" '' "$logf"
    emit_count 'Serverless Containers' "${ap_containers:-0}" "$counts"
    progress_count "${ap_containers:-0}" 'Serverless Containers [GKE Autopilot]' "$name" '' "$logf"
  fi

  if has_service cloudfunctions.googleapis.com; then
    # Cloud Functions v2 (gcp-v2:692-715)
    n=$(gcp_get_paged "https://cloudfunctions.googleapis.com/v2/projects/$proj/locations/-/functions?pageSize=500" '.functions' | jq 'length')
    emit_count 'Serverless Functions' "$n" "$counts"
    progress_count "$n" 'Serverless Functions [Cloud Functions]' "$name" '' "$logf"
  fi

  if has_service run.googleapis.com; then
    # Cloud Run active revisions with a healthy container (gcp-v2:721-747)
    json=$(gcp_get_paged "https://run.googleapis.com/apis/serving.knative.dev/v1/namespaces/$proj/revisions?labelSelector=$(urlencode 'serving.knative.dev/revisionStatus=active')" '.items')
    n=$(jq '[ .[] | (.status.conditions // [])[]
              | select(.type == "ContainerHealthy" and .status == "True") ] | length' <<<"$json")
    emit_count 'Serverless Containers' "$n" "$counts"
    progress_count "$n" 'Serverless Containers [Cloud Run Revisions]' "$name" '' "$logf"
  fi

  if (( DATA )); then
    if has_service storage.googleapis.com; then
      # Buckets, cap 10000 (gcp-v2:856-880)
      n=$(gcp_get_paged "https://storage.googleapis.com/storage/v1/b?project=$proj&maxResults=1000" '.items' | jq 'length')
      (( n > 10000 )) && n=10000
      emit_count 'Data Buckets' "$n" "$counts"
      progress_count "$n" 'Data Buckets' "$name" '' "$logf"
    fi
    if has_service sqladmin.googleapis.com; then
      # Cloud SQL instances (gcp-v2:886-909)
      n=$(gcp_get_paged "https://sqladmin.googleapis.com/v1/instances?project=$proj" '.items' | jq 'length')
      emit_count 'PaaS Databases' "$n" "$counts"
      progress_count "$n" 'PaaS Databases [Cloud SQL]' "$name" '' "$logf"
    fi
    if has_service spanner.googleapis.com; then
      # Spanner databases per instance (gcp-v2:915-962)
      local inst db_count=0 c
      json=$(gcp_get_paged "https://spanner.googleapis.com/v1/projects/$proj/instances" '.instances')
      while IFS= read -r inst; do
        [[ -n "$inst" ]] || continue
        c=$(gcp_get_paged "https://spanner.googleapis.com/v1/$inst/databases" '.databases' | jq 'length') || c=0
        db_count=$(( db_count + c ))
      done < <(jq -r '.[].name' <<<"$json")
      emit_count 'PaaS Databases' "$db_count" "$counts"
      progress_count "$db_count" 'PaaS Databases [Spanner]' "$name" '' "$logf"
    fi
    if has_service bigquery.googleapis.com; then
      # BigQuery datasets (gcp-v2:968-991)
      n=$(gcp_get_paged "https://bigquery.googleapis.com/bigquery/v2/projects/$proj/datasets?maxResults=1000" '.datasets' | jq 'length')
      emit_count 'Data Warehouses' "$n" "$counts"
      progress_count "$n" 'Data Warehouses [BigQuery]' "$name" '' "$logf"
    fi
  fi

  if (( IMAGES )) && has_service artifactregistry.googleapis.com; then
    # Artifact Registry DOCKER images per region: min(MAX_IMAGE_TAGS, tags)
    # per image (1 for untagged), cap 10000/repo (gcp-v2:797-848)
    local regions region repo repos imgs img_count region_count
    regions=$(gcp_get_paged "https://compute.googleapis.com/compute/v1/projects/$proj/regions" '.items' | jq -r '.[].name' | sort)
    for region in $regions; do
      region_count=0
      repos=$(gcp_get_paged "https://artifactregistry.googleapis.com/v1/projects/$proj/locations/$region/repositories" '.repositories' \
        | jq -r '.[] | select(.format == "DOCKER") | .name | split("/")[-1]')
      while IFS= read -r repo; do
        [[ -n "$repo" ]] || continue
        imgs=$(gcp_get_paged "https://artifactregistry.googleapis.com/v1/projects/$proj/locations/$region/repositories/$repo/dockerImages?pageSize=1000" '.dockerImages')
        img_count=$(jq --argjson max "$MAX_IMAGE_TAGS" \
          '[ .[] | if (.tags | length) > 0 then ([ (.tags | length), $max ] | min) else 1 end ] | add // 0' <<<"$imgs")
        (( img_count > 10000 )) && img_count=10000
        region_count=$(( region_count + img_count ))
      done <<<"$repos"
      if (( region_count > 0 )); then
        emit_count 'Registry Container Images' "$region_count" "$counts"
        progress_count "$region_count" 'Registry Container Images [GAR]' "$name" "$region" "$logf"
      fi
    done
  fi

  ERR_SINK=''
}

####
# Cloud counting — fast (Cloud Asset Inventory; D2/D6)
####

cai_count() { # $1 scope (projects/x or organizations/y), $2 asset type, $3 query ('' = none) → count or '' on API failure
  local scope="$1" atype="$2" query="$3" url page total=0 next='' token_param=''
  url="https://cloudasset.googleapis.com/v1/$scope:searchAllResources?assetTypes=$(urlencode "$atype")&pageSize=500"
  [[ -n "$query" ]] && url+="&query=$(urlencode "$query")"
  while :; do
    page=$(gcp_get "${url}${token_param}") || { printf ''; return 1; }
    total=$(( total + $(jq '.results | length' <<<"$page") ))
    next=$(jq -r '.nextPageToken // empty' <<<"$page")
    [[ -z "$next" ]] && break
    token_param="&pageToken=$(urlencode "$next")"
  done
  printf '%s' "$total"
}

scan_scope_fast() { # $1 scope, $2 display name, $3 tmp prefix → prints 1 if CAI worked
  # Fast is best-effort, never silently zero (§7): if ANY Cloud Asset
  # Inventory query fails — not just the first — the partial fast counts are
  # discarded and the caller falls back to the accurate path.
  local scope="$1" name="$2" prefix="$3"
  local counts="$prefix.counts" logf="$prefix.log"
  ERR_SINK="$prefix.errors"
  : > "$counts"; : > "$logf"
  if scan_scope_fast_try "$scope" "$name" "$prefix"; then
    (( IMAGES )) && status "- Registry Container Images pending in $name: not countable from the index; rerun without --fast"
    ERR_SINK=''
    printf 1
  else
    : > "$counts"; : > "$logf"   # discard partial fast rows; the accurate path recounts
    ERR_SINK=''
    printf 0
  fi
}

scan_scope_fast_try() { # $1 scope, $2 display name, $3 tmp prefix; 1 on any CAI failure
  local scope="$1" name="$2" prefix="$3"
  local counts="$prefix.counts" logf="$prefix.log"

  local total gke vms
  total=$(cai_count "$scope" 'compute.googleapis.com/Instance' '') || return 1
  gke=$(cai_count "$scope" 'compute.googleapis.com/Instance' 'labels.goog-gke-node:*') || return 1
  vms=$(( total - ${gke:-0} ))
  (( vms < 0 )) && vms=$total
  # The oracle counts GKE nodes in Virtual Machines too (gcp-v2:629-636)
  emit_count 'Virtual Machines' "$total" "$counts"
  progress_count "$total" 'Virtual Machines [Compute]' "$name" '' "$logf" '(index count, D6)'
  emit_count 'Container Hosts' "${gke:-0}" "$counts"
  emit_count 'Kubernetes Sensors' "${gke:-0}" "$counts"
  progress_count "${gke:-0}" 'Container Hosts [GKE]' "$name" '' "$logf" '(label-indexed nodes, D2)'

  local n
  n=$(cai_count "$scope" 'cloudfunctions.googleapis.com/CloudFunction' '') || return 1
  emit_count 'Serverless Functions' "${n:-0}" "$counts"
  progress_count "${n:-0}" 'Serverless Functions [Cloud Functions]' "$name" '' "$logf"
  n=$(cai_count "$scope" 'run.googleapis.com/Revision' '') || return 1
  emit_count 'Serverless Containers' "${n:-0}" "$counts"
  progress_count "${n:-0}" 'Serverless Containers [Cloud Run Revisions]' "$name" '' "$logf" '(all revisions, not only active — D6)'
  status '- GKE Autopilot serverless containers pending under --fast (pods-per-node not indexed; D2)'

  if (( DATA )); then
    n=$(cai_count "$scope" 'storage.googleapis.com/Bucket' '') || return 1
    (( n > 10000 )) && n=10000
    emit_count 'Data Buckets' "${n:-0}" "$counts"
    progress_count "${n:-0}" 'Data Buckets' "$name" '' "$logf"
    n=$(cai_count "$scope" 'sqladmin.googleapis.com/Instance' '') || return 1
    emit_count 'PaaS Databases' "${n:-0}" "$counts"
    progress_count "${n:-0}" 'PaaS Databases [Cloud SQL]' "$name" '' "$logf"
    n=$(cai_count "$scope" 'spanner.googleapis.com/Instance' '') || return 1
    emit_count 'PaaS Databases' "${n:-0}" "$counts"
    progress_count "${n:-0}" 'PaaS Databases [Spanner]' "$name" '' "$logf" '(instances, not databases — D6)'
    n=$(cai_count "$scope" 'bigquery.googleapis.com/Dataset' '') || return 1
    emit_count 'Data Warehouses' "${n:-0}" "$counts"
    progress_count "${n:-0}" 'Data Warehouses [BigQuery]' "$name" '' "$logf"
  fi
  return 0
}

####
# Defend — Cloud Monitoring byte_count (port of log-volume-estimation-gcp.py)
####

DEFEND_ROWS=''
DEFEND_ERRORS_F=''

monitoring_series() { # $1 project, $2 filter, $3 reducer? (1/0 REDUCE_SUM+groupby log/resource) → timeSeries JSON array
  local proj="$1" filter="$2" grouped="$3" start end url out='[]' page next='' token_param=''
  end=$(utc_now_iso)
  start=$(utc_days_ago_iso "$DEFEND_DAYS")
  url="https://monitoring.googleapis.com/v3/projects/$proj/timeSeries"
  url+="?filter=$(urlencode "$filter")"
  url+="&interval.startTime=$(urlencode "$start")&interval.endTime=$(urlencode "$end")"
  url+='&aggregation.alignmentPeriod=3600s&aggregation.perSeriesAligner=ALIGN_RATE'
  if [[ "$grouped" == 1 ]]; then
    url+='&aggregation.crossSeriesReducer=REDUCE_SUM'
    url+="&aggregation.groupByFields=$(urlencode 'metric.labels.log')"
    url+="&aggregation.groupByFields=$(urlencode 'resource.type')"
  fi
  while :; do
    page=$(gcp_get "${url}${token_param}") || { printf '%s' "$out"; return 1; }
    out=$(jq -c --argjson acc "$out" '$acc + (.timeSeries // [])' <<<"$page")
    next=$(jq -r '.nextPageToken // empty' <<<"$page")
    [[ -z "$next" ]] && break
    token_param="&pageToken=$(urlencode "$next")"
  done
  printf '%s' "$out"
}

# 30-day GB from an ALIGN_RATE series: sum(rate×3600) / points × 24 / 1024³ × 30
# (defend-gcp:432-438). jq expression fragment applied per series; the $n is
# a jq binding, not a shell expansion.
# shellcheck disable=SC2016
JQ_SERIES_GB='(
  ([ .points[]?.value.doubleValue ] | length) as $n
  | if $n == 0 then 0
    else (([ .points[]?.value.doubleValue ] | add) * 3600 / $n * 24 / 1073741824 * 30)
    end
)'

defend_estimate_project() { # $1 project id — appends "gb|name|category|project" rows
  local proj="$1" json
  ERR_SINK="$DEFEND_ERRORS_F"
  status "Defend: estimating log volume for project $proj"

  # Combined audit query grouped by log × resource type (defend-gcp:407-448)
  json=$(monitoring_series "$proj" \
    'metric.type="logging.googleapis.com/byte_count" AND (metric.labels.log="cloudaudit.googleapis.com/activity" OR metric.labels.log="cloudaudit.googleapis.com/data_access")' 1) \
    || { err "Defend: monitoring query failed for $proj"; ERR_SINK=''; return 0; }

  # Workspace slice (defend-gcp:552-556)
  local ws_json ws_gb
  ws_json=$(monitoring_series "$proj" \
    'metric.type="logging.googleapis.com/byte_count" AND metric.labels.log="cloudaudit.googleapis.com/activity" AND resource.type="audited_resource"' 1) || ws_json='[]'
  ws_gb=$(jq -r "[ .[] | $JQ_SERIES_GB ] | add // 0" <<<"$ws_json")

  # Per (log, resource_type) volumes → exclusion ratios (defend-gcp:489-517)
  local line log rtype gb
  local admin_non_gke=0 gke=0 da_non_storage=0 storage=0
  while IFS='|' read -r log rtype gb; do
    [[ -n "$log" ]] || continue
    case "$log" in
      cloudaudit.googleapis.com/activity)
        case "$rtype" in
          k8s_cluster|gke_cluster)
            if (( NO_EXCLUSION_ADJ )); then
              admin_non_gke=$(awk -v a="$admin_non_gke" -v g="$gb" 'BEGIN{printf "%.10f", a + g}')
            else
              gke=$(awk -v a="$gke" -v g="$gb" -v r="$(exclusion_ratio gke_audit "$rtype")" 'BEGIN{printf "%.10f", a + g * r}')
            fi ;;
          *)
            admin_non_gke=$(awk -v a="$admin_non_gke" -v g="$gb" 'BEGIN{printf "%.10f", a + g}') ;;
        esac ;;
      cloudaudit.googleapis.com/data_access)
        if [[ "$rtype" == gcs_bucket ]]; then
          storage=$(awk -v a="$storage" -v g="$gb" 'BEGIN{printf "%.10f", a + g}')
        else
          local mult=1.0
          (( NO_EXCLUSION_ADJ )) || mult=$(exclusion_ratio data_access_non_storage "$rtype")
          da_non_storage=$(awk -v a="$da_non_storage" -v g="$gb" -v r="$mult" 'BEGIN{printf "%.10f", a + g * r}')
        fi ;;
    esac
  done < <(jq -r ".[] | [ (.metric.labels.log // \"\"), (.resource.type // \"\"), ($JQ_SERIES_GB | tostring) ] | join(\"|\")" <<<"$json")

  local key val info
  for key in admin_activity_non_gke gke_audit data_access_non_storage storage_data_access workspace_audit; do
    case "$key" in
      admin_activity_non_gke) val="$admin_non_gke" ;;
      gke_audit) val="$gke" ;;
      data_access_non_storage) val="$da_non_storage" ;;
      storage_data_access) val="$storage" ;;
      workspace_audit) val="$ws_gb" ;;
    esac
    if awk -v v="$val" 'BEGIN{exit !(v > 0)}'; then
      info=$(defend_log_info "$key")
      printf '%s|%s|%s|%s\n' "$(awk -v v="$val" 'BEGIN{printf "%.2f", v}')" "${info%%|*}" "${info##*|}" "$proj" >> "$DEFEND_ROWS"
    fi
  done
  ERR_SINK=''
}

defend_sink_project() { # $1 project id — measured sink volumes
  local proj="$1" sinks sink json gb info
  ERR_SINK="$DEFEND_ERRORS_F"
  status "Defend: measuring Wiz sink volume for project $proj"
  if [[ -n "$SINK_NAME" ]]; then
    sinks="$SINK_NAME"
  else
    # Sinks with 'wiz' in name or destination (defend-gcp:350-370)
    sinks=$(gcp_get_paged "https://logging.googleapis.com/v2/projects/$proj/sinks" '.sinks' \
      | jq -r '.[] | select((.name | ascii_downcase | contains("wiz"))
                        or ((.destination // "") | ascii_downcase | contains("wiz"))) | .name')
  fi
  if [[ -z "$sinks" ]]; then
    status "Defend: no Wiz-related sinks found in $proj"
    ERR_SINK=''
    return 0
  fi
  while IFS= read -r sink; do
    [[ -n "$sink" ]] || continue
    json=$(monitoring_series "$proj" \
      "metric.type=\"logging.googleapis.com/exports/byte_count\" AND resource.type=\"logging_sink\" AND resource.labels.name=\"$sink\"" 0) || json='[]'
    gb=$(jq -r "[ .[] | $JQ_SERIES_GB ] | add // 0" <<<"$json")
    if awk -v v="$gb" 'BEGIN{exit !(v > 0)}'; then
      info=$(defend_log_info measured_sink)
      printf '%s|Log Sink: %s|%s|%s\n' "$(awk -v v="$gb" 'BEGIN{printf "%.2f", v}')" "$sink" "${info##*|}" "$proj" >> "$DEFEND_ROWS"
    fi
  done <<<"$sinks"
  ERR_SINK=''
}

run_defend() { # $@ = "id<TAB>name" project lines
  DEFEND_ROWS="$TMP_DIR/defend.rows"
  DEFEND_ERRORS_F="$TMP_DIR/defend.errors"
  touch "$DEFEND_ROWS" "$DEFEND_ERRORS_F"
  local line proj
  for line in "$@"; do
    proj=${line%%$'\t'*}
    if (( RESUME )) && grep -q "^defend $proj done\$" "$STATE_FILE" 2>/dev/null; then
      status "Defend: skipping $proj (resumed)"
      continue
    fi
    if (( USE_SINK_METRICS )); then
      defend_sink_project "$proj"
    else
      defend_estimate_project "$proj"
    fi
    echo "defend $proj done" >> "$STATE_FILE"
  done
}

write_defend_output() {
  [[ -n "${DEFEND_ROWS:-}" && -f "$DEFEND_ROWS" ]] || return 0
  local stamp csv_file
  stamp=$(date +%Y%m%d-%H%M%S)
  csv_file="$OUTPUT_DIR/gcp-defend-log-volume-$stamp.csv"
  {
    csv_row 'Log Source Type' 'Billable Category' 'Specific Metric' 'Resource/Scope Details' 'Estimated 30-Day Uncompressed Volume (GB)'
    local gb lname cat proj
    while IFS='|' read -r gb lname cat proj; do
      [[ -n "$lname" ]] || continue
      csv_row 'GCP Monitoring Metrics' "$cat" "$lname" "Project: $proj" "$gb"
    done < <(sort -t'|' -k1,1gr "$DEFEND_ROWS")
  } > "$csv_file"

  local total
  total=$(awk -F'|' '{ s += $1 } END { printf "%.2f", s }' "$DEFEND_ROWS")
  echo
  echo 'Wiz Defend Ingestion: GCP Log Volume Estimation'
  echo "Time period: Last $DEFEND_DAYS days (results extrapolated to 30-day volume)"
  echo
  awk -F'|' '{ printf "  %-36s %-14s Project: %-24s : %s GB\n", $2, $3, $4, $1 }' "$DEFEND_ROWS" | sort
  echo
  echo "  Total Estimated 30-Day Volume: $total GB"
  awk -v t="$total" 'BEGIN { printf "  Average Daily Volume         : %.2f GB\n", t / 30 }'
  echo
  echo "Defend details written to $csv_file"
  if [[ -s "$DEFEND_ERRORS_F" ]]; then
    sort -u "$DEFEND_ERRORS_F" > "$OUTPUT_DIR/$DEFEND_ERROR_LOG_FILE"
    echo "Defend errors logged to $DEFEND_ERROR_LOG_FILE"
  fi
}

####
# Output — cloud CSVs + summary block (single writer; §11, §12)
####

write_cloud_output() {
  local partial="${1:-}"
  declare -A totals
  local key f v
  for key in "${TOTAL_KEYS[@]}"; do totals[$key]=0; done

  local projects_merged=0
  for f in "$TMP_DIR"/cloud.*.counts; do
    [[ -f "$f" ]] || continue
    projects_merged=$(( projects_merged + 1 ))
    while IFS='=' read -r key v; do
      [[ -n "$key" && -n "${totals[$key]+x}" ]] || continue
      totals[$key]=$(( totals[$key] + v ))
    done < "$f"
  done

  mkdir -p "$OUTPUT_DIR"
  {
    csv_row 'Resource Type' 'Resource Count'
    for key in "${TOTAL_KEYS[@]}"; do
      csv_row "$key" "${totals[$key]}"
    done
  } > "$OUTPUT_DIR/$OUTPUT_FILE"

  {
    csv_row 'Resource Type' 'Resource Count' 'Project' 'Region'
    for f in "$TMP_DIR"/cloud.*.log; do
      [[ -f "$f" ]] || continue
      cat "$f"
    done
  } > "$OUTPUT_DIR/$OUTPUT_FILE_LOG"

  local err_count=0
  : > "$TMP_DIR/all.errors"
  for f in "$TMP_DIR"/*.errors "$GLOBAL_ERRORS"; do
    [[ -f "$f" ]] || continue
    cat "$f" >> "$TMP_DIR/all.errors"
  done
  if [[ -s "$TMP_DIR/all.errors" ]]; then
    sort -u "$TMP_DIR/all.errors" > "$OUTPUT_DIR/$ERROR_LOG_FILE"
    err_count=$(grep -c . "$OUTPUT_DIR/$ERROR_LOG_FILE")
  fi

  local label='Results'
  [[ -n "$partial" ]] && label='Partial results'
  echo
  echo "$label across $projects_merged GCP Projects (wiz-gcp.sh version: $VERSION)"
  echo
  printf "%${PADDING}s Virtual Machines [Compute]\n" "${totals['Virtual Machines']}"
  printf "%${PADDING}s Container Hosts [GKE]\n" "${totals['Container Hosts']}"
  printf "%${PADDING}s Serverless Functions [Cloud Functions]\n" "${totals['Serverless Functions']}"
  printf "%${PADDING}s Serverless Containers [Cloud Run Revisions, GKE Autopilot]\n" "${totals['Serverless Containers']}"
  if (( DATA )); then
    echo
    printf "%${PADDING}s Data Buckets (Public and Private)\n" "${totals['Data Buckets']}"
    printf "%${PADDING}s PaaS Databases [Cloud SQL, Spanner]\n" "${totals['PaaS Databases']}"
    printf "%${PADDING}s Data Warehouses [BigQuery]\n" "${totals['Data Warehouses']}"
    echo
    printf "%${PADDING}s Non-OS Disks [Compute]\n" "${totals['Non-OS Disks']}"
  fi
  if (( IMAGES )); then
    echo
    if (( FAST )); then
      printf "%${PADDING}s Registry Container Images [GAR] (pending: rerun without --fast)\n" 'n/a'
    else
      printf "%${PADDING}s Registry Container Images [GAR]\n" "${totals['Registry Container Images']}"
    fi
  fi
  echo
  printf "%${PADDING}s (Potential) Kubernetes Sensors [GKE, GKE Autopilot]\n" "${totals['Kubernetes Sensors']}"
  printf "%${PADDING}s (Potential) Virtual Machine Sensors [Estimated from Boot Image *]\n" "${totals['Virtual Machine Sensors']}"
  printf "%${PADDING}s (Potential) Serverless Container Sensors\n" "${totals['Serverless Container Sensors']}"
  echo
  echo '* Linux Sensor counts may be lower, depending upon kernel and operating system versions'
  if (( ! DATA )); then
    echo
    echo "To count Data Security (Buckets, Databases, etc) resources, rerun with '--data'"
  fi
  if (( ! IMAGES )); then
    echo
    echo "To count Registry Container Images, rerun with '--images'"
  fi
  echo
  echo "Details written to $OUTPUT_FILE and $OUTPUT_FILE_LOG"
  if (( err_count > 0 )); then
    echo
    echo "$err_count error(s) occurred. Review $ERROR_LOG_FILE."
  fi
  [[ -n "$partial" ]] && echo 'Scan interrupted; results above cover completed projects only.'
  return 0
}

####
# Scan orchestration — bounded parallelism, per-project temp files, resume (§11)
####

enumerate_org_parents() { # → newline-separated parent IDs: the org + every folder under it (recursive)
  local pending=("organizations/$ORG_ID") parent folders
  printf '%s\n' "$ORG_ID"
  while (( ${#pending[@]} > 0 )); do
    parent=${pending[0]}
    pending=("${pending[@]:1}")
    folders=$(gcp_get_paged "https://cloudresourcemanager.googleapis.com/v2/folders?parent=$(urlencode "$parent")&pageSize=300" '.folders') || folders='[]'
    while IFS= read -r parent; do
      [[ -n "$parent" ]] || continue          # parent is "folders/<id>"
      printf '%s\n' "${parent#folders/}"
      pending+=("$parent")
    done < <(jq -r '.[].name // empty' <<<"$folders")
  done
}

enumerate_projects() { # → "id<TAB>name" lines
  if [[ -n "$PROJECTS" ]]; then
    local id detail
    for id in ${PROJECTS//,/ }; do
      detail=$(gcp_get "https://cloudresourcemanager.googleapis.com/v1/projects/$id") \
        || { err "cannot read project $id"; continue; }
      jq -r '[ .projectId, (.name // "UNNAMED") ] | @tsv' <<<"$detail"
    done
    return 0
  fi
  if [[ -n "$ORG_ID" ]]; then
    # Org scope: keep only ACTIVE projects whose parent is the org itself or a
    # folder under it, so accurate/Defend scans match the --fast org sweep.
    # (projects.list carries each project's direct parent; the folder tree is
    # walked via cloudresourcemanager v2 folders.list.)
    local parents_json
    parents_json=$(enumerate_org_parents | jq -R . | jq -cs .)
    gcp_get_paged 'https://cloudresourcemanager.googleapis.com/v1/projects?pageSize=500' '.projects' \
      | jq -r --argjson parents "$parents_json" \
          '.[] | select(.lifecycleState == "ACTIVE")
               | select((.parent.id // "") as $p | $parents | index($p))
               | [ .projectId, (.name // "UNNAMED") ] | @tsv' | sort
    return 0
  fi
  # All ACTIVE listable projects, sorted by ID (gcp-v2:518-555)
  gcp_get_paged 'https://cloudresourcemanager.googleapis.com/v1/projects?pageSize=500' '.projects' \
    | jq -r '.[] | select(.lifecycleState == "ACTIVE")
                 | [ .projectId, (.name // "UNNAMED") ] | @tsv' | sort
}

wait_for_slot() {
  while (( $(jobs -rp | wc -l) >= MAX_PARALLEL )); do sleep 0.2; done
}

run_cloud() { # $@ = "id<TAB>name" project lines
  local lines=("$@") line proj name idx=0
  local total=${#lines[@]}

  # Org-scope fast path: one CAI sweep instead of per-project scans (§7)
  if (( FAST )) && [[ -n "$ORG_ID" ]]; then
    status "Cloud: fast org-scope scan of organizations/$ORG_ID via Cloud Asset Inventory"
    local ok
    ok=$( scan_scope_fast "organizations/$ORG_ID" "org $ORG_ID" "$TMP_DIR/cloud.org" )
    if [[ "$ok" == 1 ]]; then
      echo "cloud org done" >> "$STATE_FILE"
      return 0
    fi
    status '[FALLBACK] org-scope Cloud Asset Inventory unavailable — per-project scans'
  fi

  status "Cloud: scanning $total project(s) with up to $MAX_PARALLEL in parallel"
  for line in "${lines[@]}"; do
    proj=${line%%$'\t'*}; name=${line#*$'\t'}
    idx=$(( idx + 1 ))
    if (( RESUME )) && grep -q "^cloud $proj done\$" "$STATE_FILE" 2>/dev/null; then
      status "[SKIP] Project $idx/$total: $proj (resumed)"
      continue
    fi
    status "[SCAN] Project $idx/$total: $proj - $name"
    wait_for_slot
    (
      if (( FAST )); then
        local ok
        ok=$( scan_scope_fast "projects/$proj" "$name" "$TMP_DIR/cloud.$proj" )
        if [[ "$ok" != 1 ]]; then
          status "[FALLBACK] $proj: Cloud Asset Inventory unavailable — accurate scan (§7)"
          scan_project_accurate "$proj" "$name" "$TMP_DIR/cloud.$proj"
        fi
      else
        scan_project_accurate "$proj" "$name" "$TMP_DIR/cloud.$proj"
      fi
      echo "cloud $proj done" >> "$STATE_FILE"
      status "[DONE] Project: $proj ($name)"
    ) &
  done
  wait
}

on_interrupt() {
  trap - INT TERM
  status '[INTERRUPTED] Writing partial results before exiting.'
  if [[ "$MODE" != defend ]]; then write_cloud_output partial; fi
  if [[ "$MODE" != cloud ]]; then write_defend_output; fi
  echo "Resume with: wiz-gcp.sh $MODE --resume --output-dir $OUTPUT_DIR"
  exit 130
}

####
# Interactive menu (§4)
####

menu() {
  cat <<EOF

wiz-gcp.sh v$VERSION — Wiz sizing for GCP

  1) Full sizing        cloud resources + Defend ingest (recommended)
  2) Full + data/images adds Buckets, Cloud SQL, Spanner, BigQuery, GAR images
  3) Fast estimate      Cloud Asset Inventory (D2/D6 apply)
  4) Cloud resources only
  5) Defend ingest only
  q) Quit

EOF
  local choice
  read -r -p 'Select: ' choice || choice=q
  case "$choice" in
    1) MODE=all ;;
    2) MODE=all; DATA=1; IMAGES=1 ;;
    3) MODE=all; FAST=1 ;;
    4) MODE=cloud ;;
    5) MODE=defend ;;
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
      all|cloud|defend) MODE="$1"; shift ;;
      --fast) FAST=1; shift ;;
      --data) DATA=1; shift ;;
      --images) IMAGES=1; shift ;;
      --resume) RESUME=1; shift ;;
      --dry-run) DRY_RUN=1; shift ;;
      --quiet) QUIET=1; shift ;;
      --output-dir) OUTPUT_DIR="${2:?--output-dir needs a value}"; shift 2 ;;
      --projects) PROJECTS="${2:?--projects needs a value}"; shift 2 ;;
      --org) ORG_ID="${2:?--org needs a value}"; shift 2 ;;
      --days) DEFEND_DAYS="${2:?--days needs a value}"; shift 2 ;;
      --use-sink-metrics) USE_SINK_METRICS=1; shift ;;
      --sink-name) SINK_NAME="${2:?--sink-name needs a value}"; USE_SINK_METRICS=1; shift 2 ;;
      --no-exclusion-adjustment) NO_EXCLUSION_ADJ=1; shift ;;
      --max-parallel) MAX_PARALLEL="${2:?--max-parallel needs a value}"; shift 2 ;;
      --max-image-tags) MAX_IMAGE_TAGS="${2:?--max-image-tags needs a value}"; shift 2 ;;
      --print-csv-contract) print_csv_contract; exit 0 ;;
      --list) list_modes; exit 0 ;;
      --version) echo "wiz-gcp.sh $VERSION"; exit 0 ;;
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
  TMP_DIR="$OUTPUT_DIR/.wiz-gcp-tmp"
  STATE_FILE="$OUTPUT_DIR/.wiz-gcp-state"
  if (( ! RESUME )); then
    rm -rf "$TMP_DIR"
    rm -f "$STATE_FILE"
  fi
  mkdir -p "$TMP_DIR"
  touch "$STATE_FILE"
  GLOBAL_ERRORS="$TMP_DIR/global.errors"
  touch "$GLOBAL_ERRORS"

  trap on_interrupt INT TERM

  status "wiz-gcp.sh v$VERSION — mode: $MODE$( ((FAST)) && printf ' (fast)' )"
  status 'Enumerating GCP projects'
  local projects=() line
  while IFS= read -r line; do
    [[ -n "$line" ]] && projects+=("$line")
  done < <(enumerate_projects)
  if (( ${#projects[@]} == 0 )); then
    echo 'No projects found. Run gcloud auth login (or pass --projects IDs).' >&2
    exit 1
  fi
  status "Found ${#projects[@]} project(s)"

  if [[ "$MODE" != defend ]]; then
    run_cloud "${projects[@]}"
  fi
  if [[ "$MODE" != cloud ]]; then
    run_defend "${projects[@]}"
  fi

  if [[ "$MODE" != defend ]]; then write_cloud_output; fi
  if [[ "$MODE" != cloud ]]; then write_defend_output; fi

  rm -rf "$TMP_DIR"
  rm -f "$STATE_FILE"
  status 'Scan complete.'
}

main "$@"
