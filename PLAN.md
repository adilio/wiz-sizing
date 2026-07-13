# Wiz Sizing — Bash-per-CSP Rewrite Plan

> **Status: STRUCTURALLY COMPLETE (2026-07-12), hardened 2026-07-13.** All six
> phases (§14) ran to the §17 Definition of Done in one autonomous session;
> a second review pass then fixed five defects (see the hardening addendum
> below). The live parity diff per CSP remains the one open gate — it needs a
> real tenant/account (expected §17 end-state).
>
> Original preamble: This supersedes the earlier Python single-file-per-CSP
> design (now in git history). The product is now **one curl-able bash script per
> cloud** (Azure/AWS/GCP), hitting REST APIs / cloud CLIs directly with the user's
> existing shell session — no Python modules, no Az/Graph modules. The one
> deliberate exception is **M365, which keeps the proven PowerShell script**
> (`wiz-365.ps1`) as an opt-in, because that domain's consent flow and field
> hardening make PowerShell the best UX (§5, §10). The official Wiz sizing scripts
> remain the source of truth for all counting logic and output.
>
> **Implementing this plan?** Read **§16 (Execution protocol)** and **§17
> (Definition of Done)** first, then work §14 Phase 0 → 5 without stopping between
> phases — run to §17, don't pause for approval you don't need.

## Implementation report (2026-07-12)

### What shipped

All four bash entrypoints, built Phase 0 → 5 per §14, each reproducing its
official script's counting rules and exact CSV filenames/headers:

- **`wiz-azure.sh`** — ARM REST + Resource Graph cloud counting (live VMSS /
  child-function / `--data` / `--images` drill-downs); Defend via Log
  Analytics KQL with workspace discovery through tenant (Entra),
  management-group and subscription diagnostic settings; AzDO opt-in with the
  30s default-skip prompt; `--m365` hand-off to `wiz-365.ps1` (promoted
  verbatim — byte-identical to the hardened reference).
- **`wiz-aws.sh`** — per account×region CLI counting; `--org` via
  `organizations` + `sts assume-role` with sessions re-assumed near expiry;
  Defend **auto-discovers** CloudTrail/VPC-flow/R53 buckets (R2), basic
  CloudWatch estimation by default, full `--defend-detailed` S3-sampling port.
- **`wiz-gcp.sh`** — REST counting gated on each project's enabled services;
  Defend via Monitoring `byte_count` (ALIGN_RATE formula, exclusion ratios,
  `--use-sink-metrics`); `--fast` automates the official's own CAI guidance,
  org-scope in one sweep with `--org`.
- **`wiz-code.sh`** — GitHub / GitLab / HCP Terraform developer counts, masked
  token prompts reusing `*_TOKEN` env vars, sha256-hashed outputs.

Shared plumbing per §6/§11/§12 in all four: per-audience token refresh,
per-scope temp files merged by a single writer, `--resume`, INT/TERM partial
output, `--max-parallel`, stderr progress, error rollups, and a `--dry-run`
that provably makes zero cloud calls.

### Verification

- No-creds gates: `shellcheck` clean; **all 27 bats tests pass with zero
  skips** (contract + smoke + mock e2e; cloud CLIs stubbed); the python
  safety-net suite and `parity/diff.sh <csp> --stub` also pass. CI runs all
  of it.
- **Committed mock end-to-end suite** (`tests/mock_e2e.bats` +
  `tests/mocks/`): the real cloud-counting paths of all three CSP scripts run
  against fixture APIs (stubbed `curl`/`az`/`aws`/`gcloud`, no network) and
  the produced `<csp>-resources.csv` files are diffed against hand-verified
  expected CSVs. The suite also pins fast-mode fallback (a mid-sequence
  index/ARG/CAI failure discards partial fast counts and reruns accurately),
  GCP `--org` scoping (out-of-org projects never contacted), and one-token-
  per-audience acquisition. *(The original session's broader mock runs —
  Defend volume math, wiz-code — were ad hoc and not committed; only what is
  in `tests/` counts as verified.)*
- `parity/mapping.md` is complete for every CSP: per-count citations,
  official source line → bash call + `jq` reduction.

### Notable findings (ledger updated)

- **D1 shrank:** the official EKS *node* count is EC2-tag-based
  (`kubernetes.io/cluster/<name>`), so bash matches it exactly; only Fargate
  pods use the official's own 1-per-cluster error fallback.
- **D2 shrank:** the official GKE node count reads live `goog-gke-node`
  instance labels (not the k8s API); accurate mode matches exactly — D2 now
  applies to `--fast` only.
- **Upstream bug fixed:** the official AWS Defend detailed mode drops S3 Data
  event volume via a category-name mismatch (`Data (S3)` vs `Storage (S3)`);
  our port populates the Storage row (bias-high, documented in the mapping).
- Mock-testing caught two real bash pitfalls before ship: `set -u` +
  empty `local -A` arrays (bash 5.2+), and consecutive-tab field collapse in
  `IFS=$'\t' read`.

### Hardening addendum (2026-07-13)

