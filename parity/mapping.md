# Parity map — official Python → wiz-*.sh

Structural parity layer (§8.1): for every count a `wiz-<csp>.sh` emits, this
file cites the official script's source (under `reference/`, the parity
oracle) and the exact bash query + `jq` reduction that reproduces it. A
reviewer can diff intent side-by-side with no credentials.

Conventions:

- **Official** cites `reference/<path>:<line>` at the point the count is
  produced (the API call or the accumulation into the CSV row).
- **Ours** names the `wiz-<csp>.sh` function and the REST/CLI call + `jq`
  reduction.
- **Deviation** links the ledger entry (PLAN.md §9, D1–D6) when the count is
  intentionally non-identical; `—` means the mapping is intended exact.
- Rows marked *pending* are filled in the phase that builds that script.
  A CSP's section being complete is part of that phase's Definition of Done.

## Azure — `wiz-azure.sh`

Oracle: `reference/cloud/azure/resource-count-azure-v2.py` (cloud, "azure-v2"),
`reference/defend/azure/log-volume-estimation-azure.py` ("defend-az"),
`reference/code/azure-devops/active-developer-count-ado.py` ("ado").

Scope note: the official cloud script prompts for one subscription by default
(`--all` for every subscription); `wiz-azure.sh` defaults to all accessible
enabled subscriptions (`--subscription ID` / `--subscriptions-file` to narrow),
because sizing runs almost always want the whole tenant. Subscription set is
filtered identically (state Enabled, drop "Access to Azure Active Directory",
azure-v2:1238).

### Cloud, accurate mode (default)

| Count (CSV row) | Official | Ours (`wiz-azure.sh` fn → call + jq) | Deviation |
|---|---|---|---|
| Virtual Machines [Compute] | azure-v2:536-591 — SDK `virtual_machines.list_all()`, skip scale-set members + `tags.Vendor==Databricks` | `scan_sub_cloud_accurate` — `GET .../Microsoft.Compute/virtualMachines`, `jq select(.properties.virtualMachineScaleSet == null) \| select(tags.Vendor != "Databricks") \| length` | — |
| Non-OS Disks (VMs) | azure-v2:583-585 — `len(storage_profile.data_disks)` | same call, `jq (.properties.storageProfile.dataDisks // []) \| length` summed | — |
| Virtual Machine Sensors | azure-v2:581-582 — VMs with `os_profile.linux_configuration` | same call, `jq select(.properties.osProfile.linuxConfiguration != null)` | — |
| Virtual Machines [Scale Sets] | azure-v2:597-655 — enumerate VMSS then live `virtual_machine_scale_set_vms.list()`, skip Databricks | `GET .../virtualMachineScaleSets` then `GET .../{name}/virtualMachines` per set | — |
| Non-OS Disks (VMSS) | azure-v2:614-648 — profile `dataDisks × instances`; per-VM detail when no profile | same rule; the no-profile fallback reads each instance's own `storageProfile.dataDisks` from the list response instead of a per-VM GET | — (same disks, one fewer call) |
| Container Hosts | azure-v2:661-696 — sum `agent_pool_profiles[].count` over managed clusters | `GET .../Microsoft.ContainerService/managedClusters`, `jq (.properties.agentPoolProfiles // [])[] \| .count` summed; also feeds Kubernetes Sensors like azure-v2:679,696 | — |
| Serverless Functions | azure-v2:749-794 — `web_apps.list()` count + child `list_functions()` for kind~functionapp | `GET .../Microsoft.Web/sites` + `GET .../sites/{name}/functions` for kind containing `functionapp` | — |
| Serverless Containers (ACI) | azure-v2:702-719 — `container_groups.list()` count | `GET .../Microsoft.ContainerInstance/containerGroups`, `jq length` | — |
| Serverless Containers (Container Apps) + Sensors | azure-v2:725-743 — `container_apps.list_by_subscription()` count | `GET .../Microsoft.App/containerApps`, `jq length` | — |
| Asset Metadata (Arc) | azure-v2:1015-1032 — `machines.list_by_subscription()` | `GET .../Microsoft.HybridCompute/machines`, `jq length` | — |
| Asset Metadata (Stack HCI) | azure-v2:1039-1056 — `clusters.list_by_subscription()` | `GET .../Microsoft.AzureStackHCI/clusters`, `jq length` | — |
| Data Buckets (`--data`) | azure-v2:919-961 — ARM control-plane `blob_containers.list()` (bypasses firewalls), skip Databricks-tagged accounts, 10000/account cap | `GET .../storageAccounts` + `GET .../blobServices/default/containers` per account, same skips + cap. Control plane, so no storage data-plane token is needed (same as the oracle) | — |
| PaaS Databases (`--data`) | azure-v2:967-1008 — `databases.list_by_server()`, skip `master` | `GET .../Microsoft.Sql/servers` + `.../databases` per server, `jq select(.name != "master")` | — |
| Data Warehouses | azure-v2:248,268 — enabled by `--data` but never incremented (no Azure counter) | constant 0 row, same as oracle | — |
| Registry Container Images (`--images`) | azure-v2:846-877 — the Cloud Shell path: `az acr repository list` + `show-tags length(@)`, `min(max_image_tags, max(1, tags))` | identical `az acr` calls and clamp (`MAX_IMAGE_TAGS`, default 5) | — |

