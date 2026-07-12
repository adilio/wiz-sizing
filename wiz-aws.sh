#!/usr/bin/env bash
# wiz-aws.sh — Wiz sizing for AWS: cloud resources + Defend ingest in one pass.
#
#   bash <(curl -sL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-aws.sh)
#
# Requires only what AWS CloudShell ships: bash 4+, aws CLI v2 (ambient
# credentials), jq. Counting logic reproduces the official Wiz sizing scripts
# (see reference/ and parity/mapping.md in the repo); output CSV filenames and
# headers are identical.
#
# Modes:   all (default) · cloud · defend
# Org:     --org scans every ACTIVE member account via sts assume-role
#          (--role-name, default OrganizationAccountAccessRole)
# Defend:  auto-discovers CloudTrail / VPC Flow / R53 Resolver log buckets;
#          --defend-*-bucket flags override, --defend-detailed samples S3.
#
# Everything is read-only.

set -uo pipefail

if (( BASH_VERSINFO[0] < 4 )); then
  echo "wiz-aws.sh needs bash 4+ (AWS CloudShell has it; on macOS use 'brew install bash')." >&2
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
ORG=0
ROLE_NAME='OrganizationAccountAccessRole'
ACCOUNTS_FILE=''
REGIONS=''              # comma-separated override
MAX_PARALLEL=8
MAX_IMAGE_TAGS=5
MAX_LAMBDA_VERSIONS=5

DEFEND_DETAILED=0
DEFEND_CT_BUCKET=''     # override/supplement discovery
DEFEND_CT_PREFIX='AWSLogs/'
DEFEND_VPC_BUCKET=''
DEFEND_R53_BUCKET=''
DEFEND_DAYS=30
DEFEND_SAMPLE_SIZE=200
DEFEND_CT_COMPRESSION='10.0'
DEFEND_VPC_COMPRESSION='10.0'
DEFEND_R53_COMPRESSION='10.0'
DEFEND_NO_DISCOVER=0

OUTPUT_FILE='aws-resources.csv'
OUTPUT_FILE_LOG='aws-resources-log.csv'
ERROR_LOG_FILE='aws-errors-log.txt'
DEFEND_OUTPUT_FILE='aws-defend-log-volume.csv'
DEFEND_ERROR_LOG_FILE='aws-defend-errors-log.txt'
PADDING=6

# CSV row order — matches the official totals dict exactly
# (reference/cloud/aws/resource-count-aws-v2.py:234-250).
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
Usage: wiz-aws.sh [MODE] [flags]

Estimate Wiz billable units for AWS. Default run counts cloud resources AND
estimates Wiz Defend log ingest, in one pass, using your ambient 'aws'
credentials (read-only).

Modes:
  all                 Cloud resources + Defend ingest (default)
  cloud               Cloud resources only
  defend              Defend ingest estimate only

Scope flags:
  --org               Scan every ACTIVE account in the AWS Organization via
                      sts assume-role (default: current account only)
  --role-name NAME    IAM role to assume in member accounts
                      (default: OrganizationAccountAccessRole)
  --accounts-file F   Scan the 12-digit account IDs listed in F (one per line);
                      implies assume-role for accounts other than the current
  --regions LIST      Comma-separated regions (default: all enabled regions)

Cloud flags:
  --fast              Fast estimate via AWS Resource Explorer where indexed;
                      per-dimension fallback to the accurate path when the
                      index is missing (deviation D6). Container hosts and
                      serverless containers always use the accurate path.
  --data              Also count Data Security resources (S3, RDS/Aurora/
                      DocumentDB/Redshift, DynamoDB)
  --images            Also count Registry Container Images (ECR)
  --max-image-tags N  Image tags counted per ECR repository (default: 5)
  --max-lambda-versions N
                      Versions counted per Lambda function (default: 5, 0 skips)

Defend flags (auto-discovery is the default — trails, VPC flow-log and R53
resolver query-log configs are found for you; flags override or supplement):
  --defend-cloudtrail-bucket B    CloudTrail logs bucket
  --defend-cloudtrail-prefix P    CloudTrail prefix (default: AWSLogs/)
  --defend-vpc-flow-bucket B      VPC Flow Logs bucket
  --defend-r53-bucket B           Route 53 Resolver Query Logs bucket
  --defend-no-discover            Skip auto-discovery; use only the flags above
  --defend-detailed               Sample and parse CloudTrail objects for a
                                  per-category breakdown (slower, minor S3
                                  API cost — same trade-off as the official)
  --defend-days N                 Days of logs to analyze, detailed mode (default: 30)
  --defend-sample-size N          Objects to sample, detailed mode (default: 200)
  --defend-compression-factor F   Assumed compression for basic mode (default: 10.0)

General:
  --resume            Resume an interrupted scan (per account+region checkpoints)
  --output-dir DIR    Directory for output CSVs (default: current directory)
  --max-parallel N    Concurrent scans (default: 8)
  --dry-run           Print the calls this run would make, then exit. Makes no
                      AWS calls and needs no credentials.
  --quiet             Suppress progress output
  --list              List modes and opt-in extras
  --version           Print version
  --help              This help

Output files (identical to the official Wiz sizing scripts):
  aws-resources.csv, aws-resources-log.csv, aws-errors-log.txt
  aws-defend-log-volume.csv, aws-defend-errors-log.txt

Known deviation (PLAN.md §9 D1): EKS nodes are counted exactly like the
official script (EC2 instances tagged kubernetes.io/cluster/<name>); only the
EKS-Fargate pod count differs — the official queries the Kubernetes API and
falls back to 1 per Fargate-profile cluster on any error; this script always
uses that documented fallback (pure shell has no k8s client).

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
  --data     S3 buckets, PaaS databases, DynamoDB      --images  ECR images
  --org      All ACTIVE org accounts via assume-role   --fast    Resource Explorer estimate
  --defend-detailed   CloudTrail S3 object sampling (per-category breakdown)
EOF
}

