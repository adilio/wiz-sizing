#!/usr/bin/env bash
# wiz-azure.sh — Wiz sizing for Azure: cloud resources + Defend ingest in one pass.
#
#   bash <(curl -sL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-azure.sh)
#
# Requires only what Azure Cloud Shell ships: bash 4+, az (logged in), jq, curl.
# Counting logic reproduces the official Wiz sizing scripts (see reference/ and
# parity/mapping.md in the repo); output CSV filenames and headers are identical.
#
# Modes:    all (default) · cloud · defend
# Opt-ins:  --azdo (Azure DevOps developer counting) · --m365 (hands off to wiz-365.ps1)
#
# Everything is read-only. No app registrations, no consent grants, no modules.

set -uo pipefail

if (( BASH_VERSINFO[0] < 4 )); then
  echo "wiz-azure.sh needs bash 4+ (Azure Cloud Shell has it; on macOS use 'brew install bash')." >&2
  exit 1
fi

VERSION='1.0.0'

####
# Defaults and globals
####

MODE=''                # all | cloud | defend  ('' → menu when no args at all)
FAST=0
DATA=0
IMAGES=0
RESUME=0
DRY_RUN=0
QUIET=0
OUTPUT_DIR='.'
SUBSCRIPTION=''        # single subscription ID; empty → all accessible
SUBSCRIPTIONS_FILE=''  # file with one subscription ID per line
DEFEND_DAYS=30
AZDO_DAYS=90
MAX_PARALLEL=8
MAX_IMAGE_TAGS=5
AZDO='auto'            # auto | on | off
AZDO_ORG="${AZDO_ORG:-}"
M365=0
DEFEND_WORKSPACES=''   # comma-separated workspace GUIDs to supplement discovery

ARM_AUDIENCE='https://management.azure.com'
LA_AUDIENCE='https://api.loganalytics.io'
AZDO_AUDIENCE='499b84ac-1321-427f-aa17-267ca6975798'
ARG_URL='https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01'

OUTPUT_FILE='azure-resources.csv'
OUTPUT_FILE_LOG='azure-resources-log.csv'
ERROR_LOG_FILE='azure-errors-log.txt'
DEFEND_ERROR_LOG_FILE='azure-defend-errors-log.txt'
PADDING=6

# CSV row order — matches the official totals dict exactly
# (reference/cloud/azure/resource-count-azure-v2.py:259-276).
TOTAL_KEYS=(
  'Virtual Machines'
  'Container Hosts'
  'Serverless Functions'
  'Serverless Containers'
  'Asset Metadata'
  'Data Buckets'
  'PaaS Databases'
  'Data Warehouses'
  'Non-OS Disks'
  'Registry Container Images'
  'Kubernetes Sensors'
  'Virtual Machine Sensors'
  'Serverless Container Sensors'
)

# Defend log types relevant for Wiz Defend — name|category per DataType
# (reference/defend/azure/log-volume-estimation-azure.py:103-125).
DEFEND_TYPE_KEYS=(
  AzureActivity AuditLogs SignInLogs AADNonInteractiveUserSignInLogs
  AADServicePrincipalSignInLogs AADManagedIdentitySignInLogs AADProvisioningLogs
  AADADFSSignInLogs AADRiskyUsers AADUserRiskEvents AADRiskyServicePrincipals
  AADServicePrincipalRiskEvents KubeAudit KubeAuditAdmin AZMSKeyVaultAuditLogs
  AZKVAuditLogs StorageBlobLogs
)

defend_type_info() { # $1 = DataType → "Display Name|Category"
  case "$1" in
    AzureActivity)                   echo 'Azure Activity Logs|Management' ;;
    AuditLogs)                       echo 'Entra ID Audit Logs|Identity' ;;
    SignInLogs)                      echo 'Entra ID Signin Logs|Identity' ;;
    AADNonInteractiveUserSignInLogs) echo 'Entra ID Non-Interactive Signin Logs|Identity' ;;
    AADServicePrincipalSignInLogs)   echo 'Entra ID Service Principal Signin Logs|Identity' ;;
    AADManagedIdentitySignInLogs)    echo 'Entra ID Managed Identity Signin Logs|Identity' ;;
    AADProvisioningLogs)             echo 'Entra ID Provisioning Logs|Identity' ;;
    AADADFSSignInLogs)               echo 'Entra ID ADFS Signin Logs|Identity' ;;
    AADRiskyUsers)                   echo 'Entra ID Risky Users|Identity' ;;
    AADUserRiskEvents)               echo 'Entra ID Identity Protection|Identity' ;;
    AADRiskyServicePrincipals)       echo 'Entra ID Risky Service Principals|Identity' ;;
    AADServicePrincipalRiskEvents)   echo 'Entra ID Service Principal Risk Events|Identity' ;;
    KubeAudit)                       echo 'AKS Audit Logs|Management' ;;
    KubeAuditAdmin)                  echo 'AKS Audit Logs (Admin)|Management' ;;
    AZMSKeyVaultAuditLogs)           echo 'Azure Key Vault Logs|Data' ;;
    AZKVAuditLogs)                   echo 'Azure Key Vault Audit Logs|Data' ;;
    StorageBlobLogs)                 echo 'Azure Storage Blob Logs|Data' ;;
    *)                               echo 'Unknown|Data' ;;
  esac
}

RUN_STARTED_AT=$SECONDS
STATE_FILE=''
TMP_DIR=''
ERR_SINK=''            # per-worker error file; empty → global errors file
GLOBAL_ERRORS=''
DEFEND_ERRORS=''

####
# Usage / list / contract
####