A post-ship review found five defects in the implementation report's claims;
all are now fixed and regression-pinned by the committed mock e2e suite:

1. **Fast-mode fallback was partial.** Azure `--fast` converted Resource
   Graph failures into zero counts with no fallback; AWS/GCP fell back only
   when the *first* index query failed (later failures became zeros). Now any
   fast-query failure discards that scope's partial fast counts and reruns
   the accurate path — fast can never silently zero (§7).
2. **GCP `--org` didn't scope enumeration.** The accurate path and Defend
   scanned every listable project regardless of `--org`. `enumerate_projects`
   now walks the org's folder tree (cloudresourcemanager v2) and keeps only
   ACTIVE projects parented inside it, so accurate/Defend match the `--fast`
   org sweep's scope.
3. **Azure/GCP token caching never took effect.** Tokens were cached in shell
   variables, but every HTTP call runs inside `$(...)` subshells, so each
   request re-invoked `az`/`gcloud`. The cache is now a 0600 file under the
   run's temp dir — it survives subshells and is shared across parallel
   workers (one acquisition per audience per run).
4. **`parity/diff.sh` couldn't guarantee same-scope runs.** Live mode now
   *requires* `--scope <ID>` and passes it to both sides (`--id` officially;
   `--subscription`/`--accounts-file`/`--projects` for ours).
5. **The mock e2e claim wasn't reproducible.** The suite is now committed
   (`tests/mock_e2e.bats`) and wired into CI.

### Where things stand

- **Branches:** merged — `main` == `origin/main` in both repos (wiz-sizing
  bash rewrite; wiz-tools sizing stub).
- **The one open item** (expected §17 end-state): the **live parity diff**
  per CSP needs a real tenant/account
  (`parity/diff.sh <csp> --scope <ID>`). Until each CSP passes it, its
  `wiz-<csp>.py` + `tools/` stay in-tree as the safety net, noted in README.
  Everything else in §14/§17 is ticked.

---

## 1. Goals and non-goals

### Goals

1. **Simplicity for the user, above all.** One `curl | run` bash script per CSP
   (Azure, AWS, GCP). What you paste is what runs. No install, no modules, no
   build step. Uses only what ships in each cloud shell: `az` / `aws` / `gcloud`
   + `jq`.
2. **Fidelity.** Output near-identical to the official scripts (same CSV
   filenames, headers, resource taxonomy, counting rules). Every place bash+REST
   cannot reproduce a count exactly is documented in the **deviation ledger**
   (§9) — no silent drift.
3. **Fast estimate mode** alongside the accurate default, with its deviations
   documented explicitly.
4. **Default run = core cloud resources + Wiz Defend ingest**, in a single pass.
5. **Opt-in domains attach cleanly:** code/repo counting (AzDO for Azure; a
   separate `wiz-code.sh` for GitHub/GitLab/HCP) and M365 identity — never in a
   CSP default.
6. **No new permissions.** Read-only, using the user's existing elevated session.
   No app registrations, service principals, or consent grants for the default run.
7. **Resilience at scale.** Long tenant scans survive token expiry (re-fetch from
   the CLI per audience), interruption (incremental writes + resume), and partial
   failure (per-scope isolation, error rollup).
8. **Cloud-shell-tuned UX.** Live progress, visible partial results, a final
   summary block that maps 1:1 to the billable-units calculator.

### Non-goals

- **Deduplication across the three scripts is explicitly not a goal.** Each
  `wiz-<csp>.sh` is self-contained and may repeat helper logic (auth, jq filters,
  CSV writer, progress). **Portability beats DRY.** No shared library to source.
- **No long-tail CSPs in this plan** (OCI, Alibaba, Linode, Snowflake, vSphere).
  They remain the standalone `reference/` scripts; consolidate one only on demand.
- **No AWS ASM (`asm-resource-count-aws.py`) in the default.** Deferred; a later
  opt-in if needed (its ~20% error rate makes it a poor default anyway).
- **No cross-cloud launcher / auto-detect.** Each cloud shell is single-cloud.
- **No packaging (PyPI, brew, containers).** It would reintroduce the install step
  the design deletes.

## 2. Source-of-truth mapping

The official script is the counting spec; our bash reproduces it. Where the
hardened `wiz-tools` forks fixed real bugs, those fixes carry into our logic.