print_csv_contract() {
  # filename<TAB>header — pinned by tests/contract.bats against reference/.
  printf 'aws-resources.csv\tResource Type,Resource Count\n'
  printf 'aws-resources-log.csv\tResource Type,Resource Count,Account,Region\n'
  printf 'aws-defend-log-volume.csv\tLog Source Type,Billable Category,Specific Metric,Bucket/Prefix Details,Estimated 30-Day Uncompressed Volume (GB)\n'
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

date_ymd_days_ago() { # $1 days → "YYYY/MM/DD"
  local out
  if out=$(date -u -d "$1 days ago" +%Y/%m/%d 2>/dev/null); then
    printf '%s' "$out"
  else
    date -u -v-"$1"d +%Y/%m/%d
  fi
}

require_tools() {
  local missing=0 t
  for t in aws jq; do
    if ! command -v "$t" >/dev/null 2>&1; then
      echo "ERROR: '$t' not found. Run from AWS CloudShell, or install it." >&2
      missing=1
    fi
  done
  (( missing )) && exit 1
  return 0
}

emit_count() { printf '%s=%s\n' "$1" "$2" >> "$3"; }

progress_count() { # $1 count, $2 label, $3 account name, $4 region, $5 log file, $6 details
  local count="$1" label="$2" acct="$3" region="$4" logf="$5" details="${6:-}"
  (( count > 0 )) || return 0
  status "- $(printf "%${PADDING}s" "$count") $label in $region${details:+ $details}"
  csv_row "$label" "$count" "$acct" "$region" >> "$logf"
}

####
# Credentials — ambient for the current account, assume-role for members (§6)
####

# Creds files live in $TMP_DIR/creds.<account>. Ambient accounts get the
# sentinel 'ambient'; assumed accounts get exportable env + expiry + role arn
# so a worker can re-assume when the session nears expiry.

write_creds_file() { # $1 account id, $2 current account id
  local acct="$1" current="$2"
  local f="$TMP_DIR/creds.$acct"
  if [[ "$acct" == "$current" ]]; then
    echo 'ambient' > "$f"
    return 0
  fi
  assume_into_file "$acct" "$f"
}

assume_into_file() { # $1 account id, $2 creds file
  local acct="$1" f="$2" arn json
  arn="arn:aws:iam::${acct}:role/${ROLE_NAME}"
  if ! json=$(env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
      aws sts assume-role --role-arn "$arn" --role-session-name 'wiz-sizing' --output json 2>/dev/null); then
    err "Account: $acct cannot assume $arn — skipping account"
    return 1
  fi
  {
    jq -r '.Credentials |
      "export AWS_ACCESS_KEY_ID=\(.AccessKeyId)",
      "export AWS_SECRET_ACCESS_KEY=\(.SecretAccessKey)",
      "export AWS_SESSION_TOKEN=\(.SessionToken)"' <<<"$json"
    printf 'WIZ_ROLE_ACCOUNT=%s\n' "$acct"
    printf 'WIZ_CREDS_EXPIRY=%s\n' "$(( $(date +%s) + 3300 ))"
  } > "$f"
}

apply_creds() { # $1 account id — source creds in the CURRENT shell (worker subshell)
  local f="$TMP_DIR/creds.$1"
  [[ -f "$f" ]] || { err "Account: $1 no credentials file"; return 1; }
  if [[ "$(head -1 "$f")" == ambient ]]; then return 0; fi
  # shellcheck source=/dev/null
  source "$f"
  return 0
}

ensure_creds_fresh() { # $1 account id — re-assume when near expiry (PLAN §6/§11)
  local f="$TMP_DIR/creds.$1"
  [[ -f "$f" && "$(head -1 "$f")" != ambient ]] || return 0
  local exp
  exp=$(sed -n 's/^WIZ_CREDS_EXPIRY=//p' "$f")
  [[ "$exp" =~ ^[0-9]+$ ]] || return 0
  if (( $(date +%s) > exp - 300 )); then
    status "  refreshing assumed-role session for account $1"
    assume_into_file "$1" "$f" && apply_creds "$1"
  fi
  return 0
}

####
# Dry-run — prints the call plan; provably no AWS calls, no credentials needed
####

dry_run_plan() {
  echo "wiz-aws.sh v$VERSION — dry-run: the calls this run would make (none are made now)."
  echo
  if (( ORG )); then
    echo "Scope: all ACTIVE accounts in the AWS Organization"
    echo "  aws organizations describe-organization ; aws organizations list-accounts"
    echo "  aws sts assume-role --role-arn arn:aws:iam::{account}:role/$ROLE_NAME   # per member account,"
    echo "    re-assumed automatically when the session nears expiry"
  elif [[ -n "$ACCOUNTS_FILE" ]]; then
    echo "Scope: accounts listed in $ACCOUNTS_FILE (assume-role for non-current accounts)"
  else
    echo 'Scope: current account (ambient credentials)'
    echo '  aws sts get-caller-identity'
  fi
  if [[ -n "$REGIONS" ]]; then
    echo "Regions: $REGIONS"
  else
    echo '  aws ec2 describe-regions --no-all-regions ; aws lightsail get-regions'
  fi
  echo
  if [[ "$MODE" != defend ]]; then
    if (( FAST )); then
      echo 'Cloud resources (fast estimate — Resource Explorer where indexed, D6):'
      echo '  aws resource-explorer-2 search --query-string "resourcetype:ec2:instance"'
      echo '  aws resource-explorer-2 search --query-string "resourcetype:lambda:function"'
      (( DATA )) && {
        echo '  aws resource-explorer-2 search --query-string "resourcetype:s3:bucket"'
        echo '  aws resource-explorer-2 search --query-string "resourcetype:rds:db" / "resourcetype:rds:cluster"'
        echo '  aws resource-explorer-2 search --query-string "resourcetype:dynamodb:table"'
      }
      echo '  (per-dimension fallback to the accurate calls below if the index is absent)'
      echo '  Container hosts + serverless containers always use the accurate calls:'
      echo '  aws ecs list-clusters / list-container-instances ; aws eks list-clusters +'
      echo '  aws ec2 describe-instances --filters Name=tag-key,Values=kubernetes.io/cluster/{name}'
      (( IMAGES )) && echo '  Registry images stay pending under --fast (rerun without --fast)'
    else
      echo 'Cloud resources (accurate — aws CLI per account × region):'
      echo '  aws ec2 describe-instances                                # VMs, non-OS disks'
      echo '  aws lightsail get-instances                               # Lightsail regions only'
      echo '  aws ecs list-clusters ; list-container-instances          # ECS hosts'
      echo '  aws eks list-clusters ; aws ec2 describe-instances --filters tag-key=kubernetes.io/cluster/{name}'
      echo '  aws eks list-fargate-profiles                             # Fargate: 1/cluster fallback (D1)'
      echo '  aws lambda list-functions ; list-versions-by-function     # + versions (max '"$MAX_LAMBDA_VERSIONS"')'
      echo '  aws ecs list-tasks --launch-type FARGATE ; describe-tasks # serverless containers'
      echo '  aws sagemaker list-domains ; list-endpoints'
      (( DATA )) && {
        echo '  aws s3api list-buckets                                    # global, cap 10000'
        echo '  aws docdb describe-db-clusters ; aws rds describe-db-clusters (aurora engines)'
        echo '  aws rds describe-db-instances (mariadb/mysql/oracle/postgres/sqlserver engines)'
        echo '  aws redshift describe-clusters ; aws dynamodb list-tables (cap 10000)'
      }
      (( IMAGES )) && echo '  aws ecr describe-repositories ; list-images              # min('"$MAX_IMAGE_TAGS"', tags)/repo'
    fi
    echo
  fi
  if [[ "$MODE" != cloud ]]; then
    echo 'Defend ingest (metrics-based basic estimation by default):'
    if (( DEFEND_NO_DISCOVER )); then
      echo '  (auto-discovery disabled by --defend-no-discover)'
    else
      echo '  aws cloudtrail describe-trails                            # → S3 bucket/prefix'
      echo '  aws ec2 describe-flow-logs --filter Name=log-destination-type,Values=s3   # per region'
      echo '  aws route53resolver list-resolver-query-log-configs                       # per region'
    fi
    [[ -n "$DEFEND_CT_BUCKET" ]] && echo "  plus explicit CloudTrail bucket: $DEFEND_CT_BUCKET/$DEFEND_CT_PREFIX"
    [[ -n "$DEFEND_VPC_BUCKET" ]] && echo "  plus explicit VPC Flow bucket: $DEFEND_VPC_BUCKET"
    [[ -n "$DEFEND_R53_BUCKET" ]] && echo "  plus explicit R53 Resolver bucket: $DEFEND_R53_BUCKET"
    echo '  Per bucket: aws s3api get-bucket-location, then'
    echo '  aws cloudwatch get-metric-statistics AWS/S3 IncomingBytes (Sum, 30d)'
    echo '    fallback: BucketSizeBytes growth over ~30d (Average, daily)'
    if (( DEFEND_DETAILED )); then
      echo "  CloudTrail detailed mode: aws s3api list-objects-v2 (base-path + daily prefixes,"
      echo "    last $DEFEND_DAYS days), sample $DEFEND_SAMPLE_SIZE objects via aws s3api get-object,"
      echo '    gunzip + jq per-event categorization (Management Write/ReadOnly, S3 Data, Other)'
    fi
    echo '  If nothing is discoverable and no flags are given: one-line note, scan continues.'
    echo
  fi
  echo "Output: $OUTPUT_FILE, $OUTPUT_FILE_LOG$( [[ "$MODE" != cloud ]] && printf '%s' ", $DEFEND_OUTPUT_FILE" ) in $OUTPUT_DIR"
  echo 'dry-run complete — no AWS calls were made.'
}

####
# Cloud counting — accurate (aws CLI), one worker per account × region
####

aws_json() { # aws CLI wrapper: JSON out, errors recorded, '{}' on failure
  local out
  if out=$(aws "$@" --output json 2>/dev/null); then
    printf '%s' "${out:-\{\}}"
    return 0
  fi
  err "aws $* failed"
  printf '{}'
  return 1
}

scan_account_region() { # $1 acct id, $2 acct name, $3 region, $4 lightsail? (1/0), $5 tmp prefix
  local acct="$1" name="$2" region="$3" lightsail="$4" prefix="$5"
  local counts="$prefix.counts" logf="$prefix.log"
  ERR_SINK="$prefix.errors"
  : > "$counts"; : > "$logf"
  apply_creds "$acct" || { ERR_SINK=''; return 0; }

  local json n nonos linux

  # Virtual Machines [EC2] — skip terminated + Databricks-tagged; non-OS disks
  # = mappings whose VolumeId differs from the first mapping's (aws-v2:574-636)
  ensure_creds_fresh "$acct"
  json=$(aws_json ec2 describe-instances --region "$region") || true
  read -r n nonos linux < <(jq -r '
    [ .Reservations[]?.Instances[]?
      | select(.State.Name != "terminated")
      | select(( [ (.Tags // [])[] | select(.Key == "Vendor" and .Value == "Databricks") ] | length ) == 0)
    ] as $vms
    | [ ($vms | length),
        ([ $vms[] | ((.BlockDeviceMappings // []) as $m
            | if ($m | length) > 0 then ($m[0].Ebs.VolumeId) as $root
              | [ $m[] | select(.Ebs.VolumeId != $root) ] | length
              else 0 end) ] | add // 0),
        ([ $vms[] | select((.platform // "") == "LINUX_UNIX") ] | length)
      ] | @tsv' <<<"$json" | tr '\t' ' ')
  emit_count 'Virtual Machines' "${n:-0}" "$counts"
  emit_count 'Non-OS Disks' "${nonos:-0}" "$counts"
  emit_count 'Virtual Machine Sensors' "${linux:-0}" "$counts"
  progress_count "${n:-0}" 'Virtual Machines [EC2]' "$name" "$region" "$logf" "with ${nonos:-0} Non-OS Disks"

  # Virtual Machines [Lightsail] — Lightsail regions only (aws-v2:642-699)
  if (( lightsail )); then
    json=$(aws_json lightsail get-instances --region "$region") || true
    read -r n nonos linux < <(jq -r '
      [ .instances[]?
        | select(.resourceType == "Instance")
        | select(.state.name != "terminated")
      ] as $vms
      | [ ($vms | length),
          ([ $vms[] | [ (.hardware.disks // [])[]
              | select(.isSystemDisk != true) | select(.isAttached == true) ] | length ] | add // 0),
          ([ $vms[] | select((.platform // "") == "LINUX_UNIX") ] | length)
        ] | @tsv' <<<"$json" | tr '\t' ' ')
    emit_count 'Virtual Machines' "${n:-0}" "$counts"
    emit_count 'Non-OS Disks' "${nonos:-0}" "$counts"
    emit_count 'Virtual Machine Sensors' "${linux:-0}" "$counts"
    progress_count "${n:-0}" 'Virtual Machines [Lightsail]' "$name" "$region" "$logf" "with ${nonos:-0} Non-OS Disks"
  fi

  # Container Hosts [ECS] — container instances per cluster (aws-v2:705-745)
  ensure_creds_fresh "$acct"
  local cluster ecs_hosts=0 c
  json=$(aws_json ecs list-clusters --region "$region") || true
  while IFS= read -r cluster; do
    [[ -n "$cluster" ]] || continue
    c=$(aws_json ecs list-container-instances --cluster "$cluster" --region "$region" | jq '.containerInstanceArns | length') || c=0
    ecs_hosts=$(( ecs_hosts + c ))
  done < <(jq -r '.clusterArns[]?' <<<"$json")
  emit_count 'Container Hosts' "$ecs_hosts" "$counts"
  emit_count 'Kubernetes Sensors' "$ecs_hosts" "$counts"
  progress_count "$ecs_hosts" 'Container Hosts [ECS]' "$name" "$region" "$logf"

  # Container Hosts [EKS] — EC2 instances tagged kubernetes.io/cluster/<name>,
  # exactly like the official (aws-v2:751-801); Fargate pods use the official's
  # own no-k8s-access fallback of 1 per Fargate-profile cluster (D1)
  local eks_nodes=0 eks_fargate=0 profiles
  json=$(aws_json eks list-clusters --region "$region") || true
  while IFS= read -r cluster; do
    [[ -n "$cluster" ]] || continue
    c=$(aws_json ec2 describe-instances --region "$region" \
          --filters "Name=tag-key,Values=kubernetes.io/cluster/$cluster" \
        | jq '[ .Reservations[]?.Instances[]? | select(.State.Name != "terminated") ] | length') || c=0
    eks_nodes=$(( eks_nodes + c ))
    profiles=$(aws_json eks list-fargate-profiles --cluster-name "$cluster" --region "$region" \
        | jq '.fargateProfileNames | length') || profiles=0
    (( profiles > 0 )) && eks_fargate=$(( eks_fargate + 1 ))
  done < <(jq -r '.clusters[]?' <<<"$json")
  emit_count 'Container Hosts' "$eks_nodes" "$counts"
  emit_count 'Kubernetes Sensors' "$eks_nodes" "$counts"
  progress_count "$eks_nodes" 'Container Hosts [EKS]' "$name" "$region" "$logf"
  emit_count 'Serverless Containers' "$eks_fargate" "$counts"
  progress_count "$eks_fargate" 'Serverless Containers [EKS Fargate]' "$name" "$region" "$logf" '(1 per Fargate cluster, D1)'

  # Serverless Functions [Lambda] — functions + up to N versions each
  # (aws-v2:865-913; versions exclude $LATEST, min(N, count))
  ensure_creds_fresh "$acct"
  local fn_count fn arn versions total_versions=0
  json=$(aws_json lambda list-functions --region "$region") || true
  fn_count=$(jq '.Functions | length' <<<"$json")
  if (( MAX_LAMBDA_VERSIONS > 0 && fn_count > 0 )); then
    while IFS= read -r arn; do
      [[ -n "$arn" ]] || continue
      versions=$(aws_json lambda list-versions-by-function --function-name "$arn" \
          --max-items "$MAX_LAMBDA_VERSIONS" --region "$region" \
        | jq '[ .Versions[]? | select(.Version != "$LATEST") ] | length') || versions=0
      (( versions > MAX_LAMBDA_VERSIONS )) && versions=$MAX_LAMBDA_VERSIONS
      total_versions=$(( total_versions + versions ))
    done < <(jq -r '.Functions[]?.FunctionArn' <<<"$json")
  fi
  fn=$(( fn_count + total_versions ))
  emit_count 'Serverless Functions' "$fn" "$counts"
  progress_count "$fn" 'Serverless Functions [Lambda]' "$name" "$region" "$logf"

  # Serverless Containers [ECS Fargate] — containers in FARGATE tasks; sensors
  # = task count (aws-v2:919-968)
  local task_arns fargate_containers=0 fargate_tasks=0 tc tk
  json=$(aws_json ecs list-clusters --region "$region") || true
  while IFS= read -r cluster; do
    [[ -n "$cluster" ]] || continue
    task_arns=$(aws_json ecs list-tasks --cluster "$cluster" --launch-type FARGATE --region "$region" \
      | jq -r '.taskArns[]?')
    [[ -n "$task_arns" ]] || continue
    # describe-tasks accepts up to 100 task ARNs per call
    local batch=()
    while IFS= read -r arn; do
      [[ -n "$arn" ]] || continue
      batch+=("$arn")
      if (( ${#batch[@]} == 100 )); then
        read -r tc tk < <(aws_json ecs describe-tasks --cluster "$cluster" --tasks "${batch[@]}" --region "$region" \
          | jq -r '[ ([ .tasks[]? | (.containers | length) ] | add // 0), (.tasks | length) ] | @tsv' | tr '\t' ' ')
        fargate_containers=$(( fargate_containers + ${tc:-0} ))
        fargate_tasks=$(( fargate_tasks + ${tk:-0} ))
        batch=()
      fi
    done <<<"$task_arns"
    if (( ${#batch[@]} > 0 )); then
      read -r tc tk < <(aws_json ecs describe-tasks --cluster "$cluster" --tasks "${batch[@]}" --region "$region" \
        | jq -r '[ ([ .tasks[]? | (.containers | length) ] | add // 0), (.tasks | length) ] | @tsv' | tr '\t' ' ')
      fargate_containers=$(( fargate_containers + ${tc:-0} ))
      fargate_tasks=$(( fargate_tasks + ${tk:-0} ))
    fi
  done < <(jq -r '.clusterArns[]?' <<<"$json")
  emit_count 'Serverless Containers' "$fargate_containers" "$counts"
  emit_count 'Serverless Container Sensors' "$fargate_tasks" "$counts"
  progress_count "$fargate_containers" 'Serverless Containers [ECS Fargate]' "$name" "$region" "$logf"

  # Serverless Containers [SageMaker] — domains + endpoints (aws-v2:974-1024)
  n=$(aws_json sagemaker list-domains --region "$region" | jq '.Domains | length') || n=0
  emit_count 'Serverless Containers' "$n" "$counts"
  progress_count "$n" 'Serverless Containers [SageMaker Domains]' "$name" "$region" "$logf"
  n=$(aws_json sagemaker list-endpoints --region "$region" | jq '.Endpoints | length') || n=0
  emit_count 'Serverless Containers' "$n" "$counts"
  progress_count "$n" 'Serverless Containers [SageMaker Endpoints]' "$name" "$region" "$logf"

  if (( DATA )); then
    # PaaS Databases — DocumentDB, RDS Aurora, RDS, Redshift (aws-v2:1107-1219)
    ensure_creds_fresh "$acct"
    n=$(aws_json docdb describe-db-clusters --region "$region" | jq '.DBClusters | length') || n=0
    emit_count 'PaaS Databases' "$n" "$counts"
    progress_count "$n" 'PaaS Databases [DocumentDB]' "$name" "$region" "$logf"

    n=$(aws_json rds describe-db-clusters --region "$region" \
          --filters 'Name=engine,Values=aurora-mysql,aurora-postgresql' \
        | jq '.DBClusters | length') || n=0
    emit_count 'PaaS Databases' "$n" "$counts"
    progress_count "$n" 'PaaS Databases [RDS Aurora]' "$name" "$region" "$logf"

    n=$(aws_json rds describe-db-instances --region "$region" \
          --filters 'Name=engine,Values=mariadb,mysql,oracle-ee,oracle-ee-cdb,oracle-se2,oracle-se2-cdb,postgres,sqlserver-ee,sqlserver-ex,sqlserver-se,sqlserver-web' \
        | jq '.DBInstances | length') || n=0
    emit_count 'PaaS Databases' "$n" "$counts"
    progress_count "$n" 'PaaS Databases [RDS]' "$name" "$region" "$logf"

    n=$(aws_json redshift describe-clusters --region "$region" | jq '.Clusters | length') || n=0
    emit_count 'PaaS Databases' "$n" "$counts"
    progress_count "$n" 'PaaS Databases [RedShift]' "$name" "$region" "$logf"

    # Data Warehouses — DynamoDB tables, cap 10000 (aws-v2:1227-1249)
    n=$(aws_json dynamodb list-tables --region "$region" | jq '.TableNames | length') || n=0
    (( n > 10000 )) && n=10000
    emit_count 'Data Warehouses' "$n" "$counts"
    progress_count "$n" 'Data Warehouses [DynamoDB]' "$name" "$region" "$logf"
  fi

  if (( IMAGES )); then
    # Registry Container Images [ECR] — min(MAX_IMAGE_TAGS, images)/repo
    # (aws-v2:1033-1071)
    ensure_creds_fresh "$acct"
    local repo img_count=0
    json=$(aws_json ecr describe-repositories --region "$region") || true
    while IFS= read -r repo; do
      [[ -n "$repo" ]] || continue
      c=$(aws_json ecr list-images --repository-name "$repo" --region "$region" \
        | jq '.imageIds | length') || c=0
      (( c > MAX_IMAGE_TAGS )) && c=$MAX_IMAGE_TAGS
      img_count=$(( img_count + c ))
    done < <(jq -r '.repositories[]?.repositoryName' <<<"$json")
    emit_count 'Registry Container Images' "$img_count" "$counts"
    progress_count "$img_count" 'Registry Container Images [ECR]' "$name" "$region" "$logf"
  fi

  ERR_SINK=''
}

scan_account_s3() { # $1 acct id, $2 acct name, $3 tmp prefix — global control plane (aws-v2:1079-1101)
  local acct="$1" name="$2" prefix="$3"
  local counts="$prefix.counts" logf="$prefix.log"
  ERR_SINK="$prefix.errors"
  : > "$counts"; : > "$logf"
  apply_creds "$acct" || { ERR_SINK=''; return 0; }
  local n
  n=$(aws_json s3api list-buckets | jq '.Buckets | length') || n=0
  (( n > 10000 )) && n=10000
  emit_count 'Data Buckets' "$n" "$counts"
  progress_count "$n" 'Data Buckets [S3]' "$name" 'us-east-1' "$logf"
  ERR_SINK=''
}

####
# Cloud counting — fast (Resource Explorer where indexed; D6)
####

re_count() { # $1 query-string, $2 region → count, or '' when the index is unusable
  local out
  if ! out=$(aws resource-explorer-2 search --query-string "$1" --max-results 1 \
      --region "$2" --output json 2>/dev/null); then
    printf ''
    return 1
  fi
  jq -r '.Count.TotalResources // 0' <<<"$out"
}

scan_account_fast() { # $1 acct id, $2 acct name, $3 home region, $4 tmp prefix
  local acct="$1" name="$2" region="$3" prefix="$4"
  local counts="$prefix.counts" logf="$prefix.log"
  ERR_SINK="$prefix.errors"
  : > "$counts"; : > "$logf"
  apply_creds "$acct" || { ERR_SINK=''; return 0; }

  local n ok=1
  n=$(re_count 'resourcetype:ec2:instance' "$region") || ok=0
  if (( ok )); then
    emit_count 'Virtual Machines' "${n:-0}" "$counts"
    progress_count "${n:-0}" 'Virtual Machines [EC2]' "$name" 'all-regions' "$logf" '(Resource Explorer, D6)'
    n=$(re_count 'resourcetype:lambda:function' "$region") || n=0
    emit_count 'Serverless Functions' "${n:-0}" "$counts"
    progress_count "${n:-0}" 'Serverless Functions [Lambda]' "$name" 'all-regions' "$logf" '(no versions, D6)'
    if (( DATA )); then
      n=$(re_count 'resourcetype:s3:bucket' "$region") || n=0
      (( n > 10000 )) && n=10000
      emit_count 'Data Buckets' "${n:-0}" "$counts"
      progress_count "${n:-0}" 'Data Buckets [S3]' "$name" 'all-regions' "$logf"
      local db cl
      db=$(re_count 'resourcetype:rds:db' "$region") || db=0
      cl=$(re_count 'resourcetype:rds:cluster' "$region") || cl=0
      n=$(( ${db:-0} + ${cl:-0} ))
      emit_count 'PaaS Databases' "$n" "$counts"
      progress_count "$n" 'PaaS Databases [RDS + clusters]' "$name" 'all-regions' "$logf" '(index types, D6)'
      n=$(re_count 'resourcetype:dynamodb:table' "$region") || n=0
      (( n > 10000 )) && n=10000
      emit_count 'Data Warehouses' "${n:-0}" "$counts"
      progress_count "${n:-0}" 'Data Warehouses [DynamoDB]' "$name" 'all-regions' "$logf"
    fi
    (( IMAGES )) && status "- Registry Container Images pending in $name: not countable from the index; rerun without --fast"
  else
    status "- Resource Explorer index not available in $name — falling back to the accurate path (§7)"
  fi
  ERR_SINK=''
  # Container hosts + serverless containers are never index-visible as node/
  # container counts — the caller runs the accurate path for those (and for
  # everything else when ok=0).
  printf '%s' "$ok"
}

####
# Defend — auto-discovery + CloudWatch basic estimation (+ detailed sampling)
####

DEFEND_ROWS=''     # results file: rows "source|category|metric|details|gb"
DEFEND_ERRORS_F=''

bucket_region() { # $1 bucket → region name
  local loc
  loc=$(aws s3api get-bucket-location --bucket "$1" --output json 2>/dev/null \
    | jq -r '.LocationConstraint // "us-east-1"')
  [[ -z "$loc" || "$loc" == null ]] && loc='us-east-1'
  printf '%s' "$loc"
}

cw_incoming_bytes() { # $1 bucket, $2 region → bytes ('' if no datapoints)
  local start end out
  end=$(utc_now_iso)
  start=$(utc_days_ago_iso 30)
  out=$(aws cloudwatch get-metric-statistics --namespace AWS/S3 --metric-name IncomingBytes \
    --dimensions "Name=BucketName,Value=$1" 'Name=FilterId,Value=EntireBucket' \
    --start-time "$start" --end-time "$end" --period 2592000 \
    --statistics Sum --unit Bytes --region "$2" --output json 2>/dev/null) || { printf ''; return 1; }
  jq -r '[ .Datapoints[]? | select(.Sum != null) ] | if length > 0 then .[0].Sum else empty end' <<<"$out"
}

cw_bucket_size_growth() { # $1 bucket, $2 region → bytes ('' if none)
  local now_iso start30 out latest hist h_start h_end
  now_iso=$(utc_now_iso)
  start30=$(utc_days_ago_iso 30)
  out=$(aws cloudwatch get-metric-statistics --namespace AWS/S3 --metric-name BucketSizeBytes \
    --dimensions "Name=BucketName,Value=$1" 'Name=StorageType,Value=StandardStorage' \
    --start-time "$start30" --end-time "$now_iso" --period 86400 \
    --statistics Average --unit Bytes --region "$2" --output json 2>/dev/null) || { printf ''; return 1; }
  latest=$(jq -r '[ .Datapoints[]? | select(.Average != null) ] | sort_by(.Timestamp) | if length > 0 then (last.Average) else empty end' <<<"$out")
  [[ -n "$latest" ]] || { printf ''; return 0; }
  h_start=$(utc_days_ago_iso 31)
  h_end=$(utc_days_ago_iso 29)
  hist=$(aws cloudwatch get-metric-statistics --namespace AWS/S3 --metric-name BucketSizeBytes \
    --dimensions "Name=BucketName,Value=$1" 'Name=StorageType,Value=StandardStorage' \
    --start-time "$h_start" --end-time "$h_end" --period 86400 \
    --statistics Average --unit Bytes --region "$2" --output json 2>/dev/null \
    | jq -r '[ .Datapoints[]? | select(.Average != null) ] | sort_by(.Timestamp) | if length > 0 then (first.Average) else empty end')
  if [[ -n "$hist" ]]; then
    awk -v a="$latest" -v b="$hist" 'BEGIN { printf "%s", a - b }'
  else
    printf '%s' "$latest"
  fi
}

defend_basic() { # $1 source key (ct|vpc|r53), $2 bucket, $3 prefix detail, $4 compression
  local key="$1" bucket="$2" detail="$3" factor="$4"
  ERR_SINK="$DEFEND_ERRORS_F"
  status "Defend: basic estimation for s3://$bucket (CloudWatch metrics)"
  local region bytes gb
  region=$(bucket_region "$bucket")
  bytes=$(cw_incoming_bytes "$bucket" "$region")
  if [[ -z "$bytes" ]]; then
    bytes=$(cw_bucket_size_growth "$bucket" "$region")
  fi
  [[ -n "$bytes" ]] || { bytes=0; err "Defend: no CloudWatch S3 metrics for $bucket (permissions or metrics not enabled)"; }
  gb=$(awk -v b="$bytes" -v f="$factor" 'BEGIN { printf "%.2f", b * f / (1024*1024*1024) }')
  case "$key" in
    ct)  printf 'AWS CloudTrail|Management Logs Ingestion GB|Basic Estimation (Total)|%s|%s\n' "$detail" "$gb" >> "$DEFEND_ROWS" ;;
    vpc) printf 'AWS VPC Flow Logs|AWS VPC Flow Logs Ingestion GB|Basic Estimation|%s|%s\n' "$detail" "$gb" >> "$DEFEND_ROWS" ;;
    r53) printf 'AWS Route 53 Resolver Query Logs|Network Logs Ingestion GB|Basic Estimation|%s|%s\n' "$detail" "$gb" >> "$DEFEND_ROWS" ;;
  esac
  ERR_SINK=''
}

# Detailed CloudTrail: discover base paths, list the last N daily prefixes, sum
# compressed sizes, sample objects, categorize events (defend-aws:513-571).
defend_detailed_cloudtrail() { # $1 bucket, $2 prefix
  local bucket="$1" prefix="${2%/}/"
  ERR_SINK="$DEFEND_ERRORS_F"
  status "Defend: detailed CloudTrail sampling in s3://$bucket/$prefix"

  list_common_prefixes() { # $1 prefix → subprefixes, digest paths dropped
    aws s3api list-objects-v2 --bucket "$bucket" --prefix "$1" --delimiter / --output json 2>/dev/null \
      | jq -r '.CommonPrefixes[]?.Prefix // empty' \
      | grep -viE 'cloudtrail-digest|cloudtraildigest' || true
  }

  # Base-path discovery (defend-aws:574-654): account/org level, then the
  # cloudtrail service dir, then regions.
  local base_paths=() l1 l2 l3 seg
  local level1
  level1=$(list_common_prefixes "$prefix")
  if [[ -z "$level1" ]]; then
    base_paths+=("$prefix")
  else
    while IFS= read -r l1; do
      [[ -n "$l1" ]] || continue
      seg=$(basename "$l1")
      if [[ "$seg" == o-* ]]; then
        while IFS= read -r l2; do
          [[ -n "$l2" ]] || continue
          while IFS= read -r l3; do
            [[ -n "$l3" ]] || continue
            if [[ "${l3,,}" == *cloudtrail* ]]; then
              local regions_found
              regions_found=$(list_common_prefixes "$l3")
              if [[ -z "$regions_found" ]]; then base_paths+=("$l3")
              else while IFS= read -r r; do [[ -n "$r" ]] && base_paths+=("$r"); done <<<"$regions_found"; fi
            fi
          done < <(list_common_prefixes "$l2")
        done < <(list_common_prefixes "$l1")
      else
        while IFS= read -r l2; do
          [[ -n "$l2" ]] || continue
          if [[ "${l2,,}" == *cloudtrail* ]]; then
            local regions_found
            regions_found=$(list_common_prefixes "$l2")
            if [[ -z "$regions_found" ]]; then base_paths+=("$l2")
            else while IFS= read -r r; do [[ -n "$r" ]] && base_paths+=("$r"); done <<<"$regions_found"; fi
          fi
        done < <(list_common_prefixes "$l1")
      fi
    done <<<"$level1"
    (( ${#base_paths[@]} == 0 )) && base_paths+=("$prefix")
  fi

  # Collect objects for the last N days (key<TAB>size), sum compressed size
  local objects_file="$TMP_DIR/defend.ct.objects" bp d day_prefix
  : > "$objects_file"
  for bp in "${base_paths[@]}"; do
    for (( d = 0; d < DEFEND_DAYS; d++ )); do
      day_prefix="${bp%/}/$(date_ymd_days_ago "$d")/"
      aws s3api list-objects-v2 --bucket "$bucket" --prefix "$day_prefix" --output json 2>/dev/null \
        | jq -r '.Contents[]? | select(.Key | test("digest"; "i") | not) | [ .Key, (.Size | tostring) ] | @tsv' \
        >> "$objects_file" || true
    done
  done

  local total_objects total_compressed
  total_objects=$(grep -c . "$objects_file" || true)
  total_compressed=$(awk -F'\t' '{ s += $2 } END { printf "%d", s }' "$objects_file")
  status "Defend: $total_objects CloudTrail objects in the last $DEFEND_DAYS days ($total_compressed compressed bytes)"

  local detail="$bucket/$prefix"
  if (( total_objects == 0 )); then
    printf 'AWS CloudTrail|Detailed Categories|No data processed or available|%s|\n' "$detail" >> "$DEFEND_ROWS"
    ERR_SINK=''
    return 0
  fi

  # Sample objects (random when shuf exists, else evenly spaced)
  local sample_file="$TMP_DIR/defend.ct.sample"
  if command -v shuf >/dev/null 2>&1; then
    shuf -n "$DEFEND_SAMPLE_SIZE" "$objects_file" > "$sample_file" 2>/dev/null || head -n "$DEFEND_SAMPLE_SIZE" "$objects_file" > "$sample_file"
  else
    awk -F'\t' -v n="$DEFEND_SAMPLE_SIZE" -v t="$total_objects" \
      'BEGIN { step = (t > n) ? int(t / n) : 1 } NR % step == 0 { print; c++ } c >= n { exit }' \
      "$objects_file" > "$sample_file"
  fi

  # Analyze the sample: per-event category sizes via jq
  local key size obj="$TMP_DIR/defend.ct.obj.gz" stats="$TMP_DIR/defend.ct.stats"
  : > "$stats"   # lines: compressed<TAB>uncompressed<TAB>write<TAB>readonly<TAB>data<TAB>other
  local sampled=0
  while IFS=$'\t' read -r key size; do
    [[ -n "$key" ]] || continue
    if ! aws s3api get-object --bucket "$bucket" --key "$key" "$obj" --output json >/dev/null 2>&1; then
      err "Defend: cannot read s3://$bucket/$key"
      continue
    fi
    gunzip -c "$obj" 2>/dev/null | jq -r --arg comp "$size" '
      . as $doc | ($doc | tojson | utf8bytelength) as $uncomp
      | [ ($doc.Records // [])[]
          | { size: (tojson | utf8bytelength),
              cat: (if .eventCategory == "Management" then
                      (if .readOnly == false then "write"
                       elif .readOnly == true then "readonly"
                       else "other" end)
                    elif .eventCategory == "Data" then "data"
                    else "other" end) } ] as $evs
      | [ $comp, ($uncomp | tostring),
          ([ $evs[] | select(.cat == "write")    | .size ] | add // 0 | tostring),
          ([ $evs[] | select(.cat == "readonly") | .size ] | add // 0 | tostring),
          ([ $evs[] | select(.cat == "data")     | .size ] | add // 0 | tostring),
          ([ $evs[] | select(.cat == "other")    | .size ] | add // 0 | tostring)
        ] | @tsv' >> "$stats" 2>/dev/null || err "Defend: cannot parse s3://$bucket/$key"
    sampled=$(( sampled + 1 ))
  done < "$sample_file"
  rm -f "$obj"
  status "Defend: analyzed $sampled sampled objects"

  # Extrapolate (defend-aws:536-551): avg compression ratio from the sample,
  # per-category proportion of event bytes, normalized to 30 days.
  # The official maps the S3 Data category to the Storage row via a name that
  # never matches ('CloudTrail - Storage (S3)' vs 'CloudTrail - Data (S3)'),
  # silently dropping those bytes; we keep the row populated instead (sizing
  # bias: rather over than under).
  awk -F'\t' -v total_comp="$total_compressed" -v days="$DEFEND_DAYS" -v detail="$detail" '
    { sc += $1; su += $2; w += $3; r += $4; d += $5; o += $6 }
    END {
      ev = w + r + d + o
      if (ev <= 0 || sc <= 0) {
        printf "AWS CloudTrail|Detailed Categories|No data processed or available|%s|\n", detail
        exit
      }
      ratio = su / sc
      est = total_comp * ratio
      gb = 1024 * 1024 * 1024
      norm = (days > 0) ? 30.0 / days : 1.0
      printf "AWS CloudTrail|Management Logs Ingestion GB|Write Events|%s|%.2f\n",   detail, est * (w / ev) * norm / gb
      printf "AWS CloudTrail|Management Logs Ingestion GB|ReadOnly Events|%s|%.2f\n", detail, est * (r / ev) * norm / gb
      printf "AWS CloudTrail|Storage Logs Ingestion GB|S3 Data Events|%s|%.2f\n",     detail, est * (d / ev) * norm / gb
      printf "AWS CloudTrail|N/A (Other)|Other Operations|%s|%.2f\n",                 detail, est * (o / ev) * norm / gb
    }' "$stats" >> "$DEFEND_ROWS"
  ERR_SINK=''
}

discover_defend_sources() { # $@ = regions; appends "type<TAB>bucket<TAB>prefix" lines to stdout
  local region json
  # CloudTrail — trails carry their S3 destination (R2: derive, don't ask)
  json=$(aws_json cloudtrail describe-trails) || true
  jq -r '.trailList[]? | select(.S3BucketName != null)
    | [ "ct", .S3BucketName, (.S3KeyPrefix // "") ] | @tsv' <<<"$json"
  for region in "$@"; do
    aws_json ec2 describe-flow-logs --region "$region" \
        --filter 'Name=log-destination-type,Values=s3' \
      | jq -r '.FlowLogs[]? | select(.LogDestination != null)
          | (.LogDestination | sub("^arn:aws:s3:::"; "")) as $dest
          | [ "vpc", ($dest | split("/")[0]), "" ] | @tsv'
    aws_json route53resolver list-resolver-query-log-configs --region "$region" \
      | jq -r '.ResolverQueryLogConfigs[]? | select(.DestinationArn | startswith("arn:aws:s3"))
          | (.DestinationArn | sub("^arn:aws:s3:::"; "")) as $dest
          | [ "r53", ($dest | split("/")[0]), "" ] | @tsv'
  done
}

run_defend() { # $@ = regions (for discovery)
  DEFEND_ROWS="$TMP_DIR/defend.rows"
  DEFEND_ERRORS_F="$TMP_DIR/defend.errors"
  touch "$DEFEND_ROWS" "$DEFEND_ERRORS_F"

  local -A ct_buckets=() vpc_buckets=() r53_buckets=()
  local kind bucket pfx

  if (( ! DEFEND_NO_DISCOVER )); then
    status 'Defend: auto-discovering log sources (trails, flow logs, resolver query logs)'
    while IFS=$'\t' read -r kind bucket pfx; do
      [[ -n "$bucket" ]] || continue
      case "$kind" in
        ct)  ct_buckets[$bucket]="${pfx:+${pfx%/}/}AWSLogs/" ;;
        vpc) vpc_buckets[$bucket]=1 ;;
        r53) r53_buckets[$bucket]=1 ;;
      esac
    done < <(discover_defend_sources "$@" | sort -u)
  fi
  # Explicit flags override/supplement discovery (R2)
  [[ -n "$DEFEND_CT_BUCKET" ]] && ct_buckets[$DEFEND_CT_BUCKET]="$DEFEND_CT_PREFIX"
  [[ -n "$DEFEND_VPC_BUCKET" ]] && vpc_buckets[$DEFEND_VPC_BUCKET]=1
  [[ -n "$DEFEND_R53_BUCKET" ]] && r53_buckets[$DEFEND_R53_BUCKET]=1

  if (( ${#ct_buckets[@]} == 0 && ${#vpc_buckets[@]} == 0 && ${#r53_buckets[@]} == 0 )); then
    status 'Defend: no log sources found — pass --defend-cloudtrail-bucket / --defend-vpc-flow-bucket / --defend-r53-bucket. Continuing.'
    return 0
  fi

  for bucket in "${!ct_buckets[@]}"; do
    if (( DEFEND_DETAILED )); then
      defend_detailed_cloudtrail "$bucket" "${ct_buckets[$bucket]}"
    else
      defend_basic ct "$bucket" "$bucket/${ct_buckets[$bucket]}" "$DEFEND_CT_COMPRESSION"
    fi
  done
  for bucket in "${!vpc_buckets[@]}"; do
    defend_basic vpc "$bucket" "$bucket" "$DEFEND_VPC_COMPRESSION"
  done
  for bucket in "${!r53_buckets[@]}"; do
    defend_basic r53 "$bucket" "$bucket" "$DEFEND_R53_COMPRESSION"
  done
}

write_defend_output() {
  [[ -n "${DEFEND_ROWS:-}" && -f "$DEFEND_ROWS" ]] || return 0
  local csv_file="$OUTPUT_DIR/$DEFEND_OUTPUT_FILE"
  {
    csv_row 'Log Source Type' 'Billable Category' 'Specific Metric' 'Bucket/Prefix Details' 'Estimated 30-Day Uncompressed Volume (GB)'
    local src cat metric details gb
    while IFS='|' read -r src cat metric details gb; do
      [[ -n "$src" ]] || continue
      csv_row "$src" "$cat" "$metric" "$details" "$gb"
    done < "$DEFEND_ROWS"
  } > "$csv_file"

  if [[ -s "$DEFEND_ROWS" ]]; then
    echo
    echo 'Wiz Defend Ingestion: AWS Log Volume Estimation (Uncompressed, Normalized to 30 days)'
    echo
    awk -F'|' '{ printf "  %-32s %-28s %-24s : %s GB\n", $1, $3, $4, ($5 == "" ? "n/a" : $5) }' "$DEFEND_ROWS"
    local total
    total=$(awk -F'|' '$5 != "" { s += $5 } END { printf "%.2f", s }' "$DEFEND_ROWS")
    echo
    echo "  Total Estimated 30-Day Volume: $total GB"
    if (( ! DEFEND_DETAILED )); then
      echo '  (Basic mode: S3 CloudWatch metrics × assumed compression factor. For a'
      echo '   per-category CloudTrail breakdown, rerun with --defend-detailed.)'
    fi
  fi
  echo
  echo "Defend details written to $DEFEND_OUTPUT_FILE"
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

  for f in "$TMP_DIR"/cloud.*.counts; do
    [[ -f "$f" ]] || continue
    while IFS='=' read -r key v; do
      [[ -n "$key" && -n "${totals[$key]+x}" ]] || continue
      totals[$key]=$(( totals[$key] + v ))
    done < "$f"
  done

  local accounts_seen
  accounts_seen=$(grep -h '^cloud ' "$STATE_FILE" 2>/dev/null | awk '{print $2}' | sort -u | grep -c . || true)

  mkdir -p "$OUTPUT_DIR"
  {
    csv_row 'Resource Type' 'Resource Count'
    for key in "${TOTAL_KEYS[@]}"; do
      csv_row "$key" "${totals[$key]}"
    done
  } > "$OUTPUT_DIR/$OUTPUT_FILE"

  {
    csv_row 'Resource Type' 'Resource Count' 'Account' 'Region'
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

  # Summary block — mirrors the official (aws-v2:1373-1425) so the numbers map
  # 1:1 onto the billable-units calculator
  local label='Results'
  [[ -n "$partial" ]] && label='Partial results'
  echo
  echo "$label across $accounts_seen AWS Accounts (wiz-aws.sh version: $VERSION)"
  echo
  printf "%${PADDING}s Virtual Machines [EC2, LightSail]\n" "${totals['Virtual Machines']}"
  printf "%${PADDING}s Container Hosts [ECS, EKS]\n" "${totals['Container Hosts']}"
  printf "%${PADDING}s Serverless Functions [Lambda]\n" "${totals['Serverless Functions']}"
  printf "%${PADDING}s Serverless Containers [ECS and EKS Fargate, SageMaker Domains, SageMaker Endpoints]\n" "${totals['Serverless Containers']}"
  if (( DATA )); then
    echo
    printf "%${PADDING}s Data Buckets (Public and Private) [S3]\n" "${totals['Data Buckets']}"
    printf "%${PADDING}s PaaS Databases [DocumentDB, RDS, RedShift]\n" "${totals['PaaS Databases']}"
    printf "%${PADDING}s Data Warehouses [DynamoDB]\n" "${totals['Data Warehouses']}"
  fi
  echo
  printf "%${PADDING}s Non-OS Disks [EC2, LightSail]\n" "${totals['Non-OS Disks']}"
  if (( IMAGES )); then
    if (( FAST )); then
      printf "%${PADDING}s Registry Container Images [ECR] (pending: rerun without --fast)\n" 'n/a'
    else
      printf "%${PADDING}s Registry Container Images [ECR]\n" "${totals['Registry Container Images']}"
    fi
  fi
  echo
  printf "%${PADDING}s (Potential) Kubernetes Sensors [Estimated from Platform]\n" "${totals['Kubernetes Sensors']}"
  printf "%${PADDING}s (Potential) Virtual Machine Sensors [Estimated from VM Platform *]\n" "${totals['Virtual Machine Sensors']}"
  printf "%${PADDING}s (Potential) Serverless Container Sensors [ECS Fargate Tasks]\n" "${totals['Serverless Container Sensors']}"
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
  [[ -n "$partial" ]] && echo 'Scan interrupted; results above cover completed account/region scopes only.'
  return 0
}

####
# Scan orchestration — accounts × regions, bounded parallelism, resume (§11)
####

enumerate_accounts() { # → "id<TAB>name" lines
  if (( ORG )); then
    local json
    json=$(aws_json organizations list-accounts) || return 1
    jq -r '.Accounts[]? | select(.Status == "ACTIVE") | [ .Id, .Name ] | @tsv' <<<"$json"
    return 0
  fi
  if [[ -n "$ACCOUNTS_FILE" ]]; then
    local id
    while IFS= read -r id; do
      id=$(tr -d '[:space:]' <<<"$id")
      [[ "$id" =~ ^[0-9]{12}$ ]] || { [[ -n "$id" ]] && err "skipping invalid account ID: $id"; continue; }
      printf '%s\t%s\n' "$id" "$id"
    done < "$ACCOUNTS_FILE"
    return 0
  fi
  local me
  me=$(aws_json sts get-caller-identity | jq -r '.Account // empty')
  [[ -n "$me" ]] || return 1
  printf '%s\t%s\n' "$me" "$me"
}

enumerate_regions() { # uses current creds in scope → region names
  if [[ -n "$REGIONS" ]]; then
    tr ',' '\n' <<<"$REGIONS" | grep -v '^$'
    return 0
  fi
  aws_json ec2 describe-regions --no-all-regions \
    | jq -r '.Regions[]?.RegionName' | sort
}

wait_for_slot() {
  while (( $(jobs -rp | wc -l) >= MAX_PARALLEL )); do sleep 0.2; done
}

run_cloud() { # $@ = "id<TAB>name" account lines
  local accounts=("$@") line acct name current_account
  current_account=$(aws_json sts get-caller-identity | jq -r '.Account // empty')

  for line in "${accounts[@]}"; do
    acct=${line%%$'\t'*}; name=${line#*$'\t'}
    status "[SCAN] Account: $acct ($name)"
    write_creds_file "$acct" "$current_account" || continue

    # Region + Lightsail-region enumeration under this account's creds
    local regions=() ls_regions=''
    while IFS= read -r r; do [[ -n "$r" ]] && regions+=("$r"); done < <(
      ( apply_creds "$acct"; enumerate_regions )
    )
    (( ${#regions[@]} == 0 )) && { err "Account: $acct no regions enumerable"; continue; }
    ls_regions=$( ( apply_creds "$acct"; aws_json lightsail get-regions --region us-east-1 \
      | jq -r '.regions[]?.name' ) | tr '\n' ' ' )

    if (( FAST )); then
      if (( RESUME )) && grep -q "^cloud $acct fast done\$" "$STATE_FILE" 2>/dev/null; then
        status "[SKIP] Account $acct fast scan (resumed)"
      else
        local re_ok
        re_ok=$( ( scan_account_fast "$acct" "$name" "${regions[0]}" "$TMP_DIR/cloud.$acct.fast" ) )
        if [[ "$re_ok" == 1 ]]; then
          # Index served VMs/functions/data; hosts + serverless containers
          # still need the accurate per-region pass (never index-visible).
          local region
          for region in "${regions[@]}"; do
            wait_for_slot
            ( scan_account_region_hosts_only "$acct" "$name" "$region" "$TMP_DIR/cloud.$acct.$region"
              echo "cloud $acct $region done" >> "$STATE_FILE" ) &
          done
          wait
          echo "cloud $acct fast done" >> "$STATE_FILE"
          continue
        fi
        status "[FALLBACK] Account $acct: accurate path for all dimensions"
      fi
    fi

    local region is_ls
    for region in "${regions[@]}"; do
      if (( RESUME )) && grep -q "^cloud $acct $region done\$" "$STATE_FILE" 2>/dev/null; then
        status "[SKIP] $acct/$region (resumed)"
        continue
      fi
      is_ls=0
      [[ " $ls_regions " == *" $region "* ]] && is_ls=1
      wait_for_slot
      ( scan_account_region "$acct" "$name" "$region" "$is_ls" "$TMP_DIR/cloud.$acct.$region"
        echo "cloud $acct $region done" >> "$STATE_FILE" ) &
    done
    if (( DATA && ! FAST )); then
      if ! { (( RESUME )) && grep -q "^cloud $acct s3 done\$" "$STATE_FILE" 2>/dev/null; }; then
        wait_for_slot
        ( scan_account_s3 "$acct" "$name" "$TMP_DIR/cloud.$acct.s3"
          echo "cloud $acct s3 done" >> "$STATE_FILE" ) &
      fi
    fi
    wait
    status "[DONE] Account: $acct ($name)"
  done
}

scan_account_region_hosts_only() { # fast mode's accurate remainder
  local acct="$1" name="$2" region="$3" prefix="$4"
  local counts="$prefix.counts" logf="$prefix.log"
  ERR_SINK="$prefix.errors"
  : > "$counts"; : > "$logf"
  apply_creds "$acct" || { ERR_SINK=''; return 0; }

  local json cluster c ecs_hosts=0 eks_nodes=0 eks_fargate=0 profiles
  json=$(aws_json ecs list-clusters --region "$region") || true
  while IFS= read -r cluster; do
    [[ -n "$cluster" ]] || continue
    c=$(aws_json ecs list-container-instances --cluster "$cluster" --region "$region" | jq '.containerInstanceArns | length') || c=0
    ecs_hosts=$(( ecs_hosts + c ))
  done < <(jq -r '.clusterArns[]?' <<<"$json")
  emit_count 'Container Hosts' "$ecs_hosts" "$counts"
  emit_count 'Kubernetes Sensors' "$ecs_hosts" "$counts"
  progress_count "$ecs_hosts" 'Container Hosts [ECS]' "$name" "$region" "$logf"

  json=$(aws_json eks list-clusters --region "$region") || true
  while IFS= read -r cluster; do
    [[ -n "$cluster" ]] || continue
    c=$(aws_json ec2 describe-instances --region "$region" \
          --filters "Name=tag-key,Values=kubernetes.io/cluster/$cluster" \
        | jq '[ .Reservations[]?.Instances[]? | select(.State.Name != "terminated") ] | length') || c=0
    eks_nodes=$(( eks_nodes + c ))
    profiles=$(aws_json eks list-fargate-profiles --cluster-name "$cluster" --region "$region" \
        | jq '.fargateProfileNames | length') || profiles=0
    (( profiles > 0 )) && eks_fargate=$(( eks_fargate + 1 ))
  done < <(jq -r '.clusters[]?' <<<"$json")
  emit_count 'Container Hosts' "$eks_nodes" "$counts"
  emit_count 'Kubernetes Sensors' "$eks_nodes" "$counts"
  progress_count "$eks_nodes" 'Container Hosts [EKS]' "$name" "$region" "$logf"
  emit_count 'Serverless Containers' "$eks_fargate" "$counts"
  progress_count "$eks_fargate" 'Serverless Containers [EKS Fargate]' "$name" "$region" "$logf" '(1 per Fargate cluster, D1)'
  ERR_SINK=''
}

on_interrupt() {
  trap - INT TERM
  status '[INTERRUPTED] Writing partial results before exiting.'
  if [[ "$MODE" != defend ]]; then write_cloud_output partial; fi
  if [[ "$MODE" != cloud ]]; then write_defend_output; fi
  echo "Resume with: wiz-aws.sh $MODE --resume --output-dir $OUTPUT_DIR"
  exit 130
}

####
# Interactive menu (§4)
####

menu() {
  cat <<EOF

wiz-aws.sh v$VERSION — Wiz sizing for AWS

  1) Full sizing        cloud resources + Defend ingest (recommended)
  2) Full + data/images adds S3, PaaS DBs, DynamoDB, ECR images (longer scan)
  3) Fast estimate      Resource Explorer where indexed (D6 applies)
  4) Cloud resources only
  5) Defend ingest only
  6) Organization-wide  full sizing across all ACTIVE org accounts
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
    6) MODE=all; ORG=1 ;;
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
      --org) ORG=1; shift ;;
      --role-name) ROLE_NAME="${2:?--role-name needs a value}"; shift 2 ;;
      --accounts-file) ACCOUNTS_FILE="${2:?--accounts-file needs a value}"; shift 2 ;;
      --regions) REGIONS="${2:?--regions needs a value}"; shift 2 ;;
      --max-parallel) MAX_PARALLEL="${2:?--max-parallel needs a value}"; shift 2 ;;
      --max-image-tags) MAX_IMAGE_TAGS="${2:?--max-image-tags needs a value}"; shift 2 ;;
      --max-lambda-versions) MAX_LAMBDA_VERSIONS="${2:?--max-lambda-versions needs a value}"; shift 2 ;;
      --defend-detailed) DEFEND_DETAILED=1; shift ;;
      --defend-cloudtrail-bucket) DEFEND_CT_BUCKET="${2:?--defend-cloudtrail-bucket needs a value}"; shift 2 ;;
      --defend-cloudtrail-prefix) DEFEND_CT_PREFIX="${2:?--defend-cloudtrail-prefix needs a value}"; shift 2 ;;
      --defend-vpc-flow-bucket) DEFEND_VPC_BUCKET="${2:?--defend-vpc-flow-bucket needs a value}"; shift 2 ;;
      --defend-r53-bucket) DEFEND_R53_BUCKET="${2:?--defend-r53-bucket needs a value}"; shift 2 ;;
      --defend-no-discover) DEFEND_NO_DISCOVER=1; shift ;;
      --defend-days) DEFEND_DAYS="${2:?--defend-days needs a value}"; shift 2 ;;
      --defend-sample-size) DEFEND_SAMPLE_SIZE="${2:?--defend-sample-size needs a value}"; shift 2 ;;
      --defend-compression-factor)
        DEFEND_CT_COMPRESSION="${2:?--defend-compression-factor needs a value}"
        DEFEND_VPC_COMPRESSION="$DEFEND_CT_COMPRESSION"
        DEFEND_R53_COMPRESSION="$DEFEND_CT_COMPRESSION"
        shift 2 ;;
      --print-csv-contract) print_csv_contract; exit 0 ;;
      --list) list_modes; exit 0 ;;
      --version) echo "wiz-aws.sh $VERSION"; exit 0 ;;
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
  TMP_DIR="$OUTPUT_DIR/.wiz-aws-tmp"
  STATE_FILE="$OUTPUT_DIR/.wiz-aws-state"
  if (( ! RESUME )); then
    rm -rf "$TMP_DIR"
    rm -f "$STATE_FILE"
  fi
  mkdir -p "$TMP_DIR"
  touch "$STATE_FILE"
  GLOBAL_ERRORS="$TMP_DIR/global.errors"
  touch "$GLOBAL_ERRORS"

  trap on_interrupt INT TERM

  status "wiz-aws.sh v$VERSION — mode: $MODE$( ((FAST)) && printf ' (fast)' )$( ((ORG)) && printf ' (org)' )"
  local accounts=() line
  while IFS= read -r line; do
    [[ -n "$line" ]] && accounts+=("$line")
  done < <(enumerate_accounts)
  if (( ${#accounts[@]} == 0 )); then
    echo 'No AWS account resolvable. Configure credentials (aws sts get-caller-identity should work).' >&2
    exit 1
  fi
  status "Scanning ${#accounts[@]} account(s)"

  if [[ "$MODE" != defend ]]; then
    run_cloud "${accounts[@]}"
  fi
  if [[ "$MODE" != cloud ]]; then
    # Defend runs against the CURRENT account's log architecture (org trails
    # deliver to a central bucket that describe-trails reveals from here).
    local regions=()
    while IFS= read -r r; do [[ -n "$r" ]] && regions+=("$r"); done < <(enumerate_regions)
    run_defend "${regions[@]}"
  fi

  if [[ "$MODE" != defend ]]; then write_cloud_output; fi
  if [[ "$MODE" != cloud ]]; then write_defend_output; fi

  rm -rf "$TMP_DIR"
  rm -f "$STATE_FILE"
  status 'Scan complete.'
}

main "$@"