### Cloud, `--fast` (Resource Graph)

| Count | Official (--graph) | Ours | Deviation |
|---|---|---|---|
| Virtual Machines / Non-OS Disks | azure-v2:544-560 KQL | same KQL via `POST providers/Microsoft.ResourceGraph/resources` | — |
| Scale Set VMs | *(no official graph query)* | ARG `sum(toint(sku.capacity))` | **D3** (configured ≥ live) |
| Container Hosts | azure-v2:667-673 KQL (mv-expand pool sum) | same KQL | — |
| Serverless Functions | azure-v2:755-767 — sites + staticsites counts | same two KQL counts | **D4** (no child functions) |
| ACI / Container Apps / Arc / Stack HCI | *(no official graph queries)* | ARG `count()` per type (PLAN §7) | — |
| PaaS Databases (`--data`) | azure-v2:974-978 KQL | same KQL | — |
| Data Buckets / ACR images | *(data plane)* | not counted; reported `pending` in the summary | **D5** |
| Virtual Machine Sensors | azure-v2 graph mode does not compute them (544-565) | same: 0 under `--fast` | — (matches oracle) |

### Defend (Log Analytics)

| Piece | Official | Ours | Deviation |
|---|---|---|---|
| Workspace discovery | defend-az:300-396 — tenant `microsoft.aadiam` + management groups + subscription diagnosticSettings; resolve GUID/name via `?api-version=2020-08-01`; global GUID dedupe (defend-az:739-786) | `defend_workspaces_from_settings` + `run_defend`, same three URLs/api-versions, same dedupe; `--defend-workspace` supplements | — |
| Usage query | defend-az:413-418 KQL over `RELEVANT_LOG_TYPES` (103-125) | same KQL + same DataType→(name, category) table (`defend_type_info`) | — |
| AzureActivity / StorageBlobLogs fallbacks | defend-az:491-555 `estimate_data_size(*)` when missing from Usage | same KQL, same trigger conditions | — |
| AzureDiagnostics provider fallback | defend-az:445-489, providers picked at 583-596 (KEYVAULT unless AZMS/AZKV seen; STORAGE unless blob logs seen) | same provider selection and KQL | — |
| 30-day normalization + CSV | defend-az:434,473-475,633-647 — `(gb/days)*30`, rows sorted desc, Entra rows "Tenant-wide", `%.2f` | same math (awk), same sort/scope/format | — |

### Azure DevOps opt-in (`--azdo`)