| Official script (source of truth) | Our target | Domain | When it runs |
|---|---|---|---|
| `cloud/azure/resource-count-azure-v2.py` | `wiz-azure.sh` | Azure cloud resources | default |
| `defend/azure/log-volume-estimation-azure.py` | `wiz-azure.sh` | Azure Defend ingest | default |
| `code/azure-devops/active-developer-count-ado.py` | `wiz-azure.sh` (AzDO) | repo/dev count | **opt-in** (prompt-if-detected / flag) |
| `saas/microsoft-365/365_Sizing_Script.ps1` | `wiz-365.ps1` (PowerShell, hardened) | identity/drives | **opt-in** (`wiz-azure.sh --m365` hands off; also standalone) |
| `cloud/aws/resource-count-aws-v2.py` | `wiz-aws.sh` | AWS cloud resources | default |
| `defend/aws/log-volume-estimation-aws.py` | `wiz-aws.sh` | AWS Defend ingest | default (auto-discover buckets) |
| `cloud/gcp/resource-count-gcp-v2.py` | `wiz-gcp.sh` | GCP cloud resources | default |
| `defend/gcp/log-volume-estimation-gcp.py` | `wiz-gcp.sh` | GCP Defend ingest | default |
| `code/github/active-developer-count-github.py` | `wiz-code.sh` | GitHub dev count | **opt-in domain** |
| `code/gitlab/active-developer-count-gitlab.py` | `wiz-code.sh` | GitLab dev count | **opt-in domain** |
| `code/hcp-terraform/active-developer-count-hcp.py` | `wiz-code.sh` | HCP active devs | **opt-in domain** |
| `cloud/{alibaba,oci,linode,snowflake,vmware-vsphere}` | — | long-tail | out of scope (stay in `reference/`) |
| `cloud/aws/asm-resource-count-aws.py` | — | ASM | deferred |

**Where the counting logic lives:** in each `wiz-<csp>.sh`, inline. There is no
shared engine. The official Python under `reference/` is the *specification and
parity oracle* only — it is never curled or shipped.

## 3. Target repo structure (wiz-sizing)

```
wiz-sizing/
├─ README.md              # the one authoritative doc: per-CSP one-liners, modes, outputs
├─ PLAN.md                # this file
├─ LICENSE                # MIT (unchanged)
├─ wiz-azure.sh           # curl-able; cloud + Defend default; AzDO + M365 opt-ins
├─ wiz-aws.sh             # curl-able; cloud + Defend default
├─ wiz-gcp.sh             # curl-able; cloud + Defend default
├─ wiz-code.sh            # curl-able; GitHub / GitLab / HCP dev counts (opt-in domain)
├─ wiz-365.ps1           # curl-able; M365 identity/drives (PowerShell, opt-in; hand-off target of wiz-azure.sh --m365)
├─ reference/             # official + hardened source scripts — parity oracle, NOT shipped
│  ├─ cloud/  defend/  code/  saas/    # moved verbatim from wiz-tools/sizing-scripts
│  └─ SCRIPT_STATUS.md                 # provenance ledger (wiz-copy / modified)
├─ parity/                # parity-harness scaffold (see §8) — grows when reference envs land
│  ├─ diff.sh             # run official vs ours against a live env, diff CSVs by type
│  └─ mapping.md          # per-count structural map: official line → our query
└─ tests/                 # no-creds gates
   ├─ contract.bats       # CSV filenames + headers per mode (the hard contract)
   └─ smoke.bats          # --help / --list / --dry-run run with no cloud session
```

The retired Python (`wiz-*.py`, `tools/_engine.py`, `tools/config_*.py`,
`tools/build_wiz.py`) is removed **per-CSP as its bash replacement reaches
parity**, not before — the working Python is the safety net during the cutover.
**"Reaches parity" is a hard gate, defined as all three of:** (1) contract tests
green, (2) `parity/mapping.md` complete and reviewed for that CSP, and (3) at
least **one live `parity/diff.sh` pass against a real tenant/account** for that
CSP. Structural checks alone never trigger deletion — until a live diff exists,
the Python stays in-tree even if the bash script ships.

## 4. Per-CSP entrypoint design

Every `wiz-<csp>.sh` shares this shape (re-implemented independently in each):

```
wiz-<csp>.sh [MODE] [--fast] [--data] [--images] [--resume] [--output-dir DIR]
             [scope flags] [--dry-run] [--quiet] [opt-in flags]
```

- **No arg → interactive menu** (profiles first, then individual domains),
  numbered prompts (robust in cloud-shell web terminals).
- **Subcommand form** for non-interactive use (`wiz-aws.sh cloud --fast`,
  `wiz-azure.sh defend`, `wiz-azure.sh all`).
- **Default (`all`/no subcommand)** = cloud resources **+ Defend ingest** in one
  pass, accurate mode, writing the official CSV filenames.

### Dimensions each default covers

Straight from the official billing taxonomy:

| Dimension | Azure | AWS | GCP |
|---|---|---|---|
| Virtual Machines (+ non-OS disks with `--data`) | Compute VMs, Scale Set VMs | EC2, Lightsail | Compute instances |
| Container Hosts | AKS nodes | EKS/ECS nodes | GKE nodes |
| Serverless Functions | Functions, App Services | Lambda | Cloud Functions |
| Serverless Containers | ACI, Container Apps | ECS containers, SageMaker, EKS-Fargate | GKE Autopilot, Cloud Run (active) |
| Asset Metadata | Arc, Stack HCI | — | — |
| Buckets (`--data`) | Blob containers | S3 | Buckets |
| PaaS Databases (`--data`) | Azure SQL | RDS/Aurora/DocumentDB/Redshift | Cloud SQL, Spanner |
| Data warehouses (`--data`) | — | DynamoDB | BigQuery datasets |
| Registry images (`--images`) | ACR | ECR | GCP registry |
| **Defend ingest** | Log Analytics workspaces (KQL Usage) | CloudTrail / VPC Flow / R53 Resolver (S3+CloudWatch) | Monitoring `byte_count` / sink metrics |