usage() {
  cat <<EOF
Usage: wiz-azure.sh [MODE] [flags]

Estimate Wiz billable units for Azure. Default run counts cloud resources AND
estimates Wiz Defend log ingest, in one pass, using only your existing 'az'
session (read-only; no app registrations or consent grants).

Modes:
  all                 Cloud resources + Defend ingest (default)
  cloud               Cloud resources only
  defend              Defend ingest estimate only

Flags:
  --fast              Fast estimate via Resource Graph aggregations. Skips the
                      live drill-downs; see the deviation notes in --help output
                      below (D3-D5). Falls back to the accurate path per
                      subscription when Resource Graph is unavailable.
  --data              Also count Data Security resources (Buckets, PaaS DBs)
  --images            Also count Registry Container Images (ACR)
  --resume            Resume an interrupted scan (per-subscription checkpoints)
  --output-dir DIR    Directory for output CSVs (default: current directory)
  --subscription ID   Scan a single subscription (default: all accessible)
  --subscriptions-file FILE
                      Scan the subscription IDs listed in FILE (one per line)
  --days N            Defend: analyze the last N days of logs (default: 30)
  --defend-workspace GUIDS
                      Defend: also query these Log Analytics workspace GUIDs
                      (comma-separated) in addition to discovery
  --max-parallel N    Concurrent subscription scans (default: 8)
  --max-image-tags N  Image tags counted per ACR repository (default: 5)
  --azdo              Opt in to Azure DevOps repo/developer counting
  --no-azdo           Never prompt for Azure DevOps counting
  --org ORG           Azure DevOps organization (name or URL) for --azdo
  --azdo-days N       AzDO: count developers active in the last N days (default: 90)
  --m365              Opt in to Microsoft 365 sizing (hands off to wiz-365.ps1)
  --dry-run           Print the API calls this run would make, then exit.
                      Makes no cloud calls and needs no az session.
  --quiet             Suppress progress output (data/CSVs unchanged)
  --list              List modes and opt-in domains
  --version           Print version
  --help              This help

Output files (identical to the official Wiz sizing scripts):
  azure-resources.csv, azure-resources-log.csv, azure-errors-log.txt
  azure-defend-log-volume-<timestamp>.csv, azure-defend-errors-log.txt

Fast-mode deviations (documented in the repo's PLAN.md §9):
  D3: Scale Set VMs use configured sku.capacity, not live instances (>= live).
  D4: child Functions inside Function Apps are not visible to Resource Graph.
  D5: --data / --images counts are data-plane and stay pending under --fast;
      rerun without --fast for those.

Run with no arguments for an interactive menu.
EOF
}

list_modes() {
  cat <<EOF
Modes:
  all      Cloud resources + Defend ingest (default)
  cloud    Cloud resources only
  defend   Defend ingest estimate only

Opt-in domains (never run by default):
  --azdo   Azure DevOps repo/developer counting (prompted only when detected)
  --m365   Microsoft 365 sizing via wiz-365.ps1 (PowerShell, device-code auth)

Opt-in extras:
  --data   Data Buckets + PaaS Databases     --images  ACR container images
EOF
}

print_csv_contract() {
  # filename<TAB>header — pinned by tests/contract.bats against reference/.
  printf 'azure-resources.csv\tResource Type,Resource Count\n'
  printf 'azure-resources-log.csv\tResource Type,Resource Count,Subscription\n'
  printf 'azure-defend-log-volume-YYYYMMDD-HHMMSS.csv\tLog Source Type,Billable Category,Specific Metric,Resource/Scope Details,Estimated 30-Day Uncompressed Volume (GB)\n'
  printf 'azure_devops-<ORG>-developers.txt\t(no header; one hashed developer email per line)\n'
  printf 'azure_devops-<ORG>-developers-log.txt\tOrganization,Project,Repository,Developers (Last %s Days),Commits Scanned,Status,Error\n' "$AZDO_DAYS"
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

status() { # progress → stderr (§12)
  (( QUIET )) && return 0
  printf '+%s %s\n' "$(elapsed)" "$*" >&2
}

err() { # record an error; never fatal
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

utc_days_ago_iso() { # $1 = days
  local out
  if out=$(date -u -d "$1 days ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null); then
    printf '%s' "$out"
  else
    date -u -v-"$1"d +%Y-%m-%dT%H:%M:%SZ
  fi
}

sha256_hex() { # hash stdin-less string arg, hex digest (matches python hashlib on utf-8)
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  else
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  fi
}

require_tools() {
  local missing=0 t
  for t in az jq curl; do
    if ! command -v "$t" >/dev/null 2>&1; then
      echo "ERROR: '$t' not found. Run from Azure Cloud Shell, or install it." >&2
      missing=1
    fi
  done
  (( missing )) && exit 1
  return 0
}

####
# Tokens — per-audience acquire + refresh (PLAN §6)
####

get_token() { # $1 = audience/resource → prints access token
  # Cached as a file under $TMP_DIR (0600): every HTTP call chain runs inside
  # $(...) subshells, so shell-variable caches never survive back to the
  # parent — the file cache does, and it is shared across parallel workers.
  local aud="$1" now exp json token cache=''
  now=$(date +%s)
  if [[ -n "$TMP_DIR" ]]; then
    cache="$TMP_DIR/token.${aud//[^A-Za-z0-9]/_}"
    if [[ -r "$cache" ]]; then
      { IFS= read -r exp && IFS= read -r token; } < "$cache" || token=''
      if [[ -n "$token" && "$exp" =~ ^[0-9]+$ ]] && (( exp - now > 300 )); then
        printf '%s' "$token"
        return 0
      fi
    fi
  fi
  if ! json=$(az account get-access-token --resource "$aud" --output json 2>/dev/null); then
    err "cannot acquire a token for $aud — run 'az login' first"
    return 1
  fi
  token=$(jq -r '.accessToken' <<<"$json")
  exp=$(jq -r '.expires_on // empty' <<<"$json")
  [[ "$exp" =~ ^[0-9]+$ ]] || exp=$(( now + 3300 ))
  if [[ -n "$cache" ]]; then
    ( umask 077; printf '%s\n%s\n' "$exp" "$token" > "$cache.$$" ) && mv -f "$cache.$$" "$cache"
  fi
  printf '%s' "$token"
}

####
# HTTP — retries on 429/5xx, error isolation
####

http_request() { # $1 method, $2 audience, $3 url, $4 body ('' for none) → response body
  local method="$1" aud="$2" url="$3" body="${4:-}"
  local attempt resp code payload token
  for attempt in 1 2 3 4 5; do
    token=$(get_token "$aud") || return 1
    if [[ -n "$body" ]]; then
      resp=$(curl -sS -X "$method" \
        -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
        --data "$body" -w $'\n%{http_code}' "$url" 2>/dev/null) || resp=$'\n000'
    else
      resp=$(curl -sS -X "$method" \
        -H "Authorization: Bearer $token" \
        -w $'\n%{http_code}' "$url" 2>/dev/null) || resp=$'\n000'
    fi
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

arm_get_all() { # $1 = ARM list URL → JSON array aggregated across nextLink pages
  local url="$1" out='[]' page
  while [[ -n "$url" && "$url" != null ]]; do
    page=$(http_request GET "$ARM_AUDIENCE" "$url" '') || { printf '%s' "$out"; return 1; }
    out=$(jq -c --argjson acc "$out" '$acc + (.value // [])' <<<"$page") || { printf '[]'; return 1; }
    url=$(jq -r '.nextLink // empty' <<<"$page")
  done
  printf '%s' "$out"
}

arg_query() { # $1 = subscription id ('' = tenant-wide), $2 = KQL → data array
  local sub="$1" kql="$2" skip_token='' body page out='[]'
  while :; do
    body=$(jq -cn --arg q "$kql" --arg sub "$sub" --arg st "$skip_token" \
      '{query:$q}
       + (if $sub == "" then {} else {subscriptions:[$sub]} end)
       + (if $st == "" then {} else {options:{"$skipToken":$st}} end)')
    page=$(http_request POST "$ARM_AUDIENCE" "$ARG_URL" "$body") || return 1
    out=$(jq -c --argjson acc "$out" '$acc + (.data // [])' <<<"$page") || return 1
    skip_token=$(jq -r '."$skipToken" // empty' <<<"$page")
    [[ -z "$skip_token" ]] && break
  done
  printf '%s' "$out"
}

la_query() { # $1 = workspace GUID, $2 = KQL, $3 = timespan "start/end" → response JSON
  local guid="$1" kql="$2" timespan="$3" body
  body=$(jq -cn --arg q "$kql" --arg t "$timespan" '{query:$q, timespan:$t}')
  http_request POST "$LA_AUDIENCE" "https://api.loganalytics.io/v1/workspaces/$guid/query" "$body"
}

####
# Dry-run — prints the call plan; provably no cloud calls, no session needed
####

dry_run_plan() {
  echo "wiz-azure.sh v$VERSION — dry-run: the calls this run would make (none are made now)."
  echo
  echo "Tokens (from your az session, re-fetched per audience as they near expiry):"
  echo "  az account get-access-token --resource $ARM_AUDIENCE"
  [[ "$MODE" != cloud ]] && echo "  az account get-access-token --resource $LA_AUDIENCE"
  [[ "$AZDO" == on ]] && echo "  az account get-access-token --resource $AZDO_AUDIENCE  # Azure DevOps"
  echo
  if [[ -n "$SUBSCRIPTION" ]]; then
    echo "Scope: subscription $SUBSCRIPTION"
  elif [[ -n "$SUBSCRIPTIONS_FILE" ]]; then
    echo "Scope: subscriptions listed in $SUBSCRIPTIONS_FILE"
  else
    echo "Scope: all accessible subscriptions"
    echo "  GET $ARM_AUDIENCE/subscriptions?api-version=2020-01-01"
  fi
  echo
  if [[ "$MODE" != defend ]]; then
    if (( FAST )); then
      echo "Cloud resources (fast estimate — Resource Graph aggregations, per subscription):"
      echo "  POST $ARG_URL"
      echo "    KQL: virtualmachines count (excl. tags.Vendor=Databricks); sum(dataDisks)"
      echo "    KQL: virtualmachinescalesets sum(sku.capacity)              [D3: configured >= live]"
      echo "    KQL: managedclusters mv-expand agentPoolProfiles sum(count)"
      echo "    KQL: web/sites count + web/staticsites count               [D4: no child functions]"
      echo "    KQL: containerinstance/containergroups count; app/containerapps count"
      echo "    KQL: hybridcompute/machines count; azurestackhci/clusters count"
      (( DATA ))   && echo "    KQL: sql/servers/databases count; Data Buckets stay pending [D5]"
      (( IMAGES )) && echo "    Registry images stay pending under --fast                  [D5]"
    else
      echo "Cloud resources (accurate — ARM REST per subscription, followed via nextLink):"
      echo "  GET .../providers/Microsoft.Compute/virtualMachines"
      echo "  GET .../providers/Microsoft.Compute/virtualMachineScaleSets"
      echo "  GET .../virtualMachineScaleSets/{name}/virtualMachines           # live instances"
      echo "  GET .../providers/Microsoft.ContainerService/managedClusters      # sum agent pools"
      echo "  GET .../providers/Microsoft.Web/sites"
      echo "  GET .../sites/{name}/functions                                    # child functions"
      echo "  GET .../providers/Microsoft.ContainerInstance/containerGroups"
      echo "  GET .../providers/Microsoft.App/containerApps"
      echo "  GET .../providers/Microsoft.HybridCompute/machines"
      echo "  GET .../providers/Microsoft.AzureStackHCI/clusters"
      (( DATA )) && {
        echo "  GET .../providers/Microsoft.Storage/storageAccounts"
        echo "  GET .../storageAccounts/{name}/blobServices/default/containers  # control plane"
        echo "  GET .../providers/Microsoft.Sql/servers ; .../servers/{name}/databases"
      }
      (( IMAGES )) && {
        echo "  GET .../providers/Microsoft.ContainerRegistry/registries"
        echo "  az acr repository list / show-tags per registry                 # data plane"
      }
    fi
    echo
  fi
  if [[ "$MODE" != cloud ]]; then
    echo "Defend ingest (Log Analytics discovery + KQL, normalized to 30 days):"
    echo "  GET $ARM_AUDIENCE/providers/microsoft.aadiam/providers/Microsoft.Insights/diagnosticSettings?api-version=2017-04-01-preview"
    echo "  GET $ARM_AUDIENCE/providers/Microsoft.Management/managementGroups?api-version=2020-05-01"
    echo "  GET .../managementGroups/{mg}/providers/Microsoft.Insights/diagnosticSettings?api-version=2021-05-01-preview"
    echo "  GET .../subscriptions/{sub}/providers/Microsoft.Insights/diagnosticSettings?api-version=2021-05-01-preview"
    echo "  GET {workspaceResourceId}?api-version=2020-08-01                    # GUID + name"
    echo "  POST https://api.loganalytics.io/v1/workspaces/{guid}/query"
    echo "    KQL: Usage | where IsBillable and DataType in (relevant types) | summarize sum(Quantity) by DataType"
    echo "    KQL fallbacks: AzureActivity, StorageBlobLogs, AzureDiagnostics (KeyVault/Storage)"
    [[ -n "$DEFEND_WORKSPACES" ]] && echo "  plus explicit workspaces: $DEFEND_WORKSPACES"
    echo "  Window: last $DEFEND_DAYS days"
    echo
  fi
  if [[ "$AZDO" == on ]]; then
    echo "Azure DevOps opt-in (org: ${AZDO_ORG:-<detected or --org>}):"
    echo "  GET https://dev.azure.com/{org}/_apis/projects?api-version=7.1"
    echo "  GET https://dev.azure.com/{org}/{project}/_apis/git/repositories?api-version=7.1"
    echo "  GET .../repositories/{repo}/commits?searchCriteria.fromDate=<${AZDO_DAYS}d ago>   # paged"
    echo
  fi
  if (( M365 )); then
    echo "Microsoft 365 opt-in (hands off to PowerShell; not reimplemented in bash):"
    echo "  pwsh -File wiz-365.ps1   # device-code auth + self-cleaning temporary Entra app"
    echo
  fi
  echo "Output: $OUTPUT_FILE, $OUTPUT_FILE_LOG$( [[ "$MODE" != cloud ]] && printf '%s' ', azure-defend-log-volume-<timestamp>.csv' ) in $OUTPUT_DIR"
  echo "dry-run complete — no cloud calls were made."
}

####
# Cloud counting — accurate (ARM REST), one worker per subscription
####

emit_count() { # $1 key, $2 value, $3 counts file
  printf '%s=%s\n' "$1" "$2" >> "$3"
}

progress_count() { # $1 count, $2 label, $3 subscription name, $4 log file, $5 details
  local count="$1" label="$2" sub="$3" logf="$4" details="${5:-}"
  (( count > 0 )) || return 0
  status "- $(printf "%${PADDING}s" "$count") $label in $sub${details:+ $details}"
  csv_row "$label" "$count" "$sub" >> "$logf"
}

scan_sub_cloud_accurate() { # $1 sub id, $2 sub name, $3 tmp prefix
  local sub="$1" name="$2" prefix="$3"
  local counts="$prefix.counts" logf="$prefix.log"
  local base="https://management.azure.com/subscriptions/$sub"
  ERR_SINK="$prefix.errors"
  : > "$counts"; : > "$logf"

  local json n nonos linux

  # Virtual Machines [Compute] — skip scale-set members and Databricks-tagged
  # (reference azure-v2:536-591)
  json=$(arm_get_all "$base/providers/Microsoft.Compute/virtualMachines?api-version=2024-03-01") || true
  n=$(jq '[ .[] | select(.properties.virtualMachineScaleSet == null)
               | select((.tags.Vendor // "") != "Databricks") ] | length' <<<"$json")
  nonos=$(jq '[ .[] | select(.properties.virtualMachineScaleSet == null)
                    | select((.tags.Vendor // "") != "Databricks")
                    | (.properties.storageProfile.dataDisks // []) | length ] | add // 0' <<<"$json")
  linux=$(jq '[ .[] | select(.properties.virtualMachineScaleSet == null)
                    | select((.tags.Vendor // "") != "Databricks")
                    | select(.properties.osProfile.linuxConfiguration != null) ] | length' <<<"$json")
  emit_count 'Virtual Machines' "$n" "$counts"
  emit_count 'Non-OS Disks' "$nonos" "$counts"
  emit_count 'Virtual Machine Sensors' "$linux" "$counts"
  progress_count "$n" 'Virtual Machines [Compute]' "$name" "$logf" "with $nonos Non-OS Disks"

  # Virtual Machines [Scale Sets] — live instance enumeration (azure-v2:597-655)
  local ss_json ss_count=0 ss_nonos=0 ss_linux=0 ss_id ss_name ss_rg disks_per_vm inst_json c l
  ss_json=$(arm_get_all "$base/providers/Microsoft.Compute/virtualMachineScaleSets?api-version=2024-03-01") || true
  while IFS=$'\t' read -r ss_id ss_name disks_per_vm; do
    [[ -n "$ss_id" ]] || continue
    ss_rg=$(cut -d/ -f5 <<<"$ss_id")
    inst_json=$(arm_get_all "$base/resourceGroups/$ss_rg/providers/Microsoft.Compute/virtualMachineScaleSets/$ss_name/virtualMachines?api-version=2024-03-01") || true
    c=$(jq '[ .[] | select((.tags.Vendor // "") != "Databricks") ] | length' <<<"$inst_json")
    l=$(jq '[ .[] | select((.tags.Vendor // "") != "Databricks")
                  | select(.properties.osProfile.linuxConfiguration != null) ] | length' <<<"$inst_json")
    ss_count=$(( ss_count + c ))
    ss_linux=$(( ss_linux + l ))
    if [[ "$disks_per_vm" == none ]]; then
      # No scaling profile: VMs attached after deployment carry their own disks.
      c=$(jq '[ .[] | select((.tags.Vendor // "") != "Databricks")
                    | (.properties.storageProfile.dataDisks // []) | length ] | add // 0' <<<"$inst_json")
      ss_nonos=$(( ss_nonos + c ))
    else
      ss_nonos=$(( ss_nonos + disks_per_vm * c ))
    fi
  done < <(jq -r '.[] | [ .id, .name,
      (if .properties.virtualMachineProfile == null then "none"
       else ((.properties.virtualMachineProfile.storageProfile.dataDisks // []) | length | tostring) end)
    ] | @tsv' <<<"$ss_json")
  emit_count 'Virtual Machines' "$ss_count" "$counts"
  emit_count 'Non-OS Disks' "$ss_nonos" "$counts"
  emit_count 'Virtual Machine Sensors' "$ss_linux" "$counts"
  progress_count "$ss_count" 'Virtual Machines [Scale Sets]' "$name" "$logf" "with $ss_nonos Non-OS Disks"

  # Container Hosts — AKS agent pool sum (azure-v2:661-696)
  json=$(arm_get_all "$base/providers/Microsoft.ContainerService/managedClusters?api-version=2024-02-01") || true
  n=$(jq '[ .[] | (.properties.agentPoolProfiles // [])[] | (.count // 0) ] | add // 0' <<<"$json")
  emit_count 'Container Hosts' "$n" "$counts"
  emit_count 'Kubernetes Sensors' "$n" "$counts"
  progress_count "$n" 'Container Hosts' "$name" "$logf"

  # Serverless Functions — web sites + child functions of function apps (azure-v2:749-794)
  local site_rg site_name site_kind fn_count=0 fn_json
  json=$(arm_get_all "$base/providers/Microsoft.Web/sites?api-version=2023-12-01") || true
  n=$(jq 'length' <<<"$json")
  while IFS=$'\t' read -r site_rg site_name site_kind; do
    [[ -n "$site_name" ]] || continue
    [[ "$site_kind" == *functionapp* ]] || continue
    fn_json=$(arm_get_all "$base/resourceGroups/$site_rg/providers/Microsoft.Web/sites/$site_name/functions?api-version=2023-12-01") || true
    c=$(jq 'length' <<<"$fn_json")
    fn_count=$(( fn_count + c ))
  done < <(jq -r '.[] | [ (.id | split("/")[4]), .name, (.kind // "") ] | @tsv' <<<"$json")
  n=$(( n + fn_count ))
  emit_count 'Serverless Functions' "$n" "$counts"
  progress_count "$n" 'Serverless Functions [Web Apps]' "$name" "$logf"

  # Serverless Containers — ACI container groups (azure-v2:702-719)
  json=$(arm_get_all "$base/providers/Microsoft.ContainerInstance/containerGroups?api-version=2023-05-01") || true
  n=$(jq 'length' <<<"$json")
  emit_count 'Serverless Containers' "$n" "$counts"
  progress_count "$n" 'Serverless Containers [Azure Container Instances]' "$name" "$logf"

  # Serverless Containers — Container Apps (azure-v2:725-743)
  json=$(arm_get_all "$base/providers/Microsoft.App/containerApps?api-version=2024-03-01") || true
  n=$(jq 'length' <<<"$json")
  emit_count 'Serverless Containers' "$n" "$counts"
  emit_count 'Serverless Container Sensors' "$n" "$counts"
  progress_count "$n" 'Serverless Containers [Azure Container Apps]' "$name" "$logf"

  # Asset Metadata — Arc machines + Stack HCI clusters (azure-v2:1015-1056)
  json=$(arm_get_all "$base/providers/Microsoft.HybridCompute/machines?api-version=2022-12-27") || true
  n=$(jq 'length' <<<"$json")
  emit_count 'Asset Metadata' "$n" "$counts"
  progress_count "$n" 'Asset Metadata [Arc Machines]' "$name" "$logf"

  json=$(arm_get_all "$base/providers/Microsoft.AzureStackHCI/clusters?api-version=2023-08-01") || true
  n=$(jq 'length' <<<"$json")
  emit_count 'Asset Metadata' "$n" "$counts"
  progress_count "$n" 'Asset Metadata [Stack HCI Clusters]' "$name" "$logf"

  if (( DATA )); then
    # Data Buckets — blob containers via the ARM control plane, which bypasses
    # storage-account firewalls; Databricks-managed accounts skipped; 10000
    # containers/account cap (azure-v2:919-961)
    local acct_rg acct_name bucket_count=0 cont_json
    json=$(arm_get_all "$base/providers/Microsoft.Storage/storageAccounts?api-version=2023-01-01") || true
    while IFS=$'\t' read -r acct_rg acct_name; do
      [[ -n "$acct_name" ]] || continue
      cont_json=$(arm_get_all "$base/resourceGroups/$acct_rg/providers/Microsoft.Storage/storageAccounts/$acct_name/blobServices/default/containers?api-version=2023-01-01") || true
      c=$(jq 'length' <<<"$cont_json")
      (( c > 10000 )) && c=10000
      bucket_count=$(( bucket_count + c ))
    done < <(jq -r '.[] | select((.tags.application // "") != "Databricks")
                        | select((.tags["databricks-environment"] // "") != "true")
                        | [ (.id | split("/")[4]), .name ] | @tsv' <<<"$json")
    emit_count 'Data Buckets' "$bucket_count" "$counts"
    progress_count "$bucket_count" 'Data Buckets [Storage Containers]' "$name" "$logf"

    # PaaS Databases — Azure SQL, excluding master (azure-v2:967-1008)
    local srv_rg srv_name db_count=0 db_json
    json=$(arm_get_all "$base/providers/Microsoft.Sql/servers?api-version=2021-11-01") || true
    while IFS=$'\t' read -r srv_rg srv_name; do
      [[ -n "$srv_name" ]] || continue
      db_json=$(arm_get_all "$base/resourceGroups/$srv_rg/providers/Microsoft.Sql/servers/$srv_name/databases?api-version=2021-11-01") || true
      c=$(jq '[ .[] | select(.name != "master") ] | length' <<<"$db_json")
      db_count=$(( db_count + c ))
    done < <(jq -r '.[] | [ (.id | split("/")[4]), .name ] | @tsv' <<<"$json")
    emit_count 'PaaS Databases' "$db_count" "$counts"
    progress_count "$db_count" 'PaaS Databases [SQL]' "$name" "$logf"
  fi

  if (( IMAGES )); then
    # Registry Container Images — min(MAX_IMAGE_TAGS, tag count) per repository,
    # via az acr (the official script's Cloud Shell path, azure-v2:846-877)
    local registry repos repo tags img_count=0
    json=$(arm_get_all "$base/providers/Microsoft.ContainerRegistry/registries?api-version=2023-07-01") || true
    while IFS= read -r registry; do
      [[ -n "$registry" ]] || continue
      if ! repos=$(az acr repository list --name "$registry" --output tsv 2>/dev/null); then
        err "Subscription: $name az acr repository list failed for registry $registry"
        continue
      fi
      while IFS= read -r repo; do
        [[ -n "$repo" ]] || continue
        if ! tags=$(az acr repository show-tags --name "$registry" --repository "$repo" --query 'length(@)' --output tsv 2>/dev/null); then
          err "Subscription: $name az acr show-tags failed for $registry/$repo"
          continue
        fi
        [[ "$tags" =~ ^[0-9]+$ ]] || tags=0
        (( tags < 1 )) && tags=1
        (( tags > MAX_IMAGE_TAGS )) && tags=$MAX_IMAGE_TAGS
        img_count=$(( img_count + tags ))
      done <<<"$repos"
    done < <(jq -r '.[].name' <<<"$json")
    emit_count 'Registry Container Images' "$img_count" "$counts"
    progress_count "$img_count" 'Registry Container Images [ACR]' "$name" "$logf"
  fi

  ERR_SINK=''
}

####
# Cloud counting — fast (Resource Graph aggregations; deviations D3-D5)
####

arg_scalar() { # $1 sub, $2 kql, $3 jq path for the scalar → integer (0 on miss);
               # status 1 when the ARG query itself failed (≠ a real zero)
  local out
  out=$(arg_query "$1" "$2") || return 1
  out=$(jq -r "first | $3 // 0" <<<"$out" 2>/dev/null) || out=0
  [[ "$out" =~ ^[0-9]+$ ]] || out=0
  printf '%s' "$out"
}

scan_sub_cloud_fast() { # $1 sub id, $2 sub name, $3 tmp prefix
  # Fast is best-effort, never silently zero (§7): any ARG failure discards
  # the partial fast counts and reruns this subscription on the accurate path.
  local sub="$1" name="$2" prefix="$3"
  if ! scan_sub_cloud_fast_try "$sub" "$name" "$prefix"; then
    status "[FALLBACK] Subscription $name: Resource Graph unavailable — accurate path (§7)"
    scan_sub_cloud_accurate "$sub" "$name" "$prefix"
  fi
}

scan_sub_cloud_fast_try() { # $1 sub id, $2 sub name, $3 tmp prefix; 1 on any ARG failure
  local sub="$1" name="$2" prefix="$3"
  local counts="$prefix.counts" logf="$prefix.log"
  ERR_SINK="$prefix.errors"
  : > "$counts"; : > "$logf"

  local n nonos

  # VMs + non-OS disks — official --graph queries (azure-v2:544-560)
  n=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.compute/virtualmachines"
    | where tags.Vendor != '\''Databricks'\''
    | summarize count()' '.count_') || return 1
  nonos=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.compute/virtualmachines"
    | where tags.Vendor != '\''Databricks'\''
    | project non_os_disks_count = iff(isnotempty(properties.storageProfile.dataDisks), array_length(properties.storageProfile.dataDisks), 0)
    | summarize sum(non_os_disks_count)' '.sum_non_os_disks_count') || return 1
  emit_count 'Virtual Machines' "$n" "$counts"
  emit_count 'Non-OS Disks' "$nonos" "$counts"
  progress_count "$n" 'Virtual Machines [Compute]' "$name" "$logf" "with $nonos Non-OS Disks"

  # Scale Set VMs — configured capacity, not live instances (D3)
  n=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.compute/virtualmachinescalesets"
    | summarize total = sum(toint(sku.capacity))' '.total') || return 1
  emit_count 'Virtual Machines' "$n" "$counts"
  progress_count "$n" 'Virtual Machines [Scale Sets]' "$name" "$logf" '(configured capacity, D3)'

  # AKS agent pool sum — official --graph query (azure-v2:667-673)
  n=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.containerservice/managedclusters"
    | mv-expand pool = properties.agentPoolProfiles
    | summarize aks_instances_count = sum(toint(pool["count"]))
    | project sum_aks_instances_count = aks_instances_count' '.sum_aks_instances_count') || return 1
  emit_count 'Container Hosts' "$n" "$counts"
  emit_count 'Kubernetes Sensors' "$n" "$counts"
  progress_count "$n" 'Container Hosts [AKS]' "$name" "$logf"

  # Web sites + static sites — no child functions in the index (D4)
  local sites static
  sites=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.web/sites"
    | summarize count()' '.count_') || return 1
  static=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.web/staticsites"
    | summarize count()' '.count_') || return 1
  n=$(( sites + static ))
  emit_count 'Serverless Functions' "$n" "$counts"
  progress_count "$n" 'Serverless Functions [Web Apps]' "$name" "$logf" '(sites only, D4)'

  # ACI + Container Apps + Arc + Stack HCI — index count() (PLAN §7)
  n=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.containerinstance/containergroups"
    | summarize count()' '.count_') || return 1
  emit_count 'Serverless Containers' "$n" "$counts"
  progress_count "$n" 'Serverless Containers [Azure Container Instances]' "$name" "$logf"

  n=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.app/containerapps"
    | summarize count()' '.count_') || return 1
  emit_count 'Serverless Containers' "$n" "$counts"
  emit_count 'Serverless Container Sensors' "$n" "$counts"
  progress_count "$n" 'Serverless Containers [Azure Container Apps]' "$name" "$logf"

  n=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.hybridcompute/machines"
    | summarize count()' '.count_') || return 1
  emit_count 'Asset Metadata' "$n" "$counts"
  progress_count "$n" 'Asset Metadata [Arc Machines]' "$name" "$logf"

  n=$(arg_scalar "$sub" 'resources
    | where type == "microsoft.azurestackhci/clusters"
    | summarize count()' '.count_') || return 1
  emit_count 'Asset Metadata' "$n" "$counts"
  progress_count "$n" 'Asset Metadata [Stack HCI Clusters]' "$name" "$logf"

  if (( DATA )); then
    # SQL databases are index-visible; buckets are data-plane and stay pending (D5)
    n=$(arg_scalar "$sub" 'resources
      | where type == "microsoft.sql/servers/databases"
      | summarize count()' '.count_') || return 1
    emit_count 'PaaS Databases' "$n" "$counts"
    progress_count "$n" 'PaaS Databases [SQL]' "$name" "$logf"
    status "- Data Buckets pending in $name: the index cannot see the data plane (D5); rerun without --fast"
  fi
  if (( IMAGES )); then
    status "- Registry Container Images pending in $name: data plane not indexed (D5); rerun without --fast"
  fi

  ERR_SINK=''
}

####
# Defend — Log Analytics discovery + KQL (port of log-volume-estimation-azure.py)
####

# Discovered workspaces accumulate as "guid<TAB>name" lines in $1.
defend_workspaces_from_settings() { # $1 out file, $2 diagnosticSettings URL
  local url="$2" json rid guid wname detail
  json=$(http_request GET "$ARM_AUDIENCE" "$url" '') || return 0
  while IFS= read -r rid; do
    [[ -n "$rid" ]] || continue
    detail=$(http_request GET "$ARM_AUDIENCE" "https://management.azure.com${rid}?api-version=2020-08-01" '') || continue
    guid=$(jq -r '.properties.customerId // empty' <<<"$detail")
    wname=$(jq -r '.name // empty' <<<"$detail")
    [[ -n "$guid" && -n "$wname" ]] && printf '%s\t%s\n' "$guid" "$wname" >> "$1"
  done < <(jq -r '.value[]?.properties.workspaceId // empty' <<<"$json" | sort -u)
}

defend_gb_30day() { # $1 raw amount, $2 unit divisor expr (awk), $3 days → "X.YZ" GB string
  awk -v amt="$1" -v days="$3" "BEGIN { if (days <= 0) { printf \"0.00\"; exit }
    gb = amt / $2; printf \"%.2f\", gb / days * 30 }"
}

# Appends result lines "gb|name|category|workspace_name|scope_sub" to $RESULTS_FILE.
defend_analyze_workspace() { # $1 guid, $2 name, $3 scope sub id ('tenant' or sub id)
  local guid="$1" wname="$2" scope="$3"
  local start end timespan resp gb
  end=$(utc_now_iso)
  start=$(utc_days_ago_iso "$DEFEND_DAYS")
  timespan="$start/$end"
  ERR_SINK="$DEFEND_ERRORS"

  local types_filter='' dt
  for dt in "${DEFEND_TYPE_KEYS[@]}"; do types_filter+="\"$dt\", "; done
  types_filter=${types_filter%, }

  status "  analyzing workspace $wname"

  # 1. Usage table — billable volume per relevant DataType (defend-azure:413-418)
  local usage_kql="Usage
| where TimeGenerated >= datetime($start) and TimeGenerated < datetime($end)
| where IsBillable == true and DataType in ($types_filter)
| summarize IngestedMB = sum(Quantity) by DataType"
  local found_types=()
  resp=$(la_query "$guid" "$usage_kql" "$timespan") || resp=''
  if [[ -n "$resp" ]]; then
    local row mb info
    while IFS=$'\t' read -r dt mb; do
      [[ -n "$dt" ]] || continue
      found_types+=("$dt")
      gb=$(defend_gb_30day "$mb" '1024' "$DEFEND_DAYS")
      info=$(defend_type_info "$dt")
      printf '%s|%s|%s|%s|%s\n' "$gb" "${info%%|*}" "${info##*|}" "$wname" "$scope" >> "$RESULTS_FILE"
    done < <(jq -r '(.tables[0].columns | map(.name)) as $c
      | .tables[0].rows[]?
      | [ .[$c | index("DataType")], (.[$c | index("IngestedMB")] // 0) ] | @tsv' <<<"$resp" 2>/dev/null)
    row=''
    : "$row"
  else
    err "Usage query failed for workspace $wname ($guid)"
  fi

  local have
  in_found() { for have in "${found_types[@]:-}"; do [[ "$have" == "$1" ]] && return 0; done; return 1; }

  # 2. AzureActivity direct fallback (defend-azure:491-522)
  if ! in_found AzureActivity; then
    local act_kql="AzureActivity
| where TimeGenerated >= datetime($start) and TimeGenerated < datetime($end)
| summarize EstimatedBytes = sum(estimate_data_size(*))"
    resp=$(la_query "$guid" "$act_kql" "$timespan") || resp=''
    local bytes
    bytes=$(jq -r '.tables[0].rows[0][0] // 0' <<<"$resp" 2>/dev/null) || bytes=0
    if awk -v b="${bytes:-0}" 'BEGIN{exit !(b > 0)}'; then
      gb=$(defend_gb_30day "$bytes" '(1024*1024*1024)' "$DEFEND_DAYS")
      printf '%s|Azure Activity Logs|Management|%s|%s\n' "$gb" "$wname" "$scope" >> "$RESULTS_FILE"
    fi
  fi

  # 3. StorageBlobLogs direct fallback (defend-azure:524-555)
  local have_blob=0
  in_found StorageBlobLogs && have_blob=1
  if (( ! have_blob )); then
    local blob_kql="StorageBlobLogs
| where TimeGenerated >= datetime($start) and TimeGenerated < datetime($end)
| summarize EstimatedBytes = sum(estimate_data_size(*))"
    resp=$(la_query "$guid" "$blob_kql" "$timespan") || resp=''
    local bytes
    bytes=$(jq -r '.tables[0].rows[0][0] // 0' <<<"$resp" 2>/dev/null) || bytes=0
    if awk -v b="${bytes:-0}" 'BEGIN{exit !(b > 0)}'; then
      gb=$(defend_gb_30day "$bytes" '(1024*1024*1024)' "$DEFEND_DAYS")
      printf '%s|Azure Storage Blob Logs|Data|%s|%s\n' "$gb" "$wname" "$scope" >> "$RESULTS_FILE"
      have_blob=1
    fi
  fi

  # 4. AzureDiagnostics for providers still missing (defend-azure:445-489)
  local providers=()
  if ! in_found AZMSKeyVaultAuditLogs && ! in_found AZKVAuditLogs; then
    providers+=('MICROSOFT.KEYVAULT')
  fi
  (( have_blob )) || providers+=('MICROSOFT.STORAGE')
  if (( ${#providers[@]} )); then
    local pf='' p
    for p in "${providers[@]}"; do pf+="\"$p\", "; done
    pf=${pf%, }
    local diag_kql="AzureDiagnostics
| where TimeGenerated >= datetime($start) and TimeGenerated < datetime($end)
| where ResourceProvider in ($pf)
| summarize EstimatedBytes = sum(estimate_data_size(*)) by ResourceProvider"
    resp=$(la_query "$guid" "$diag_kql" "$timespan") || resp=''
    local provider bytes pname
    while IFS=$'\t' read -r provider bytes; do
      [[ -n "$provider" ]] || continue
      awk -v b="${bytes:-0}" 'BEGIN{exit !(b > 0)}' || continue
      gb=$(defend_gb_30day "$bytes" '(1024*1024*1024)' "$DEFEND_DAYS")
      pname="${provider/MICROSOFT./} Logs (from AzureDiagnostics)"
      printf '%s|%s|Data|%s|%s\n' "$gb" "$pname" "$wname" "$scope" >> "$RESULTS_FILE"
    done < <(jq -r '(.tables[0].columns | map(.name)) as $c
      | .tables[0].rows[]?
      | [ .[$c | index("ResourceProvider")], (.[$c | index("EstimatedBytes")] // 0) ] | @tsv' <<<"$resp" 2>/dev/null)
  fi

  ERR_SINK=''
}

run_defend() { # $1.. = "sub_id<TAB>sub_name" lines (already enumerated)
  local subs=("$@")
  RESULTS_FILE="$TMP_DIR/defend.results"
  local processed="$TMP_DIR/defend.processed"
  touch "$RESULTS_FILE" "$processed"

  status "Defend: discovering Log Analytics workspaces via diagnostic settings"

  local ws_file="$TMP_DIR/defend.workspaces" guid wname

  # Tenant-level (Entra ID) settings — analyzed once, scope 'tenant'
  if ! (( RESUME )) || ! grep -q '^tenantdone$' "$processed"; then
    : > "$ws_file"
    defend_workspaces_from_settings "$ws_file" \
      'https://management.azure.com/providers/microsoft.aadiam/providers/Microsoft.Insights/diagnosticSettings?api-version=2017-04-01-preview'
    while IFS=$'\t' read -r guid wname; do
      [[ -n "$guid" ]] || continue
      grep -q "^$guid\$" "$processed" && continue
      echo "$guid" >> "$processed"
      defend_analyze_workspace "$guid" "$wname" 'tenant'
    done < "$ws_file"
    echo 'tenantdone' >> "$processed"
  fi

  # Management-group settings — merged into every subscription's set
  local mg_file="$TMP_DIR/defend.mg" mg json
  : > "$mg_file"
  json=$(http_request GET "$ARM_AUDIENCE" 'https://management.azure.com/providers/Microsoft.Management/managementGroups?api-version=2020-05-01' '') || json='{}'
  while IFS= read -r mg; do
    [[ -n "$mg" ]] || continue
    defend_workspaces_from_settings "$mg_file" \
      "https://management.azure.com/providers/Microsoft.Management/managementGroups/$mg/providers/Microsoft.Insights/diagnosticSettings?api-version=2021-05-01-preview"
  done < <(jq -r '.value[]?.name // empty' <<<"$json")

  # Per-subscription settings + management-group workspaces
  local line sub name found_any=0
  for line in "${subs[@]}"; do
    sub=${line%%$'\t'*}; name=${line#*$'\t'}
    if (( RESUME )) && grep -q "^subdone $sub\$" "$processed"; then
      status "Defend: skipping $name (resumed)"
      continue
    fi
    status "Defend: subscription $name"
    : > "$ws_file"
    defend_workspaces_from_settings "$ws_file" \
      "https://management.azure.com/subscriptions/$sub/providers/Microsoft.Insights/diagnosticSettings?api-version=2021-05-01-preview"
    cat "$mg_file" >> "$ws_file" 2>/dev/null || true
    while IFS=$'\t' read -r guid wname; do
      [[ -n "$guid" ]] || continue
      grep -q "^$guid\$" "$processed" && continue
      echo "$guid" >> "$processed"
      found_any=1
      defend_analyze_workspace "$guid" "$wname" "$sub"
    done < <(sort -u "$ws_file")
    echo "subdone $sub" >> "$processed"
  done

  # Explicit workspaces supplement discovery (PLAN §4)
  if [[ -n "$DEFEND_WORKSPACES" ]]; then
    local extra
    IFS=',' read -ra extra <<<"$DEFEND_WORKSPACES"
    for guid in "${extra[@]}"; do
      [[ -n "$guid" ]] || continue
      grep -q "^$guid\$" "$processed" && continue
      echo "$guid" >> "$processed"
      found_any=1
      defend_analyze_workspace "$guid" "$guid" 'explicit'
    done
  fi

  if (( ! found_any )) && [[ ! -s "$RESULTS_FILE" ]]; then
    status "Defend: no log sources found — pass --defend-workspace GUID to query a workspace directly. Continuing."
  fi
}

write_defend_output() {
  [[ -n "${RESULTS_FILE:-}" && -f "$RESULTS_FILE" ]] || return 0
  local stamp csv_file
  stamp=$(date +%Y%m%d-%H%M%S)
  csv_file="$OUTPUT_DIR/azure-defend-log-volume-$stamp.csv"

  {
    csv_row 'Log Source Type' 'Billable Category' 'Specific Metric' 'Resource/Scope Details' 'Estimated 30-Day Uncompressed Volume (GB)'
    local gb lname cat wname scope details
    while IFS='|' read -r gb lname cat wname scope; do
      [[ -n "$lname" ]] || continue
      # Entra ID rows are tenant-wide, like the official script (defend-azure:638-639)
      if [[ "$lname" == 'Entra ID'* ]]; then
        details="Tenant-wide / Workspace: $wname"
      else
        details="Subscription: $scope / Workspace: $wname"
      fi
      csv_row 'Azure Log Analytics' "$cat Logs Ingestion GB" "$lname" "$details" "$gb"
    done < <(sort -t'|' -k1,1gr "$RESULTS_FILE")
  } > "$csv_file"

  # Summary block — category totals then overall, like the official output
  local total mgmt idnt data
  total=$(awk -F'|' '{ s += $1 } END { printf "%.2f", s }' "$RESULTS_FILE")
  mgmt=$(awk -F'|' '$3=="Management" { s += $1 } END { printf "%.2f", s+0 }' "$RESULTS_FILE")
  idnt=$(awk -F'|' '$3=="Identity"   { s += $1 } END { printf "%.2f", s+0 }' "$RESULTS_FILE")
  data=$(awk -F'|' '$3=="Data"       { s += $1 } END { printf "%.2f", s+0 }' "$RESULTS_FILE")

  echo
  echo "Wiz Defend Ingestion: Azure Log Volume Estimation (Uncompressed, Normalized to 30 days)"
  echo "Time period: Last $DEFEND_DAYS days (results extrapolated to 30-day volume)"
  echo
  echo "  Management Logs Ingestion GB : $mgmt"
  echo "  Identity Logs Ingestion GB   : $idnt"
  echo "  Data Logs Ingestion GB       : $data"
  echo "  Total Estimated 30-Day Volume: $total GB"
  awk -v t="$total" 'BEGIN { printf "  Average Daily Volume         : %.2f GB\n", t / 30 }'
  echo
  echo "Defend details written to $csv_file"
}

####
# Azure DevOps opt-in
####

azdo_detect_org() {
  if [[ -n "$AZDO_ORG" ]]; then printf '%s' "$AZDO_ORG"; return 0; fi
  local org
  org=$(az devops configure -l 2>/dev/null | sed -n 's/^organization *= *//p' | head -1)
  [[ -n "$org" ]] && printf '%s' "$org"
}

azdo_org_base_url() { # name or URL → https URL (ado:448-453)
  local org="${1%%/}"
  if [[ "$org" == http://* || "$org" == https://* ]]; then printf '%s' "$org"
  else printf 'https://dev.azure.com/%s' "$org"; fi
}

azdo_request() { # $1 url → body
  http_request GET "$AZDO_AUDIENCE" "$1" ''
}

run_azdo() { # $1 = org (name or URL)
  local base org_display from_date
  base=$(azdo_org_base_url "$1")
  org_display=${base##*/}
  from_date=$(utc_days_ago_iso "$AZDO_DAYS")
  ERR_SINK="$GLOBAL_ERRORS"

  status "Azure DevOps: counting developers active since $from_date in $org_display"

  local devs_file="$TMP_DIR/azdo.devs" repo_log="$TMP_DIR/azdo.log"
  : > "$devs_file"; : > "$repo_log"

  # Projects — $top/$skip paged (ado:575-578)
  local skip=0 page count projects='[]'
  while :; do
    page=$(azdo_request "$base/_apis/projects?api-version=7.1&\$top=100&\$skip=$skip") || break
    count=$(jq '.value | length' <<<"$page" 2>/dev/null) || count=0
    (( count == 0 )) && break
    projects=$(jq -c --argjson acc "$projects" '$acc + .value' <<<"$page")
    (( count < 100 )) && break
    skip=$(( skip + 100 ))
  done

  local proj_id proj_name repos repo_id repo_name
  while IFS=$'\t' read -r proj_id proj_name; do
    [[ -n "$proj_id" ]] || continue
    status "  project $proj_name"
    repos=$(azdo_request "$base/$proj_id/_apis/git/repositories?api-version=7.1") || { csv_row "$org_display" "$proj_name" '' 0 0 'failed' 'repository list failed' >> "$repo_log"; continue; }
    while IFS=$'\t' read -r repo_id repo_name; do
      [[ -n "$repo_id" ]] || continue
      # Commits since from_date — distinct author emails (ado:604-694)
      local cskip=0 ccount commits_scanned=0 repo_devs status_val='scanned' error_val=''
      local repo_devs_file="$TMP_DIR/azdo.repo.devs"
      : > "$repo_devs_file"
      while :; do
        page=$(azdo_request "$base/$proj_id/_apis/git/repositories/$repo_id/commits?searchCriteria.fromDate=$from_date&searchCriteria.\$top=500&searchCriteria.\$skip=$cskip&api-version=7.1") || { status_val='failed'; error_val='commit query failed'; break; }
        ccount=$(jq '.value | length' <<<"$page" 2>/dev/null) || ccount=0
        (( ccount == 0 )) && break
        commits_scanned=$(( commits_scanned + ccount ))
        jq -r '.value[]?.author.email // empty' <<<"$page" \
          | tr '[:upper:]' '[:lower:]' | sed 's/^ *//; s/ *$//; s/^"//; s/"$//' \
          | grep -v '^$' >> "$repo_devs_file" || true
        (( ccount < 500 )) && break
        cskip=$(( cskip + 500 ))
      done
      repo_devs=$(sort -u "$repo_devs_file" | grep -c . || true)
      sort -u "$repo_devs_file" >> "$devs_file"
      csv_row "$org_display" "$proj_name" "$repo_name" "$repo_devs" "$commits_scanned" "$status_val" "$error_val" >> "$repo_log"
      status "    $repo_name: $repo_devs developers across $commits_scanned commits"
    done < <(jq -r '.value[] | [ .id, .name ] | @tsv' <<<"$repos")
  done < <(jq -r '.[] | [ .id, .name ] | @tsv' <<<"$projects")

  # Output — hashed developer file + per-repo log (ado:705-720)
  local slug="${org_display//[^[:alnum:]]/}"
  local dev_out="$OUTPUT_DIR/azure_devops-$slug-developers.txt"
  local log_out="$OUTPUT_DIR/azure_devops-$slug-developers-log.txt"
  local email total=0
  : > "$dev_out"
  while IFS= read -r email; do
    [[ -n "$email" ]] || continue
    sha256_hex "$email" >> "$dev_out"
    total=$(( total + 1 ))
  done < <(sort -u "$devs_file")
  {
    csv_row 'Organization' 'Project' 'Repository' "Developers (Last $AZDO_DAYS Days)" 'Commits Scanned' 'Status' 'Error'
    cat "$repo_log"
  } > "$log_out"

  # Cross-VCS rollup — union of *-developers.txt (ado:481-495)
  local rollup="$OUTPUT_DIR/active-developers.txt" f
  : > "$TMP_DIR/azdo.rollup"
  for f in "$OUTPUT_DIR"/*-developers.txt; do
    [[ -f "$f" && "$(basename "$f")" != 'active-developers.txt' ]] || continue
    cat "$f" >> "$TMP_DIR/azdo.rollup"
  done
  : > "$rollup"
  while IFS= read -r email; do
    [[ -n "$email" ]] || continue
    sha256_hex "$email" >> "$rollup"
  done < <(sort -u "$TMP_DIR/azdo.rollup")

  echo
  echo "Azure DevOps: $total developers active in the last $AZDO_DAYS days in $org_display"
  echo "Details written to $dev_out and $log_out"
  ERR_SINK=''
}

maybe_run_azdo() {
  case "$AZDO" in
    off) return 0 ;;
    on)
      local org
      org=$(azdo_detect_org)
      if [[ -z "$org" ]]; then
        err "Azure DevOps requested but no organization given — pass --org ORG"
        return 1
      fi
      run_azdo "$org"
      ;;
    auto)
      local org
      org=$(azdo_detect_org) || true
      [[ -n "$org" ]] || return 0
      # Detected an org: prompt, defaulting to skip after 30s so unattended
      # runs are never blocked (PLAN §5 / R4).
      local answer=''
      if ! read -r -t 30 -p "Azure DevOps organization '$org' detected. Include repo/developer counting? [y/N] " answer; then
        echo
        status 'Azure DevOps: no answer within 30s — skipping (rerun with --azdo to include)'
        return 0
      fi
      case "$answer" in
        y|Y|yes|YES) run_azdo "$org" ;;
        *) status 'Azure DevOps: skipped' ;;
      esac
      ;;
  esac
}

####
# M365 opt-in — hand off to the PowerShell script (PLAN §5, §10)
####

run_m365() {
  local script_dir local_ps1 url='https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-365.ps1'
  script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd) || script_dir=''
  local_ps1="$script_dir/wiz-365.ps1"
  echo
  echo 'Microsoft 365 sizing runs as PowerShell (device-code auth + a self-cleaning'
  echo 'temporary Entra app for accurate Graph counts) — see wiz-365.ps1.'
  if command -v pwsh >/dev/null 2>&1; then
    if [[ -n "$script_dir" && -f "$local_ps1" ]]; then
      status 'M365: running local wiz-365.ps1 via pwsh'
      pwsh -File "$local_ps1"
    else
      status 'M365: fetching and running wiz-365.ps1 via pwsh'
      local tmp_ps1="$TMP_DIR/wiz-365.ps1"
      if curl -sSL "$url" -o "$tmp_ps1"; then
        pwsh -File "$tmp_ps1"
      else
        err 'M365: could not download wiz-365.ps1'
        echo "Run it yourself:  pwsh -c \"iex (irm $url)\""
      fi
    fi
  else
    echo 'pwsh is not available here. Run this in Azure Cloud Shell (PowerShell) instead:'
    echo "  iex (irm $url)"
  fi
}

####
# Output — cloud CSVs + summary block (single writer; §11, §12)
####

write_cloud_output() { # $1 = "partial" for interrupted runs
  local partial="${1:-}"
  declare -A totals
  local key f
  for key in "${TOTAL_KEYS[@]}"; do totals[$key]=0; done

  local subs_merged=0
  for f in "$TMP_DIR"/cloud.*.counts; do
    [[ -f "$f" ]] || continue
    subs_merged=$(( subs_merged + 1 ))
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
    csv_row 'Resource Type' 'Resource Count' 'Subscription'
    for f in "$TMP_DIR"/cloud.*.log; do
      [[ -f "$f" ]] || continue
      cat "$f"
    done
  } > "$OUTPUT_DIR/$OUTPUT_FILE_LOG"

  # Error rollup (§12): never silent
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

  # Summary block — mirrors the official one so the numbers map 1:1 onto the
  # billable-units calculator (azure-v2:1150-1199)
  local label='Results'
  [[ -n "$partial" ]] && label='Partial results'
  echo
  echo "$label across $subs_merged Azure Subscriptions (wiz-azure.sh version: $VERSION)"
  echo
  printf "%${PADDING}s Virtual Machines [Compute, Scale Sets]\n" "${totals['Virtual Machines']}"
  printf "%${PADDING}s Container Hosts [AKS]\n" "${totals['Container Hosts']}"
  printf "%${PADDING}s Serverless Functions [Web Apps]\n" "${totals['Serverless Functions']}"
  printf "%${PADDING}s Serverless Containers [Container Instances, Container Apps]\n" "${totals['Serverless Containers']}"
  printf "%${PADDING}s Asset Metadata [Arc Machines, Stack HCI Clusters]\n" "${totals['Asset Metadata']}"
  if (( DATA )); then
    echo
    if (( FAST )); then
      printf "%${PADDING}s Data Buckets (Public and Private) [Storage Containers] (pending: rerun without --fast, D5)\n" 'n/a'
    else
      printf "%${PADDING}s Data Buckets (Public and Private) [Storage Containers]\n" "${totals['Data Buckets']}"
    fi
    printf "%${PADDING}s PaaS Databases [SQL]\n" "${totals['PaaS Databases']}"
  fi
  echo
  printf "%${PADDING}s Non-OS Disks [Compute]\n" "${totals['Non-OS Disks']}"
  if (( IMAGES )); then
    echo
    if (( FAST )); then
      printf "%${PADDING}s Registry Container Images [ACR] (pending: rerun without --fast, D5)\n" 'n/a'
    else
      printf "%${PADDING}s Registry Container Images [ACR]\n" "${totals['Registry Container Images']}"
    fi
  fi
  echo
  printf "%${PADDING}s (Potential) Kubernetes Sensors [Estimated from Platform]\n" "${totals['Kubernetes Sensors']}"
  printf "%${PADDING}s (Potential) Virtual Machine Sensors [Estimated from VM Platform *]\n" "${totals['Virtual Machine Sensors']}"
  printf "%${PADDING}s (Potential) Serverless Container Sensors [Container Apps]\n" "${totals['Serverless Container Sensors']}"
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
  [[ -n "$partial" ]] && echo 'Scan interrupted; results above cover completed subscriptions only.'
  return 0
}

####
# Scan orchestration — bounded parallelism, per-scope temp files, resume (§11)
####

enumerate_subscriptions() { # → "id<TAB>name" lines on stdout
  if [[ -n "$SUBSCRIPTION" ]]; then
    local detail
    detail=$(http_request GET "$ARM_AUDIENCE" "https://management.azure.com/subscriptions/$SUBSCRIPTION?api-version=2020-01-01" '') || return 1
    jq -r '[ .subscriptionId, .displayName ] | @tsv' <<<"$detail"
    return 0
  fi
  if [[ -n "$SUBSCRIPTIONS_FILE" ]]; then
    local id detail
    while IFS= read -r id; do
      id=$(tr -d '[:space:]' <<<"$id")
      [[ -n "$id" ]] || continue
      detail=$(http_request GET "$ARM_AUDIENCE" "https://management.azure.com/subscriptions/$id?api-version=2020-01-01" '') || { err "invalid subscription ID in $SUBSCRIPTIONS_FILE: $id"; continue; }
      jq -r '[ .subscriptionId, .displayName ] | @tsv' <<<"$detail"
    done < "$SUBSCRIPTIONS_FILE"
    return 0
  fi
  local json
  json=$(arm_get_all 'https://management.azure.com/subscriptions?api-version=2020-01-01') || return 1
  # Same filter as the official script (azure-v2:1238)
  jq -r '.[] | select(.state == "Enabled")
             | select(.displayName != "Access to Azure Active Directory")
             | [ .subscriptionId, .displayName ] | @tsv' <<<"$json"
}

wait_for_slot() {
  while (( $(jobs -rp | wc -l) >= MAX_PARALLEL )); do sleep 0.2; done
}

run_cloud() { # $@ = "id<TAB>name" lines
  local subs=("$@") line sub name idx=0
  local total=${#subs[@]}
  status "Cloud: scanning $total subscription(s) with up to $MAX_PARALLEL in parallel"
  for line in "${subs[@]}"; do
    sub=${line%%$'\t'*}; name=${line#*$'\t'}
    idx=$(( idx + 1 ))
    if (( RESUME )) && grep -q "^cloud $sub done\$" "$STATE_FILE" 2>/dev/null; then
      status "[SKIP] Subscription $idx/$total: $sub - $name (resumed)"
      continue
    fi
    status "[SCAN] Subscription $idx/$total: $sub - $name"
    wait_for_slot
    (
      if (( FAST )); then
        scan_sub_cloud_fast "$sub" "$name" "$TMP_DIR/cloud.$sub"
      else
        scan_sub_cloud_accurate "$sub" "$name" "$TMP_DIR/cloud.$sub"
      fi
      echo "cloud $sub done" >> "$STATE_FILE"
      status "[DONE] Subscription: $sub ($name)"
    ) &
  done
  wait
}

on_interrupt() {
  trap - INT TERM
  status '[INTERRUPTED] Writing partial results before exiting.'
  if [[ "$MODE" != defend ]]; then write_cloud_output partial; fi
  if [[ "$MODE" != cloud ]]; then write_defend_output; fi
  echo "Resume with: wiz-azure.sh $MODE --resume --output-dir $OUTPUT_DIR"
  exit 130
}

####
# Interactive menu (§4 — profiles first, then domains; numbered for web shells)
####

menu() {
  cat <<EOF

wiz-azure.sh v$VERSION — Wiz sizing for Azure

  1) Full sizing        cloud resources + Defend ingest (recommended)
  2) Full + data/images adds Buckets, PaaS DBs, ACR images (longer scan)
  3) Fast estimate      Resource Graph aggregations (D3-D5 apply)
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
      --subscription) SUBSCRIPTION="${2:?--subscription needs a value}"; shift 2 ;;
      --subscriptions-file) SUBSCRIPTIONS_FILE="${2:?--subscriptions-file needs a value}"; shift 2 ;;
      --days) DEFEND_DAYS="${2:?--days needs a value}"; shift 2 ;;
      --defend-workspace) DEFEND_WORKSPACES="${2:?--defend-workspace needs a value}"; shift 2 ;;
      --max-parallel) MAX_PARALLEL="${2:?--max-parallel needs a value}"; shift 2 ;;
      --max-image-tags) MAX_IMAGE_TAGS="${2:?--max-image-tags needs a value}"; shift 2 ;;
      --azdo) AZDO=on; shift ;;
      --no-azdo) AZDO=off; shift ;;
      --org) AZDO_ORG="${2:?--org needs a value}"; shift 2 ;;
      --azdo-days) AZDO_DAYS="${2:?--azdo-days needs a value}"; shift 2 ;;
      --m365) M365=1; shift ;;
      --print-csv-contract) print_csv_contract; exit 0 ;;
      --list) list_modes; exit 0 ;;
      --version) echo "wiz-azure.sh $VERSION"; exit 0 ;;
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
  TMP_DIR="$OUTPUT_DIR/.wiz-azure-tmp"
  STATE_FILE="$OUTPUT_DIR/.wiz-azure-state"
  if (( ! RESUME )); then
    rm -rf "$TMP_DIR"
    rm -f "$STATE_FILE"
  fi
  mkdir -p "$TMP_DIR"
  touch "$STATE_FILE"
  GLOBAL_ERRORS="$TMP_DIR/global.errors"
  DEFEND_ERRORS="$TMP_DIR/defend.errors"
  touch "$GLOBAL_ERRORS" "$DEFEND_ERRORS"

  trap on_interrupt INT TERM

  status "wiz-azure.sh v$VERSION — mode: $MODE$( ((FAST)) && printf ' (fast)' )"
  status 'Enumerating Azure subscriptions'
  local subs=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && subs+=("$line")
  done < <(enumerate_subscriptions)
  if (( ${#subs[@]} == 0 )); then
    echo 'No subscriptions found. Run az login (or pass --subscription ID).' >&2
    exit 1
  fi
  status "Found ${#subs[@]} subscription(s)"

  if [[ "$MODE" != defend ]]; then
    run_cloud "${subs[@]}"
  fi
  if [[ "$MODE" != cloud ]]; then
    run_defend "${subs[@]}"
  fi

  if [[ "$MODE" != defend ]]; then write_cloud_output; fi
  if [[ "$MODE" != cloud ]]; then
    write_defend_output
    if [[ -s "$DEFEND_ERRORS" ]]; then
      sort -u "$DEFEND_ERRORS" > "$OUTPUT_DIR/$DEFEND_ERROR_LOG_FILE"
      echo "Defend errors logged to $DEFEND_ERROR_LOG_FILE"
    fi
  fi

  # Opt-ins run last so the default scan is never delayed by them (§5)
  maybe_run_azdo || true
  (( M365 )) && run_m365

  # Full completion: clear resume bookkeeping
  rm -rf "$TMP_DIR"
  rm -f "$STATE_FILE"
  status 'Scan complete.'
}

# The Defend GB format is part of the CSV contract: %.2f (defend-azure:646).
main "$@"