| Piece | Official (ado) | Ours | Deviation |
|---|---|---|---|
| Enumeration | ado:575-598 — projects (top/skip) → repositories | `GET _apis/projects?$top/$skip` → `GET {proj}/_apis/git/repositories` | — |
| Commits window | ado:604-645 — `from_date = now - 90d`, paged | `searchCriteria.fromDate=<90d>&$top=500&$skip=N` | — |
| Developer identity | ado:426-428,661-677 — author email, trimmed/unquoted/lowercased; commits without email skipped | same normalization in `run_azdo` | — |
| Outputs | ado:694,705-720 — per-repo CSV log row, sha256-hashed developer file, cross-VCS rollup | same rows/files/hashing (verified hash-identical to `hashlib`) | — (no `--max-commits-per-repo` cap, so `commit_cap_reached` status never occurs) |

Not carried over from the oracle: `--china/--germany/--gov` cloud endpoints
(public cloud only) and the debug/max-runtime/checkpoint-interval knobs —
`--resume` + per-subscription state covers the same operational need.

## AWS — `wiz-aws.sh`

Oracle: `reference/cloud/aws/resource-count-aws-v2.py` ("aws-v2"),
`reference/defend/aws/log-volume-estimation-aws.py` ("defend-aws").

Scope notes: account set matches the official (`--org` ≙ official `--all`:
ACTIVE org accounts via `organizations list-accounts` + `sts assume-role
role/<--role-name>`, default `OrganizationAccountAccessRole`, aws-v2:386-497;
default = current account ≙ official prompt-less single account;
`--accounts-file` ≙ official `--accounts` + accounts.txt with the same
12-digit validation). Regions via `ec2 describe-regions --no-all-regions`
sorted (aws-v2:500-512); Lightsail region subset via `lightsail get-regions`
(aws-v2:515-527). Pagination: the official loops NextToken/Marker manually;
AWS CLI v2 auto-paginates the same APIs, so counts are equivalent.

### Cloud, accurate mode (default)

| Count (CSV row) | Official | Ours (`wiz-aws.sh` fn → call + jq) | Deviation |
|---|---|---|---|
| Virtual Machines [EC2] | aws-v2:574-624 — describe_instances, skip terminated + tag Vendor=Databricks | `scan_account_region` — `aws ec2 describe-instances`, same jq filters | — |
| Non-OS Disks (EC2) | aws-v2:627-636 — mappings whose `Ebs.VolumeId` ≠ first mapping's | same rule in jq (`$m[0].Ebs.VolumeId` as root) | — |
| Virtual Machine Sensors (EC2) | aws-v2:597 — `instance.get('platform') == 'LINUX_UNIX'`; the real key is `Platform` (windows-only), so this is always 0 | same lowercase `.platform` probe — reproduces the oracle's always-0 behavior byte-for-byte | — (oracle quirk, reproduced) |
| Virtual Machines [Lightsail] + disks + sensors | aws-v2:642-699 — `get_instances`, resourceType Instance, skip terminated; disks: not system, attached; `platform == LINUX_UNIX` | `aws lightsail get-instances` in Lightsail regions only, same jq | — |
| Container Hosts [ECS] | aws-v2:705-745 — container instances per cluster | `aws ecs list-clusters` + `list-container-instances` per cluster | — |
| Container Hosts [EKS] | aws-v2:751-801 — EC2 instances tagged `kubernetes.io/cluster/<name>`, skip terminated | `aws ec2 describe-instances --filters Name=tag-key,Values=kubernetes.io/cluster/<name>` per cluster — **exact**, no k8s API involved | — |
| Serverless Containers [EKS Fargate] | aws-v2:803-859 — k8s API pod count; **on any auth/API error the official returns 1 per Fargate-profile cluster** | always the official fallback: `aws eks list-fargate-profiles` → +1 per cluster with profiles | **D1** (under when >1 pod) |
| Serverless Functions [Lambda] | aws-v2:865-913 — functions + min(max_lambda_versions, versions excl. $LATEST) per function, default 5 | `aws lambda list-functions` + `list-versions-by-function --max-items N`, same clamp | — |
| Serverless Containers [ECS Fargate] + Sensors | aws-v2:919-968 — containers in FARGATE tasks; sensors = task count | `aws ecs list-tasks --launch-type FARGATE` + `describe-tasks` (batched ≤100), same sums | — |
| Serverless Containers [SageMaker] | aws-v2:974-1024 — domains + endpoints counts | `aws sagemaker list-domains` / `list-endpoints` | — |
| Data Buckets (`--data`) | aws-v2:1079-1101 — `list_buckets` count, cap 10000, global control plane | `aws s3api list-buckets`, same cap, once per account | — |
| PaaS Databases (`--data`) | aws-v2:1107-1219 — DocumentDB clusters; RDS clusters filtered to aurora-mysql/aurora-postgresql; RDS instances filtered to the 11-engine list; Redshift clusters | same four calls with identical `--filters` engine lists | — |
| Data Warehouses (`--data`) | aws-v2:1227-1249 — DynamoDB table names, cap 10000 | `aws dynamodb list-tables`, same cap | — |
| Registry Container Images (`--images`) | aws-v2:1033-1071 — min(max_image_tags, imageIds)/repository, default 5 | `aws ecr describe-repositories` + `list-images`, same clamp | — |