`--data` and `--images` remain opt-in extras (they materially lengthen the scan),
matching the official flags exactly.

### REST/CLI realization (accurate default)

- **Azure** — `POST management.azure.com/providers/Microsoft.ResourceGraph/resources`
  with KQL for the index-visible types (VMs, SQL DBs, AKS agent-pool sums, ACI,
  Container Apps, Arc, Stack HCI, web sites). Deep types the index can't serve are
  enumerated live over ARM REST: VMSS instances, function children, storage
  containers (`--data`, storage data-plane token), ACR tags (`--images`, registry
  token). We hit the Resource Graph REST endpoint directly rather than depending
  on the `az resource-graph` extension being installed.
- **AWS** — `aws` CLI directly (SigV4 via ambient creds; no bearer juggling).
  `describe-instances`, `lightsail`, `ecs`, `eks` (nodegroup `desiredSize` + ASG),
  `lambda`, `sagemaker`, `s3api`, `rds`, `dynamodb`, `ecr` — across regions, and
  across org member accounts via `organizations list-accounts` + `sts assume-role`
  (`OrganizationAccountAccessRole` or `--role-name`, 900s sessions).
- **GCP** — REST to `compute` (instances `aggregatedList`), `container` (node pool
  sizes), `cloudfunctions`, `run`, `storage`, `sqladmin`, `spanner`, `bigquery`,
  across projects from `cloudresourcemanager`; org scan enumerates projects.

**Defend ingest auto-discovers its sources by default** (best UX — the operator
shouldn't have to know bucket names). AWS: derive the log buckets from
`cloudtrail describe-trails` (→ S3 bucket/prefix), VPC flow-log configs, and R53
resolver query-log configs, then read `cloudwatch get-metric-statistics`. The
default is the official script's default: **metrics-based basic estimation**
(fast, no object downloads); `--defend-detailed` opts into S3 object sampling for
a tighter CloudTrail breakdown, exactly as the official flag does (slower, minor
API cost — same trade-off as upstream). Azure discovers Log Analytics workspaces
via diagnostic settings; GCP reads Monitoring `byte_count` / sink metrics. In all
three, explicit `--defend-*-bucket` / scope flags **override or supplement**
discovery, and if nothing is discoverable and no flags are given, Defend prints a
one-line "no log sources found — pass `--defend-*-bucket`" note and the run
continues (cloud counts still complete). Defend never hard-fails the scan.

## 5. Opt-in domains

- **AzDO (Azure only).** After the Azure default completes, if the environment
  *looks like* it has Azure DevOps (best-effort probe: `az devops configure -l`
  default org, or an org env var), **prompt**: "Include Azure DevOps repo/dev
  counting? [y/N]" — with a **short timeout (e.g. 30s) that defaults to _skip_**,
  so an unattended/CI run is never blocked. Flags override the prompt entirely:
  `--azdo [--org ORG]` forces it on non-interactively; `--no-azdo` forces it off.
  Uses the **DevOps token audience** (§6), never the default's management token.
- **M365 (Azure only).** `--m365` flag, opt-in, never prompted-by-default. Runs
  the hardened PowerShell script `wiz-365.ps1` — `wiz-azure.sh --m365` fetches and
  runs it via `pwsh` when present (Azure Cloud Shell has it), else prints the
  `wiz-365.ps1` one-liner. `wiz-365.ps1` is also a first-class curl-able
  entrypoint on its own. It keeps the official flow: device-code auth + a
  **self-cleaning temporary Entra app** that grants the correct Graph directory
  scopes, then deletes itself. This is verbatim-hardened PowerShell (no bash
  reimplementation), so there is nothing to parity-diff for M365 — it *is* the
  reference. Consent trade-off in §10.
- **Code sizing (`wiz-code.sh`).** A separate entrypoint, not tied to any CSP,
  covering GitHub / GitLab / HCP Terraform active-developer counts. Token-based
  (masked prompt; reuses `GITHUB_TOKEN` / `GITLAB_TOKEN` / `HCP_TOKEN`). This
  keeps repo sizing out of every CSP default, where most AWS/GCP users don't want
  it.

## 6. Per-audience token handling (Azure)

Azure is the only CSP that needs explicit bearer tokens. Each audience is fetched
independently via `az account get-access-token --resource <aud>` and **refreshed
independently** when it nears expiry (parse `expiresOn`, refresh at <5 min left).
No caching a single token, no manual refresh-token handling.

| Audience (resource) | Used for | Default run? |
|---|---|---|
| `https://management.azure.com` | ARM + Resource Graph | **yes** |
| `https://api.loganalytics.io` | Log Analytics query (Defend) | **yes** |
| `https://storage.azure.com` | Blob container enumeration (`--data`) | with `--data` |
| ACR token exchange (per-registry, from the ARM token) | Registry image counts (`--images`) | with `--images` |
| `499b84ac-1321-427f-aa17-267ca6975798` (Azure DevOps) | AzDO REST | opt-in `--azdo` |

M365/Graph is **not** on this table: `wiz-365.ps1` does its own device-code +
temporary-app auth (§5, §10), independent of the bash script's `az` tokens.

**AWS** has no bearer model: resilience = re-`assume-role` when a member-account
session nears expiry. **GCP** = re-run `gcloud auth print-access-token` on expiry;
one audience only.

## 7. Fast estimate mode

`--fast` trades depth for speed and is best-effort:

- **Azure** — Resource Graph aggregations for everything ARG can serve, skipping
  the live drill-downs: VMSS via `sku.capacity`, AKS via `sum(agentPoolProfiles.count)`,
  `count()` for VMs / SQL / ACI / Container Apps / Arc / Stack HCI / web sites.
- **AWS** — AWS Resource Explorer aggregated search (or a Config aggregator where
  present) for the index-visible counts.
- **GCP** — Cloud Asset Inventory (`cloudasset.searchAllResources` / aggregated
  export) for the index-visible counts.

**Graceful fallback:** if the fast source isn't available (Resource Explorer index
not created, Cloud Asset API not enabled), `--fast` prints a one-line note and
**falls back to the accurate path for that dimension** — it never fails the run or
silently returns zero.

