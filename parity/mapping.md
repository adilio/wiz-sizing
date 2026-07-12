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

*Pending — filled in Phase 2.*

| Count (CSV row) | Official | Ours | Deviation |
|---|---|---|---|

## GCP — `wiz-gcp.sh`

*Pending — filled in Phase 3.*

| Count (CSV row) | Official | Ours | Deviation |
|---|---|---|---|

## Code — `wiz-code.sh`

*Pending — filled in Phase 4.*

| Count (output) | Official | Ours | Deviation |
|---|---|---|---|

## M365 — `wiz-365.ps1`

Nothing to map: `wiz-365.ps1` **is** the hardened official PowerShell script
(`reference/saas/microsoft-365/365_Sizing_Script.ps1` promoted verbatim), so
it is its own oracle (PLAN.md §5, §10). Verify with:

```sh
diff wiz-365.ps1 reference/saas/microsoft-365/365_Sizing_Script.ps1
```