### Cloud, `--fast` (Resource Explorer; PLAN §7, D6)

The official AWS script has no fast mode; ours uses `aws resource-explorer-2
search --query-string "resourcetype:..."` `Count.TotalResources` for the
index-visible dimensions (ec2:instance, lambda:function, s3:bucket, rds:db +
rds:cluster, dynamodb:table). Container hosts and serverless containers are
never index-visible as node/container counts and always run the accurate
calls; if the index/view is absent the whole account falls back to accurate
(never zero). No Databricks exclusion, non-OS disk math, or Lambda versions
in the index — all D6.

### Defend (auto-discovery + CloudWatch metrics)

| Piece | Official (defend-aws) | Ours | Deviation |
|---|---|---|---|
| Source selection | flags only (`--defend-*-logs-bucket`), exits when none given (974-985) | **auto-discovers** trails (`cloudtrail describe-trails` → S3 bucket/prefix), VPC flow logs (`ec2 describe-flow-logs`, s3 destinations) and R53 resolver configs per region; flags override/supplement; zero sources = note + continue (PLAN R2) | — (superset; per-bucket math identical) |
| Basic estimation | 372-508 — bucket region; CloudWatch AWS/S3 `IncomingBytes` Sum over 30d (FilterId=EntireBucket); fallback `BucketSizeBytes` StandardStorage growth (latest daily Average − ~30d-ago Average, else latest total); GB = bytes × compression ÷ 1024³ | `defend_basic` / `cw_incoming_bytes` / `cw_bucket_size_growth` — same metrics, dimensions, periods, fallback order, math | — |
| Detailed CloudTrail | 513-654 — base-path discovery (account/org → cloudtrail dir → regions, digest paths dropped), daily prefixes over N days, reservoir-sample 200 objects, gunzip + per-event JSON size by category, ratio × total compressed, per-category proportion, 30-day normalization | same walk/prefixes/sampling (random via `shuf`, evenly spaced without it), same jq categorization (`eventCategory`/`readOnly`), same extrapolation (verified numerically) | sampling is not reservoir-exact — same 200-object budget, different randomness |
| S3 Data events row | **official bug:** categorizer emits `CloudTrail - Data (S3)` but the totals map checks `CloudTrail - Storage (S3)` (defend-aws:257 vs 561), so S3 Data event bytes are silently dropped from the CSV | we populate the `Storage Logs Ingestion GB` row with those bytes | fixes an upstream undercount (sizing bias: rather over than under) |
| CSV | 829-887 — filename, header, `%.2f`, per-source rows | identical shape; one row set per discovered/named bucket | — |

## GCP — `wiz-gcp.sh`

Oracle: `reference/cloud/gcp/resource-count-gcp-v2.py` ("gcp-v2"),
`reference/defend/gcp/log-volume-estimation-gcp.py` ("defend-gcp").