## 8. Parity strategy

**Be honest about what changed:** the previous Python design was byte-identical
*by construction* — it embedded the official scripts verbatim. A bash rewrite
means **every count is a reimplementation**, so fidelity is no longer free; it is
only as strong as the validation below. That is the cost of the bash-everywhere
simplicity win, and it's why this section and the §3 retirement gate carry real
weight rather than being ceremony.

No live reference environment exists yet, so parity is built in layers that don't
require one, plus a scaffold to plug reference envs in later.

1. **Structural map (`parity/mapping.md`).** For every count, cite the official
   script's source line and the exact bash query + `jq` reduction that reproduces
   it. A reviewer can diff intent side-by-side with no credentials.
2. **CSV contract tests (`tests/contract.bats`).** Assert each mode's default
   **filename** and **header row** match the official script's `writerow` exactly
   (including the dynamic `(Last N Days)` f-string and Defend's `f"{gb:.2f}"`).
   Runs in CI with no cloud session.
3. **Deviation ledger (§9).** Every known non-identical count, why, and its
   direction (we bias high for sizing).
4. **Diff harness (`parity/diff.sh`, scaffold).** Given a reference env's session,
   runs the official Python (from `reference/`) and our bash against the same
   scope, then diffs the CSVs by resource type and emits a pass/fail report. Built
   now as a runnable scaffold with a stub env; wired to real tenants when you add
   them. This is the only place true byte-diffing happens for the cloud modes.

## 9. Deviation ledger (intentional, documented)

| # | Count | Mode | Deviation | Direction | Why |
|---|---|---|---|---|---|
| D1 | EKS Fargate pods (Serverless Containers) | **both** | *(Revised during Phase 2 — smaller than planned.)* EKS **nodes** turn out to be exactly reproducible: the official counts EC2 instances tagged `kubernetes.io/cluster/<name>`, not live k8s nodes, so bash matches it 1:1 (the earlier desiredSize approximation was unnecessary). Only the **Fargate pod count** used the k8s API (eks_token + kubernetes), with a documented fallback of **1 per cluster with Fargate profiles** on any error; bash always uses that fallback. | under (when Fargate clusters run >1 pod) | k8s API auth in pure bash needs extra tooling; the official's own error path defines the fallback. |
| D2 | GKE container hosts | `--fast` only | *(Revised during Phase 3.)* Accurate mode matches the official exactly — both count live instances carrying the `goog-gke-node` label from `compute.instances.aggregatedList`, and Autopilot node/pod counts come from the clusters API in both. Only `--fast` deviates: CAI label-indexed instance counts (index lag) and no Autopilot pods-per-node data (reported pending). | index-lag either way; Autopilot pods pending | The oracle never queries the k8s API for GKE; the earlier assumption that it did was wrong. |
| D3 | Azure VMSS instances | `--fast` only | `sku.capacity` (configured) vs live instances. Accurate mode enumerates live. | ≥ live under autoscale | The N+1 the fast path is built to skip. |
| D4 | Azure child functions | `--fast` only | ARG counts web *sites*, not functions inside them. Accurate mode enumerates. | under | ARG can't see child functions. |
| D5 | Azure blob containers / ACR images | `--fast` only | ARG can't see data-plane; fast mode marks them `pending` (not counted). Accurate mode enumerates. | under (shown as pending, not zero) | Data-plane invisible to the index. |
| D6 | AWS/GCP fast counts | `--fast` only | Depend on Resource Explorer / Cloud Asset Inventory freshness and enablement; auto-fallback to accurate when absent. | index-lag either way | Best-effort by design (§7). |

*(A prior D7 — M365 counts limited by the user's existing Graph consent — is
**resolved** by keeping the PowerShell script with its temporary-app grant (§5,
§10). M365 counts match the official script with no deviation.)*

Sizing principle throughout: **rather over than under.** Where a deviation has a
direction, it leans high so a quote is never short.

**Escape hatch for D1/D2 (deferred, YAGNI):** if an engagement ever needs exact
*live* EKS/GKE node counts, add an opt-in `--deep-k8s` that shells out to
`kubectl` for clusters the operator already has access to. Not built until
something demands it — the configured/desired count is the accepted default.

## 10. Auth model (and the M365 consent tension)

- **Default run is read-only and permission-neutral:** management/inventory reads
  with the user's existing elevated session. No app registration, no SP, no
  consent grant. Azure = per-audience tokens from `az`; AWS = ambient creds +
  read-only STS assume-role; GCP = `gcloud` token (org scan needs Viewer on
  projects, which the user already holds or doesn't).
- **M365 is the one scoped exception to "no new permissions," by design.** The
  official M365 script *creates a temporary Entra app* to grant itself Graph
  directory-read scopes, then deletes it. Rather than reimplement M365 in bash and
  inherit a consent gap (the user's ambient Graph token usually lacks
  `Directory.Read.All` / `Sites.Read.All`, which would silently undercount), we
  **keep that proven flow**: `wiz-365.ps1` uses device-code auth + a self-cleaning
  temporary app. The app is opt-in (`--m365` only), isolated to the M365 domain,
  and deleted when the script finishes — so the **default run stays fully
  permission-neutral**, and M365, when explicitly requested, produces an accurate
  count instead of a hobbled one. This is why M365 is opt-in and never part of the
  Azure default.

## 11. Long-running & resumability

- **Incremental writes — race-safe by construction.** Each scope (subscription /
  account / project) writes to its **own temp file**; a **single writer** merges
  completed scopes into the CSV. Parallel workers never append to the shared CSV
  directly (concurrent `>>` from subshells can interleave partial lines). Partial
  output is always on disk, and the merge point doubles as the `--resume`
  bookkeeping point.
- **Checkpoint state.** A sidecar `.wiz-<csp>-state` records completed scopes and
  running totals. `--resume` skips completed scopes and continues.
- **Signal handling.** A `trap` on `INT`/`TERM` flushes the current CSV, writes
  the summary + error rollup, and exits with usable partial output.
- **Token refresh mid-scan** per §6 — independent per audience, driven off each
  token's real expiry, re-fetched from the CLI (never a manually managed refresh
  token).
- **Bounded concurrency** with no extra deps: a job-slot loop / `xargs -P N`
  capped by a single `--max-parallel`, so in-flight calls stay throttle-friendly
  and cloud-shell-friendly.

## 12. Output / UX for cloud shells

- **Progress to stderr, data to stdout/CSV.** A live line — `scope 12/48 ·
  VMs 1,204 · funcs 88 · elapsed 3m10s` — updated in place when a TTY, plain
  lines when piped.
- **Final summary block** that names the billable-units calculator's own fields,
  so the operator pastes numbers instead of transcribing a CSV.
- **Error rollup** at the end: "N scopes scanned, M skipped (no access), K
  errors → `*-errors-log.txt`". Failures are never silent.
- **CSV filenames/headers unchanged** from the official scripts (the §8.2
  contract), including the `-log` sidecars.
- **`--quiet`** for scripted use; **`--dry-run`** prints the calls it would make.

## 13. wiz-tools stub & migration steps

1. **Move** `wiz-tools/sizing-scripts/*` → `wiz-sizing/reference/` (parity oracle),
   preserving `SCRIPT_STATUS.md` provenance. **Promote** the hardened
   `saas/microsoft-365/365_Sizing_Script.ps1` to a shipped root `wiz-365.ps1`
   (it runs verbatim — no bash reimplementation, so it doubles as its own oracle).
2. **Stub only the sizing part of `wiz-tools`.** `wiz-tools` *stays* as a repo —
   its non-sizing tools (`wiz-shi-report-viewer`, the published `docs/` pages)
   remain untouched. Replace the `sizing-scripts/` tree with a short pointer
   README to `wiz-sizing`, and update the sizing rows/links in the `wiz-tools`
   README and landing page to point at `wiz-sizing`. Nothing else in `wiz-tools`
   moves or changes.
3. **Build bash scripts** in `wiz-sizing` phase-by-phase (§14).
4. **Retire Python per-CSP** as each bash script passes parity; the Python and
   `tools/` build leave via git history once all three cut over.
5. **Rewrite `wiz-sizing/README.md`** as the single authoritative doc (per-CSP
   one-liners, modes, outputs, auth, opt-ins).

## 14. Phased implementation checklist

**Phase 0 — repo prep**
- [x] Move `sizing-scripts/` → `reference/`; stub `wiz-tools`.
- [x] `tests/contract.bats` + `tests/smoke.bats`; wire `shellcheck` as a lint gate; CI runs all three (no creds).
- [x] `parity/mapping.md` skeleton + `parity/diff.sh` scaffold.
- [x] **Done when:** `reference/` populated, wiz-tools sizing stub in place, CI green (`shellcheck` + both `.bats` suites) with no cloud session.

**Phase 1 — `wiz-azure.sh` (the template)**
- [x] Management-token acquisition + per-audience refresh helper.
- [x] Accurate cloud count via ARG REST + live drill-downs (VMSS, functions,
      `--data` containers, `--images` ACR).
- [x] Defend ingest via Log Analytics KQL over `api.loganalytics.io`.
- [x] `--fast` mode + deviation notes (D3–D5).
- [x] Incremental write, `--resume`, signal trap, progress UX, summary block.
- [x] AzDO opt-in (prompt-if-detected + `--azdo`, DevOps audience).
- [x] M365 opt-in: promote hardened `365_Sizing_Script.ps1` → `wiz-365.ps1`;
      `wiz-azure.sh --m365` hands off via `pwsh` (else prints the one-liner).
- [x] Parity map filled for Azure. *(Python retirement stays gated on the §3 live diff — `wiz-azure.py` retained, awaiting live parity.)*
- [x] **Done when:** `wiz-azure.sh` passes `shellcheck` + contract + smoke; `--dry-run` prints the intended calls with no `az` session; `cloud` / `defend` / `all` / `--fast` / `--resume` / `--azdo` / `--m365` all parse and dry-run; the Azure section of `parity/mapping.md` is complete. (Live parity diff + Python retirement are gated per §3, not part of this DoD.)

**Phase 2 — `wiz-aws.sh`**
- [x] `aws` CLI accurate count; org via `organizations` + `sts assume-role`.
- [x] Defend ingest: auto-discover CloudTrail/VPC/R53 buckets, CloudWatch metrics,
      optional `--defend-detailed` S3 sampling.
- [x] `--fast` via Resource Explorer w/ fallback; deviations D1, D6.
- [x] Same UX/resume/progress; parity map. *(`wiz-aws.py` retained, awaiting live parity per §3.)*
- [x] **Done when:** `wiz-aws.sh` passes the gates and dry-runs every documented mode/flag with no `aws` session; org assume-role + Defend auto-discovery paths dry-run; AWS section of `parity/mapping.md` complete.

**Phase 3 — `wiz-gcp.sh`**
- [x] REST accurate count; org project enumeration.
- [x] Defend ingest via Monitoring `byte_count` / sink metrics.
- [x] `--fast` via Cloud Asset Inventory w/ fallback; deviations D2, D6.
- [x] Same UX/resume/progress; parity map. *(`wiz-gcp.py` retained, awaiting live parity per §3.)*
- [x] **Done when:** `wiz-gcp.sh` passes the gates and dry-runs every documented mode/flag with no `gcloud` session; org project enumeration + CAI fast path dry-run; GCP section of `parity/mapping.md` complete.

**Phase 4 — `wiz-code.sh`**
- [x] GitHub / GitLab / HCP active-developer counts, masked tokens, opt-in domain.
- [x] **Done when:** `wiz-code.sh` passes the gates, prompts masked tokens (reusing `GITHUB_TOKEN`/`GITLAB_TOKEN`/`HCP_TOKEN`), and dry-runs all three with no token.

**Phase 5 — finalize**
- [x] Rewrite README; confirm `wiz-tools` stub. *(Removal of `tools/` + the Python entrypoints is gated per §3 — no CSP has a live parity pass yet, so all are retained with the "awaiting live parity" note in README.)*
- *Deferred, not a checkbox (external dependency; §17's carve-out):* wire
  `parity/diff.sh <csp> --scope <ID>` to the first reference env when one
  exists. No reference env exists yet; §17 explicitly counts reaching this
  state as a complete run.
- [x] **Done when:** README is the single authoritative doc; for each CSP that cleared its §3 live gate, `tools/` + that Python entrypoint are removed (others retained with an "awaiting live parity" note); wiz-tools sizing stub confirmed; `parity/diff.sh` wired to a reference env if one exists.

## 15. Assumptions & resolved decisions

**Assumptions (proceeding on these unless corrected):**
- `jq` is present in all three cloud shells; scripts require only `az`/`aws`/`gcloud` + `jq`.
- Long-tail CSPs and AWS ASM are out of scope (stay in `reference/`).
- Curl URLs stay on `github.com/adilio/wiz-sizing`, raw `main`.
- Fast mode is best-effort with fallback; never a hard requirement (§7).
- The EKS/GKE node-count deviation (D1/D2) is acceptable as a documented,
  bias-high approximation rather than a blocker.
- M365 stays PowerShell (`wiz-365.ps1`, opt-in) with its self-cleaning temporary
  app; this is the one scoped exception to the no-new-permissions rule and keeps
  M365 counts identical to the official script (§5, §10).

**Resolved decisions (folded into the body above):**
- **R1 — `wiz-tools` fate.** `wiz-tools` stays; only its **sizing part becomes a
  stub** pointing to `wiz-sizing`. The report viewer and `docs/` pages are
  untouched (§13.2).
- **R2 — AWS Defend.** **Auto-discover** log sources by default (trails → S3
  buckets, VPC flow-log + R53 resolver configs), with explicit `--defend-*-bucket`
  flags to override/supplement and a graceful skip (never a hard fail) when
  nothing is found (§4).
- **R3 — EKS/GKE node counts (D1/D2).** **Accepted** as documented, bias-high
  approximations from configured/desired capacity — the only pure-shell-viable
  path. A future opt-in `--deep-k8s` (shell out to `kubectl` when the user already
  has cluster access) is the escape hatch if exact live counts are ever needed;
  deferred under YAGNI (§9).
- **R4 — AzDO.** **Prompt with a ~30s skip-on-timeout**, plus `--azdo` / `--no-azdo`
  flags for fully non-interactive control (§5).

No open questions remain that block starting Phase 0.

## 16. Execution protocol — run to completion

**For the agent implementing this plan.** The full specification is above; you do
not need to check in between phases. Work **Phase 0 → 5 in order** (§14) and keep
going until the Global Definition of Done (§17) is met.

- **Continue across phases automatically.** When a phase's `Done when` criteria
  pass, start the next phase in the same run. Do not stop to ask "should I
  continue?" — the answer is yes.
- **Decide and note; don't ask.** For reversible, in-scope choices (flag ordering,
  `jq` idioms, which of two equivalent REST endpoints, log wording), pick a sensible
  option, record it in the commit message, and move on. Only stop for: an
  irreversible/destructive action the plan doesn't call for, a genuine contradiction
  in the spec, or a hard blocker only the user can clear (missing credentials, no
  reference env for the live parity gate).
- **Don't end a turn on a promise.** Before ending, check your last message: if it's
  a plan, a question you can answer yourself, a next-steps list, or "I'll next…", do
  that work now instead. End only when §17 is met or you're blocked on something only
  the user can provide.
- **Self-verify every change.** After writing or editing a script, run the no-creds
  gates — `shellcheck`, `tests/contract.bats`, `tests/smoke.bats`, and the script's
  own `--dry-run` — and fix failures before advancing. Ground "phase done" on those
  passing; cite the output, don't assert it.
- **Commit atomically as you go — use `/cp`.** After each self-contained unit lands
  green — a phase's `Done when`, or a coherent sub-unit within a phase whose gates
  pass (the token/refresh helper, the ARG counting path, the Defend path, …) — commit
  and push it with **`/cp`**. **One coherent, working change per commit: never a
  single mega-commit at the end, and never commit a red tree** (gates must pass
  first). This is load-bearing for an unattended run: everything up to the last `/cp`
  is durably saved and pushed, so an interruption costs at most the current unit, not
  the whole session. `/cp` writes a detailed message with no attribution.
- **The live parity diff is the one gate you can't self-clear.** Per §3/§8 it needs a
  real tenant. If none exists, mark that CSP "structurally complete, awaiting live
  parity," keep the Python for that CSP in-tree, and **keep going** — its absence is
  an expected end-state, not a reason to stop the run.
- **Scope discipline (§1 non-goals).** Build what the plan specifies — no extra
  abstractions, no long-tail CSPs, no gold-plating. A bug fix doesn't need
  surrounding cleanup; a one-shot path doesn't need a helper.

**If running on Claude Fable 5** (only applies to Fable; ignore on Opus):

- **Enable the Opus 4.8 refusal fallback before starting.** This is security
  tooling (CloudTrail/VPC/Defend log analysis); Fable's cyber safety classifier can
  false-positive on that. Configure the server-side `fallbacks: [{model:
  "claude-opus-4-8"}]` (or confirm your harness ships the built-in Opus 4.8
  fallback) so a refusal is transparently re-served instead of stalling an
  unattended run. Do not run all-Fable without this.
- **Ignore context-limit worry.** In long sessions Fable may suggest a new session
  or trim its own work when it sees a token countdown. Don't. You have ample
  context — do not stop, summarize, or hand off on account of context limits;
  continue until §17 is met.
- **Run at `high`/`xhigh` effort.** The full task is specified above (that's what
  Fable wants — goal + constraints up front); give it room to think and act across
  tool calls, and expect minutes-long turns as normal, not a stall.

## 17. Global Definition of Done

The implementation is complete when **all** of:

- Every checkbox in §14 (Phases 0–5), including each phase's `Done when`, is ticked.
- `shellcheck` + `tests/contract.bats` + `tests/smoke.bats` are green in CI for all
  four scripts, with no cloud session.
- Each script's `--dry-run` / `--list` / menu runs with no SDK/CLI session and prints
  the intended calls.
- Every §9 deviation is reflected in code **and** documented in `parity/mapping.md`.
- Every §5 opt-in is present and parses: AzDO (prompt + `--azdo`/`--no-azdo`), M365
  (`--m365` hand-off to `wiz-365.ps1`), and `wiz-code.sh`.
- The `wiz-tools` sizing stub is in place (§13) and `wiz-sizing/README.md` is the
  single authoritative doc.
- **Per CSP:** Python retired *iff* its §3 live-parity gate passed; otherwise retained
  in-tree with an "awaiting live parity" note.

The last bullet is the honest stopping point: the whole plan runs to **structural
completion** autonomously. The live parity diff — and the final Python deletion it
gates — may remain open pending a reference env. Reaching that state with the
parity diff outstanding is a *complete* run, not an interrupted one.