Scope notes: default = every ACTIVE listable project sorted by ID, exactly the
official `--all` path (gcp-v2:518-555; the official's interactive default
prompts for one project). `--projects` ≙ official `--projects` + projects.txt
(names via `projects.get`). Each domain is gated on the project's ENABLED
services from serviceusage, same list and skip message (gcp-v2:463-485,
1004-1009).

### Cloud, accurate mode (default)

| Count (CSV row) | Official | Ours (`wiz-gcp.sh` fn → call + jq) | Deviation |
|---|---|---|---|
| Virtual Machines [Compute] | gcp-v2:598-658 — `instances.aggregatedList`; skip label key `databricks` (label_in_labels) and the no-op `tags.get('Vendor')` check; **GKE nodes count here too** (increment precedes the label check) | `scan_project_accurate` — same aggregatedList REST, same skips, same GKE-nodes-included total | — (oracle quirks reproduced) |
| Container Hosts [GKE] | gcp-v2:631-636,660-663 — instances with label key `goog-gke-node`; live, not configured | same label test on the same call | — |
| Non-OS Disks | gcp-v2:638-650 — non-boot disks of non-GKE instances only; **only displayed with `--data`** but always accumulated | same rule; summary line gated on `--data` like the oracle | — |
| Virtual Machine Sensors | gcp-v2:641-648,666-686 — per boot disk: `disks.get` → `sourceImage` → `images.get`; linux unless description/family contains 'win' (UNKNOWN → linux); image cache | same walk over REST with the same cache and UNKNOWN default | — |
| Kubernetes Sensors / Serverless Containers [GKE Autopilot] | gcp-v2:752-789 — autopilot clusters only: `currentNodeCount // initialNodeCount` per pool → sensors; × `maxPodsPerNode` → serverless containers | `container.googleapis.com/v1/projects/{p}/locations/-/clusters`, same jq | — |
| Serverless Functions [Cloud Functions] | gcp-v2:692-715 — cloudfunctions v2 list, all locations | same REST list, `jq length` | — |
| Serverless Containers [Cloud Run Revisions] | gcp-v2:721-747 — run v1 revisions labelSelector `revisionStatus=active`; count conditions type=ContainerHealthy status=True | same endpoint + labelSelector + condition count | — |
| Data Buckets (`--data`) | gcp-v2:856-880 — storage v1 buckets list, cap 10000 | same, cap applied | — |
| PaaS Databases (`--data`) | gcp-v2:886-962 — Cloud SQL instances + Spanner databases per instance | same two REST walks | — |
| Data Warehouses (`--data`) | gcp-v2:968-991 — BigQuery datasets list | same | — |
| Registry Container Images (`--images`) | gcp-v2:797-848 — per compute region: DOCKER repositories → dockerImages: min(max_image_tags, tags) or 1 if untagged; cap 10000/repo | same walk (regions from `compute.regions.list` like the oracle), same clamps | — |

### Cloud, `--fast` (Cloud Asset Inventory; PLAN §7, D2/D6)

The official GCP script has no fast mode — it prints CAI *instructions*
(gcp-v2:407-427). Ours automates that suggestion: `searchAllResources` per
asset type (Instance split into VMs/GKE via `labels.goog-gke-node:*`,
CloudFunction, Revision, Bucket, sqladmin Instance, spanner Instance,
Dataset), org-scope in one sweep when `--org` is given, per-project fallback
to the accurate path when the CAI API is not enabled. Deviations: index
lag/coverage (D6), Cloud Run counts all revisions not only active ones,
Spanner counts instances not databases, Autopilot serverless containers and
registry images stay pending (D2/D5-style, reported as pending not zero).

### Defend (Cloud Monitoring byte_count)

| Piece | Official (defend-gcp) | Ours | Deviation |
|---|---|---|---|
| Project set | 318-348 — `--project-id`, `--organization-id`, or auto-detect | the run's project scope (same enumeration as cloud mode) | — (superset default: all listable projects) |
| Estimation query | 407-448 — `byte_count` filtered to cloudaudit activity+data_access, ALIGN_RATE 3600s + REDUCE_SUM by (log, resource.type) | `monitoring_series` — same filter/aggregation via REST query params | — |
| Volume math | 432-438 — Σ(rate×3600)/points × 24 → daily bytes → GB × 30 | same formula in jq (`JQ_SERIES_GB`), verified numerically | — |
| Workspace slice | 552-556 — activity AND resource.type=audited_resource | same second query | — (incl. the oracle's per-project double-count of audited_resource in both buckets) |
| Exclusion ratios | 136-146, 483-517 — gke_audit: k8s_cluster 0.14 / gke_cluster 0.12; data_access non-storage: cloud_function 0.20 / gce_instance 0.10 / default 0.14; `--no-exclusion-adjustment` disables | same table + flag | — |
| Sink measurement | 350-405 — sinks with 'wiz' in name/destination; `exports/byte_count` per sink, ALIGN_RATE no reducer | `--use-sink-metrics` / `--sink-name`, same discovery + query | — |
| CSV | 615-629 — `gcp-defend-log-volume-<ts>.csv`, `GCP Monitoring Metrics` rows, `Project: <id>`, `%.2f`, volume-desc sort | identical | — |

## Code — `wiz-code.sh`

Oracles: `reference/code/github/active-developer-count-github.py` ("gh"),
`reference/code/gitlab/active-developer-count-gitlab.py` ("gl"),
`reference/code/hcp-terraform/active-developer-count-hcp.py` ("hcp").
Azure DevOps counting is mapped under the Azure section (it ships inside
`wiz-azure.sh`). All providers share the officials' 90-day window (`--days`),
sha256-hashed developer files unless `--decrypt` (gh:459-463), the
`slugify` filename rule (gh:179-186), and the cross-VCS
`active-developers.txt` rollup (gh:188-201).

| Piece | Official | Ours (`wiz-code.sh`) | Deviation |
|---|---|---|---|
| GitHub repositories | gh:296-328 — org repos (`type=all, sort=full_name`), else the token's `/user/repos`; `--repo` narrows | same REST endpoints, paged `per_page=100` | — |
| GitHub membership gate | gh:354-386,405-407 — collaborators list; on failure count all authors (org_access=False) | `GET /repos/{r}/collaborators`; 403/empty → no gate, same message | — |
| GitHub developer identity | gh:388-445 — dedupe by author **id**; export email: single → itself; multiple → drop `users.noreply` unless none remain; then most-commits | same rules in one jq reduction (`run_github`), mock-verified per case | — |
| GitLab projects | gl:300-373 — group (first search hit, include_subgroups) / single project / membership projects, archived excluded | same `/api/v4` endpoints + params | — |
| GitLab membership gate | gl:390-405,462-476 — `members/all`; skip committers not a member **by display name** or not `state=active` | same name+state test | — |
| GitLab developer identity | gl:478-486 — dedupe by committer email | same | — |
| HCP scope | hcp:398-457 — all orgs → memberships, workspaces; workspace + org runs, `filter[source]=tfe-ui,tfe-api,tfe-configuration-version`, `filter[timeframe]=year`, run-id dedupe | same endpoints/filters, JSON:API `links.next` pagination | — |
| HCP developer identity | hcp:324-366 — UI/API runs: creator user unless service account, keyed by membership email else user id; CV runs: ingress-attributes `sender-username` | same, with the officials' user/service-account caches | — |
| Outputs | gh:455-471 / gl:485-499 / hcp:369-385 — `<provider><slug>-developers.txt`, `-developers-log.txt` CSV headers with the dynamic day window, `hcpt-developers.txt`, rollup | identical filenames/headers (contract-tested) | — |

## M365 — `wiz-365.ps1`

Nothing to map: `wiz-365.ps1` **is** the hardened official PowerShell script
(`reference/saas/microsoft-365/365_Sizing_Script.ps1` promoted verbatim), so
it is its own oracle (PLAN.md §5, §10). Verify with:

```sh
diff wiz-365.ps1 reference/saas/microsoft-365/365_Sizing_Script.ps1
```
