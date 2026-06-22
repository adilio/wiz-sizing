# Wiz Sizing — Single-File-Per-CSP Plan (v3, IMPLEMENTED)

---

# Azure cloud scan: speed + two-phase ARG/SDK (2026-06-22)

> **Status: IMPLEMENTED (2026-06-22).** The `azure-cloud` scan now runs the two-phase design below:
> a fast whole-tenant Azure Resource Graph **preview** (`Preliminary estimate (Azure Resource
> Graph):`) followed by the authoritative SDK **detailed scan**, now parallelized across
> subscriptions via one global `ThreadPoolExecutor(max_workers=…)`. New flags `--quick` (estimate
> only) and `--no-preview` (skip the estimate) ship in both the scanner and `tools/config_azure.py`;
> `--graph` is a deprecated alias for `--quick`. The per-subscription `graph_mode` branches were
> removed from the resource functions, the scanner version is `2.9.0`, `wiz-azure.py` was rebuilt,
> and the README Azure section documents the behavior. The CSV contract (filenames, headers, `totals`
> taxonomy, counting rules) is unchanged. The original spec follows for reference. Defend and DevOps
> are untouched.

## 0. One-paragraph summary

Make the Azure resource-count scan **fast and progressive** without sacrificing accuracy. Today the
scan walks subscriptions **strictly sequentially** (`main()` loops `filtered_subscriptions` one at a
time; within a subscription ~11 resource-type calls run in a thread pool). On a 30–50 subscription
tenant this is the dominant cost, and the operator sees nothing until subscriptions finish. The new
design runs in **two phases**: (1) a fast **Azure Resource Graph (ARG)** preview that counts the
whole tenant in a handful of cross-subscription KQL queries and prints a **preliminary estimate**
within seconds; then (2) an **authoritative detailed pass** that runs the *existing* SDK counting
logic but **parallelized across subscriptions** (not one at a time), correcting the preliminary
numbers in place. ARG is a preview; the SDK pass is the source of truth → **final counts have zero
drift vs today**, and the CSV output format is unchanged.

## 1. Where the code is and how to build it (read first)

- **Scanner to edit:** `sizing-scripts/cloud/azure/resource-count-azure-v2.py` (currently ~1280
  lines; the file analyzed for this spec). It is the source of truth for `azure-cloud` logic.
  - If that file is **absent** (the tree gets torn down between sessions — see the Maintenance note
    below), restore it with: `git checkout 5282e5b~1 -- sizing-scripts`
- **Menu/flag metadata:** `tools/config_azure.py` (the `azure-cloud` mode's `options` list). New
  flags must be added here too so the interactive menu can offer/serialize them.
- **Rebuild after editing the scanner:** `python3 tools/build_wiz.py azure` — this re-embeds the
  edited scanner (gzip+base64) into the committed `wiz-azure.py`. The build round-trips and
  recompiles; `wiz-azure.py` is a generated artifact — **never hand-edit it.**
- **Verify the build is current & tests pass:**
  - `python3 tools/build_wiz.py --check`  (CI gate; must report no staleness)
  - `python3 -m pytest tests/ -q`  (or `python3 -m unittest discover tests`)
- The cloud scan **cannot run locally** (needs an authenticated Azure Cloud Shell). Logic changes
  are verified structurally (tests + `--check`); behavioral verification is a Cloud Shell step (§7).

## 2. Hard constraints — do NOT change these

The §3 CSV contract below still binds. Concretely, in the scanner:

- **Filenames:** `azure-resources.csv`, `azure-resources-log.csv`, `azure-errors-log.txt`.
- **Headers:** summary `['Resource Type', 'Resource Count']`; detailed/log
  `['Resource Type', 'Resource Count', 'Subscription']`.
- **The `totals` dict keys** (the resource taxonomy) must stay the same set — `output_results()`
  iterates them and `tests/test_output_contract.py` greps the header literals.
- **Counting business rules must be preserved exactly in the SDK pass** (these are what guarantee
  zero drift): skip `Vendor=Databricks` VMs and `application=Databricks` / `databricks-environment=true`
  storage accounts; exclude the SQL `master` database; exclude scale-set-member VMs from the Compute
  VM count (counted under Scale Sets); count Linux instances into `Virtual Machine Sensors`; AKS =
  sum of `agentPoolProfiles[].count`; ACR images capped at `--max-image-tags` per repo.
- The legacy file and its embedded blob must stay **byte-identical** (enforced by build + test) —
  so all edits happen in `sizing-scripts/...` and are followed by a rebuild.

## 3. Phase 1 — ARG preview (fast, whole-tenant, best-effort)

A small set of KQL queries with **no `subscriptions=[...]` filter**, so ARG counts across every
subscription the credential can see (current management group / tenant). For the preview we need
**totals only** (the per-subscription detail rows come from the SDK pass), so prefer bare
`summarize count()` — no `by subscriptionId` needed.

Coverage — ARG can faithfully or near-faithfully count more types than today's partial `--graph`
mode implements. Maximize what the preview shows:

| `totals` key | ARG query (type) | Preview fidelity |
|---|---|---|
| Virtual Machines + Non-OS Disks | `microsoft.compute/virtualmachines` (+ `dataDisks` array length), filter out `tags.Vendor=='Databricks'` | High (standalone VMs; VMSS members aren't separate rows in ARG) |
| Container Hosts + K8s Sensors | `microsoft.containerservice/managedclusters` → `mv-expand`/`sum(toint(pool['count']))` | High |
| Serverless Functions | `microsoft.web/sites` + `microsoft.web/staticsites` | Approx (ARG misses *child* functions the SDK enumerates → preview slightly low) |
| PaaS Databases | `microsoft.sql/servers/databases`, exclude names ending `master` | High |
| Serverless Containers | `microsoft.containerinstance/containergroups` + `microsoft.app/containerapps` | High |
| Asset Metadata | `microsoft.hybridcompute/machines` + `microsoft.azurestackhci/clusters` | High |
| Virtual Machines [Scale Sets] | `microsoft.compute/virtualmachinescalesets` → `sum(toint(sku.capacity))` | **Approx only** — capacity ≠ live instance count; SDK corrects |
| Data Buckets (storage containers) | — | **Cannot** — containers are an account sub-resource not in ARG → show `pending` |
| Registry Container Images (ACR) | — | **Cannot** — image/tag counts are registry data-plane → show `pending` |

Print a clearly-labelled block, e.g. `Preliminary estimate (Azure Resource Graph):`, listing the
counts ARG produced and marking the rest `pending detailed scan`. **Store these in a SEPARATE dict
(e.g. `preview_totals`), NOT in `totals`** — Phase 2 must start `totals` at zero so it is fully
authoritative and there is no double-counting. Phase 1 is **best-effort**: wrap it in try/except;
on any failure (missing `azure-mgmt-resourcegraph`, permission error) print a one-line note and
proceed straight to Phase 2.

## 4. Phase 2 — authoritative detailed pass, parallelized across subscriptions

Keep every per-resource function (`get_azure_vms`, `get_azure_vms_scale_sets`,
`get_azure_aks_container_instances`, `get_azure_functions_web_apps`, `get_azure_container_instances`,
`get_azure_container_apps`, `get_azure_storage_containers`, `get_azure_sql_servers`,
`get_azure_arc_machines`, `get_azure_stack_hci_clusters`, `get_azure_acr_images`) **unchanged** —
they already write via the thread-safe `add_total()` (`totals_lock`) and `progress_print()`
(`log_lock`), so they are already safe to run concurrently across subscriptions.

**Concurrency model — flatten to one global pool.** Replace today's "sequential subs, per-sub
`ThreadPoolExecutor`" with a single `ThreadPoolExecutor(max_workers=args.max_workers)` over a flat
list of `(subscription, fn)` work units built for every filtered subscription × every `enabled`
resource type. This:
- parallelizes across subscriptions (the main win), and
- bounds total in-flight REST calls to one number (`--max-workers`) → throttle-friendly. Rely on the
  Azure SDK's built-in exponential retry for 429s (already configured).

`--debug` keeps its meaning: **sequential, no pool, exit on first error** — branch to the existing
serial code path (preview may still run first).

**Preserve the sub-level controls by filtering the subscription list *before* building work units:**
`--start-after-subscription`, `--include/exclude-subscription-regex`, `--max-subscriptions`, and the
`'Access to Azure Active Directory'` skip. For controls that are awkward under full parallelism:
- `--max-run-minutes`: check `max_runtime_reached()` in the submit loop / a wrapper; stop submitting
  and let in-flight finish, then write partial results.
- `--checkpoint-interval`: track **completed subscriptions** (a subscription is "done" when all its
  submitted futures resolve — use a per-sub countdown latch under a lock); write partial output every
  N completed subs.
- SIGINT handler still writes partial results — keep an accumulating `last_subscriptions` list
  (lock-guarded) appended to as each subscription completes.

**Final output is unchanged:** call the existing `output_results()` (it iterates `totals`). Print the
authoritative block labelled e.g. `Final results (detailed scan):` so it visibly supersedes the
preliminary estimate. Optionally show per-type deltas vs `preview_totals` (nice-to-have, not
required).

## 5. Flag surface (simplicity)

Add to the scanner's `argparse` **and** to `tools/config_azure.py` (`azure-cloud` options):

| Flag | Behavior |
|---|---|
| *(default)* | ARG preview → parallel SDK detailed (authoritative) |
| `--quick` | ARG only; skip the detailed pass — fastest, approximate. Writes CSV from `preview_totals`. |
| `--no-preview` | Skip ARG; go straight to the detailed pass (no-ARG-permission environments) |
| `--max-workers N` | Existing flag; now the **global** cap across subs × resource types |
| `--graph` (existing) | **Deprecate → alias for `--quick`.** Keep it parsing so nothing breaks; print a one-line "deprecated, use --quick" note. Remove the old partial per-sub graph branches inside the resource functions (their logic moves into the Phase 1 ARG queries). |

When `--quick`: Phase 1 runs, its `preview_totals` become the result, write the CSV from them, label
output as an estimate, and note which types are `pending`/excluded. When both `--quick` and
`--no-preview` are given, error out (mutually exclusive).

## 6. Implementation checklist (ordered)

1. Restore the scanner if absent (`git checkout 5282e5b~1 -- sizing-scripts`).
2. Add `--quick` / `--no-preview` to the scanner argparse; make `--graph` an alias for `--quick`
   with a deprecation note; validate the mutual-exclusion.
3. Write Phase 1: ARG query helpers (reuse `query_azure_resource_graph` but call it **without** a
   subscription so it spans the tenant), populate `preview_totals`, print the preliminary block,
   all wrapped best-effort.
4. Rewrite `main()` orchestration: subscription discovery/filtering unchanged → Phase 1 (unless
   `--no-preview`) → if `--quick` return after writing preview CSV → else Phase 2.
5. Write Phase 2: flat global `ThreadPoolExecutor` over `(sub, fn)` units; per-sub completion latch
   for checkpoint/SIGINT/`last_subscriptions`; honor `--max-run-minutes`/`--max-subscriptions`/
   `--start-after`/regex via pre-filtering; keep the `--debug` serial path.
6. Remove the now-dead per-sub `graph_mode` branches inside the resource functions (ARG lives in
   Phase 1 now); keep the SDK bodies as the authoritative counters.
7. Update `tools/config_azure.py`: add `--quick`, `--no-preview`; re-label `--graph` as deprecated.
8. Rebuild: `python3 tools/build_wiz.py azure`.
9. Update `README.md` Azure section to describe the two-phase behavior and the new flags.
10. Bump the scanner `version` string.

## 7. Verification

- `python3 tools/build_wiz.py --check` → no staleness.
- `python3 -m pytest tests/ -q` → green (CSV contract + scaffolding unchanged).
- `python3 wiz-azure.py --mode azure-cloud --dry-run` and `--list` work with no SDKs installed.
- Cloud Shell (operator step, not a landing blocker): run a small-scope scan, confirm the
  preliminary block appears within seconds, the detailed pass corrects it, and the final
  `azure-resources.csv` matches a legacy-script run for the same scope.

---

> **Status (2026-06-22): IMPLEMENTED.** The repo ships one self-contained, curl-able script per
> CSP — `wiz-azure.py`, `wiz-aws.py`, `wiz-gcp.py`, `wiz-code.py` (GitHub/GitLab), plus the
> standalone `wiz-365.ps1` for Microsoft 365. Each `wiz-*.py` is the artifact you `curl` and run.
>
> **Architecture: approach (B), the amalgamation build (see §4).** Rather than hand-maintaining
> five near-identical files, the shared scaffolding lives once in `tools/_engine.py`, the per-CSP
> menus/options/profiles in `tools/config_<csp>.py`, and each legacy scanner's verbatim source is
> embedded (gzip+base64). `tools/build_wiz.py` concatenates these into the committed `wiz-*.py`
> files; `tools/build_wiz.py --check` (run in CI) guards against staleness. The **CSV output**
> (§3) is preserved by construction: the scanner source runs in-process, unmodified.
>
> **Maintenance note.** The original `sizing-scripts/` tree has been torn down — it lives in git
> history. The embedded blob inside each `wiz-*.py` is therefore the source of truth for scanner
> logic, and `build_wiz.py` re-reads existing blobs when the legacy tree is absent. To change a
> *scanner*, restore its file from git history into `sizing-scripts/`, edit it, and rebuild (see
> README → "Maintaining the files"). *Scaffolding* changes (engine/config) need no such restore.
>
> The prior v1/v2 launcher design lives in git history (`ef801dc` and earlier).

---

## 1. Goal & guiding principles

A field engineer opens their cloud's CloudShell, pastes **one line**, and is sizing in seconds.
Priorities, in order:

1. **Simplicity.** One self-contained file per cloud. *What's in the repo is exactly what you
   run* — no package to install, no build the user must perform, no hunting through a tree.
2. **Minimal dependencies.** The file's own scaffolding (menu, dependency handling, CSV output)
   is **pure Python standard library**. Cloud SDKs are imported lazily, only for the mode the
   user picks, and installed on demand.
3. **Great UX.** A clean interactive menu, auto-confirmed "recommended sweep" profiles, masked
   token prompts, copy-pasteable command previews, and the existing on-demand dependency install.
4. **One-line bootstrap per cloud** (see §6) — the headline of the README.

## 2. What we are building

Self-contained, **curl-able single files**, one per cloud surface:

| Artifact | Runs in | Bundles (modes) |
|---|---|---|
| `wiz-azure.py` | Azure Cloud Shell | Azure Cloud resource-count · Azure Defend log-volume · Azure DevOps developer-count |
| `wiz-aws.py` | AWS CloudShell | AWS Cloud resource-count · AWS Defend log-volume |
| `wiz-gcp.py` | GCP Cloud Shell | GCP Cloud resource-count · GCP Defend log-volume |
| `wiz-code.py` | anywhere (token) | GitHub · GitLab developer-count |
| `wiz-365.ps1` | Azure Cloud Shell (`pwsh`) | Microsoft 365 sizing (PowerShell; stays standalone) |

Each `.py` is one file you can `curl` and `python3`. Because each CloudShell is already a
single-cloud environment, **no cross-cloud detection or launcher is needed** — you run the file
for the cloud you're in. (Azure DevOps lives in `wiz-azure.py` as part of the Microsoft estate;
GitHub/GitLab are cloud-agnostic, hence `wiz-code.py`.)

## 3. HARD CONSTRAINT — preserve the CSV output exactly

Everything else can change; the output files cannot. Each mode must still write a CSV with the
**same default filename and the same column header(s) and semantics** as today. A consolidated
mode is "done" only when its CSV is byte-equivalent to the legacy script's for the same inputs.

| Mode (legacy script) | Default filename | CSV columns (exact header text) |
|---|---|---|
| AWS cloud `cloud/aws/resource-count-aws-v2.py` | `aws-resources.csv` (+ `aws-resources-log.csv`) | summary: `Resource Type, Resource Count` · detailed: `Resource Type, Resource Count, Account, Region` |
| Azure cloud `cloud/azure/resource-count-azure-v2.py` | `azure-resources.csv` (+ `azure-resources-log.csv`) | summary: `Resource Type, Resource Count` · detailed: `Resource Type, Resource Count, Subscription` |
| GCP cloud `cloud/gcp/resource-count-gcp-v2.py` | `gcp-resources.csv` (+ `gcp-resources-log.csv`) | summary: `Resource Type, Resource Count` · detailed: `Resource Type, Resource Count, Project, Region` |
| AWS Defend `defend/aws/log-volume-estimation-aws.py` | `aws-defend-log-volume.csv` | `Log Source Type, Billable Category, Specific Metric, Bucket/Prefix Details, Estimated 30-Day Uncompressed Volume (GB)` |
| Azure Defend `defend/azure/log-volume-estimation-azure.py` | `azure-defend-log-volume-<YYYYMMDD-HHMMSS>.csv` | `Log Source Type, Billable Category, Specific Metric, Resource/Scope Details, Estimated 30-Day Uncompressed Volume (GB)` |
| GCP Defend `defend/gcp/log-volume-estimation-gcp.py` | `gcp-defend-log-volume-<YYYYMMDD-HHMMSS>.csv` | `Log Source Type, Billable Category, Specific Metric, Resource/Scope Details, Estimated 30-Day Uncompressed Volume (GB)` |
| GitHub `code/github/active-developer-count-github.py` | (current default) | `Organization, Repository, Developers (Last N Days)` |
| GitLab `code/gitlab/active-developer-count-gitlab.py` | (current default) | `Group, Project, Developers (Last N Days)` |
| Azure DevOps `code/azure-devops/active-developer-count-ado.py` | (current default) | `Organization, Project, Repository, Developers (Last N Days), Commits Scanned, Status, Error` |

Notes:
- `(Last N Days)` is dynamic (look-back window) — preserve the exact f-string.
- Sidecar files (`*-resources-log.csv`, `*-errors-log.txt`) and the AWS Defend
  `--defend-detailed` extra rows are part of the contract — keep them.
- "Same data" = same resource taxonomy, counting logic, and volume math. The consolidation
  **lifts** existing scanning logic; it does not re-derive it. Verify by diffing CSVs (§9).
- Preserve the **MIT `LICENSE`**.

## 4. Architecture & the duplication question

The hard part of "single file per CSP" is the shared scaffolding (menu, dependency preflight,
CSV writer, scope-`idfile` handling, profiles). Two ways to keep it DRY were weighed;
**approach (B) was adopted** — the per-cloud option/profile surface plus five embedded scanners
made hand-maintained copies (A) the higher-drift choice in practice:

- **(A) Hand-authored files, small shared scaffolding by convention.** Keep the shared scaffolding
  deliberately *small and stable* and copy it into each `wiz-*.py`. The genuinely per-cloud
  scanning logic is not duplicated. Simplest in the abstract, but with five files it means
  hand-syncing every scaffolding edit across all of them. *Not chosen.*
- **(B) Amalgamation build — ADOPTED.** One copy of the scaffolding in `tools/_engine.py`, the
  per-CSP menus/options/profiles in `tools/config_<csp>.py`, and each legacy scanner embedded
  verbatim (gzip+base64). `tools/build_wiz.py` concatenates these into each root `wiz-*.py`;
  `build_wiz.py --check` guards staleness in CI. DRY source, single-file curl-able output. The
  tradeoff: the committed `wiz-*.py` is a build artifact, and once `sizing-scripts/` is torn down
  the embedded blob is the source of truth for scanner logic (see the §-top Maintenance note).

Repo layout as built under **(B)**:

```
wiz-sizing/
├─ README.md         # THE single authoritative doc (root), replaces the stub
├─ LICENSE           # unchanged (MIT)
├─ PLAN.md           # this file
├─ wiz-azure.py      # self-contained, curl-able  (generated)
├─ wiz-aws.py        # self-contained, curl-able  (generated)
├─ wiz-gcp.py        # self-contained, curl-able  (generated)
├─ wiz-code.py       # self-contained, curl-able  (generated; GitHub/GitLab)
├─ wiz-365.ps1       # Microsoft 365 (PowerShell), standalone
├─ tools/            # build inputs (dev only — not needed to run a wiz-*.py)
│  ├─ _engine.py     # shared scaffolding (menu, deps, idfiles, profiles)
│  ├─ config_*.py    # per-CSP menu/options/profiles
│  └─ build_wiz.py   # assembles config + engine + embedded scanners -> wiz-*.py
└─ tests/
   ├─ test_output_contract.py  # §3 headers/filenames across all files
   └─ test_scaffolding.py      # argv/idfile/profile/CLI assertions
```

The deep `sizing-scripts/{cloud,defend,code,saas}/…` tree is **dissolved**: each script's
scanning logic moves into the matching `wiz-*.py` mode, then the legacy file is deleted (git
history is the snapshot). The nested `sizing-scripts/launcher/README.md` is removed; its content
folds into the root `README.md`.

## 5. Inside each `wiz-<csp>.py`

A single file with this shape (pure stdlib at import time):

1. **Shebang + module docstring** with the one-line bootstrap for that cloud.
2. **Shared scaffolding** (the copied ~300–400 lines):
   - **Menu/CLI** — a clean numbered-prompt menu (robust over CloudShell web terminals) plus
     flags: `--list`, `--dry-run`, `--mode <id>`, `--set`, `--profile`. *(Curses arrow-key UI is
     optional later; numbered prompts are the simple, reliable default.)*
   - **`deps`** — import-probe the SDK(s) for the chosen mode; on miss, show the exact
     `pip3 install …` (honoring `--user` for Azure/GCP Defend) and offer install/skip/back.
   - **`output`** — the ONLY place that knows the §3 filenames + columns; every mode writes
     through it.
   - **token/idfile helpers** — masked `getpass`; scope IDs typed as a list → sibling `.txt`
     file + bare toggle (carried from v2: `regions.txt`, `subscriptions.txt`, `projects.txt`,
     `excluded-folders.txt`, `accounts.txt`).
   - **profiles** — ordered, one-confirmation sequences (see §7).
3. **Per-mode functions** — the lifted scanning logic for that cloud (cloud resource-count,
   Defend log-volume, and for Azure also DevOps). SDKs imported lazily *inside* these.
4. **`main()`** — pick a mode/profile (menu or `--mode`), collect options, preflight, preview +
   confirm, run, report exit code + output path.

Auth per mode is unchanged: cloud/Defend = ambient CloudShell creds (no prompt); Azure DevOps =
masked PAT (`ADO_TOKEN` reused if set; `--org` auto-detected best-effort via `az devops
configure`); GitHub/GitLab = masked token.

## 6. Bootstrap — one line per cloud (the headline)

README leads with these. Pure stdlib core ⇒ nothing to `pip install` to launch:

```bash
# Azure Cloud Shell
curl -fsSL https://downloads.wiz.io/sizing/wiz-azure.py -o wiz-azure.py && python3 wiz-azure.py

# AWS CloudShell
curl -fsSL https://downloads.wiz.io/sizing/wiz-aws.py   -o wiz-aws.py   && python3 wiz-aws.py

# GCP Cloud Shell
curl -fsSL https://downloads.wiz.io/sizing/wiz-gcp.py   -o wiz-gcp.py   && python3 wiz-gcp.py

# GitHub / GitLab (run anywhere; prompts for a token)
curl -fsSL https://downloads.wiz.io/sizing/wiz-code.py  -o wiz-code.py  && python3 wiz-code.py

# Microsoft 365 (Azure Cloud Shell / pwsh)
curl -fsSL https://downloads.wiz.io/sizing/wiz-365.ps1  -o wiz-365.ps1  && pwsh ./wiz-365.ps1
```

(Distribution URL is illustrative; the same files are runnable straight from a `git clone`.)

## 7. UX — profiles & menu shape

Each file opens on its cloud's menu, profiles first, then individual modes. Profiles run as an
ordered sequence under **one confirmation**. The **Azure** menu is the model and ships two:

```
wiz-azure.py
  1) ★ Recommended full sweep   — Azure Cloud --all + Defend --all-subscriptions (tenant-wide),
                                   then OFFER Azure DevOps + Microsoft 365 (interactive y/N)
  2) ★ All Microsoft estate     — Azure Cloud + Defend → Azure DevOps → Microsoft 365,
                                   as committed steps in the sequence (not optional)
  3) Azure — Cloud resource count
  4) Azure — Defend log volume
  5) Azure DevOps — developer count
  q) Quit
```

- **AWS / GCP** ship one profile each: `★ Recommended full sweep` (AWS org `--all` + Defend;
  GCP `--all` + Defend `--org-aggregate`), then their individual modes. The profile mechanism is
  general, so more can be added per file.
- **Scope-identity auto-detect** (best-effort, never blocks): GCP org id (`gcloud`) for
  org-aggregate; Azure tenant (`az`) surfaced for confirmation; ADO org (`az devops configure`).
- **M365 from `wiz-azure.py`:** since M365 is PowerShell/device-code, the Azure profiles drive it
  by, when `pwsh` is present, fetching + running `wiz-365.ps1`; otherwise printing the M365
  one-liner to run in a `pwsh`-capable shell. M365 itself stays the standalone `wiz-365.ps1`.

## 8. Migration phases (Azure first; each independently verifiable)

> **All phases below are complete** (see §-top status). The cloud-side step 9.4 matrix remains an
> operator release step — it needs live CloudShells and is not a code-landing blocker.

1. **`wiz-azure.py` — first complete vertical slice.** Author the shared scaffolding (§5.2) and
   lift the three Azure modes (cloud resource-count, Defend log-volume, Azure DevOps) into it.
   Implement both Azure profiles (§7), including the M365 hand-off. Prove **CSV-equivalence**
   for each mode (§9). This file is the template the others are cut from.
2. **`wiz-365.ps1`.** Move `saas/microsoft-365/365_Sizing_Script.ps1` to the root as the
   standalone M365 file; wire the `wiz-azure.py` hand-off to it.
3. **`wiz-aws.py`.** Lift AWS cloud + AWS Defend, reusing the scaffolding from step 1; one
   `★ Recommended full sweep` profile; CSV-equivalence.
4. **`wiz-gcp.py`.** Lift GCP cloud + GCP Defend (incl. org-aggregate detection); CSV-equivalence.
5. **`wiz-code.py`.** Lift GitHub + GitLab developer-count; masked token prompts; CSV-equivalence.
6. **Docs + teardown.** Rewrite root `README.md` as the single authoritative doc (per-cloud
   one-liners from §6, menu/profile explanation, CSV outputs, credentials). Delete the entire
   `sizing-scripts/` tree (all logic now lives in the `wiz-*` files) and the nested README.

Rationale: build one file end-to-end (Azure) so the scaffolding and the CSV-equivalence harness
are proven before replicating; then each subsequent cloud is a small, mechanical lift.

## 9. Testing & the CSV-equivalence gate (concrete)

The Azure/AWS/GCP scans **cannot run locally** (they need live, authenticated CloudShell), so
"diff against the legacy script" is not generally available off-box. The gate is therefore
defined structurally, in four layers — a mode is **done** only when 1–3 pass and 4 is scheduled:

1. **Single writer reproduces the legacy `writerow` calls.** Every CSV write in every mode goes
   through the shared `output` writer (§5.2). For each mode, the writer's header tuple and each
   row tuple must be **identical** to the legacy script's `csv_writer.writerow([...])` calls —
   same column order, same f-string formatting (e.g. GCP/Azure Defend `f"{volume_gb:.2f}"`, the
   `(Last {N} Days)` header). Cite the legacy source line (see Appendix A) next to each writer
   path so a reviewer can compare side by side.
2. **Unit tests on the writer** (`tests/test_output_contract.py`): assert exact default
   **filenames** and **header rows** for all nine modes from in-memory fixture rows (no creds
   needed). This is the enforceable form of §3.
3. **Scaffolding unit tests** (per file): menu/argv building, `idfile` → `.txt` materialization,
   `--mode`/`--set`/`--dry-run`/`--profile`, token reuse + scope-detection wiring (mock the
   `gcloud`/`az` calls). Port the relevant assertions from today's `test_wiz_sizing.py` (14
   tests). Where a mode *can* run off-box (GitHub/GitLab with a real token), add a genuine
   new-vs-legacy CSV diff.
4. **In-shell manual matrix (operator-run, recorded in README):** in each real CloudShell — curl
   the file, run a recommended sweep at small scope, byte-diff the produced CSV against the
   legacy script's CSV for the same scope, confirm on-demand dependency install works. This is
   the only place full new-vs-legacy diffing happens for the cloud modes; it is a release step,
   not a blocker for landing the code.

## 10. Risks & mitigations

- **Behavioral drift while lifting cloud logic** → the CSV-equivalence gate (§9); lift, don't
  rewrite; git history (`ef801dc`) is the legacy reference.
- **Scaffolding duplication across files** → keep it small/stable (§4A); if it bites, switch to
  the amalgamation build (§4B).
- **M365 language boundary** → kept standalone (`wiz-365.ps1`); `wiz-azure.py` only hands off to
  it, gated on `shutil.which("pwsh")`.
- **CloudShell Python versions** → broadly-compatible stdlib only; avoid 3.12-only APIs.

## 11. Out of scope / deferred

- Deferred providers (OCI, Alibaba, Linode, Snowflake, vSphere, HCP Terraform) — future `wiz-*`
  files once the template lands.
- Curses arrow-key UI inside the single files — optional polish; numbered menu ships first (§5).
- Amalgamation build (§4B), PyPI packaging, console-scripts — only if needed later.
- Deep de-duplication of cloud API code beyond the shared scaffolding — follow-up after
  CSV-equivalence is locked.

---

## Appendix A — Lift-source map (copy from here; do not reinvent)

All paths relative to repo root. **Read the source before lifting**; the v1 manifest had
flag-modeling bugs, so re-verify each flag against the script's actual `argparse` block.

**Shared scaffolding** ← `sizing-scripts/launcher/wiz-sizing.py` (lift these functions/classes):
- Menu + flow: `PromptUI`, `run_session`, `main`, arg parsing (`--list/--dry-run/--set`).
- Command building: `build_command`, `default_value`, `quote_command`, `_parse_set_values`.
- Scope idfiles: `parse_id_list`, `idfile_plan`, `materialize_idfiles` (+ the `idfile` option
  kind). Files: `accounts.txt`, `regions.txt`, `subscriptions.txt`, `projects.txt`,
  `excluded-folders.txt` — opened from **cwd** by the scripts, so write them into the run cwd.
- Dependency preflight: `probe_ok`, `preflight`.
- Tokens: `collect_tokens` (masked, env reuse, `detect` hook).
- Scope detection: `DETECTORS` = `detect_gcp_org` (`gcloud organizations list`),
  `detect_azure_tenant` (`az account show`), `detect_ado_org` (`az devops configure`).
  **Drop `detect_csp`** — each file is single-cloud.
- Profiles: `PROFILES`, `PROFILE_OPTINS`, `run_profile`, `_resolve_profile_steps`,
  `_offer_profile_optins`, `_run_leaf_inline`. (Generalize `PROFILES` to a *list* per file.)
- Tests: `sizing-scripts/launcher/test_wiz_sizing.py` → split into per-file tests.

**Per-mode scanning logic** ← the legacy scripts (lift the scan + the `csv_writer.writerow`
sites named for §9 layer 1):

| Mode id | Legacy source | Output writer site (legacy line) |
|---|---|---|
| `azure-cloud`  | `cloud/azure/resource-count-azure-v2.py` | header ~1134 / detailed ~1140 |
| `azure-defend` | `defend/azure/log-volume-estimation-azure.py` | header ~633 |
| `azure-devops` | `code/azure-devops/active-developer-count-ado.py` | header ~718 |
| `aws-cloud`    | `cloud/aws/resource-count-aws-v2.py` | header ~1357 / detailed ~1363 |
| `aws-defend`   | `defend/aws/log-volume-estimation-aws.py` | header ~834 |
| `gcp-cloud`    | `cloud/gcp/resource-count-gcp-v2.py` | header ~1092 / detailed ~1098 |
| `gcp-defend`   | `defend/gcp/log-volume-estimation-gcp.py` | header ~617 |
| `github`       | `code/github/active-developer-count-github.py` | header ~468 |
| `gitlab`       | `code/gitlab/active-developer-count-gitlab.py` | header ~497 |
| `m365`         | `saas/microsoft-365/365_Sizing_Script.ps1` | (PowerShell, moved verbatim) |

## Appendix B — Input/flag surface per mode (preserve; re-verify against argparse)

`idfile` = list input → sibling `.txt` + bare toggle. Cloud/Defend = ambient auth.

- **azure-cloud** — Common: `--all` (all subs in mgmt group), `--data`, `--images`,
  `--subscriptions` (idfile→`subscriptions.txt`), `--output-dir`. Advanced: `--graph`, `--id`
  (single sub), `--gov`, `--china`, `--germany`, `--include-subscription-regex`,
  `--exclude-subscription-regex`, `--start-after-subscription`, `--max-subscriptions`,
  `--max-workers`, `--max-run-minutes`, `--max-image-tags`, `--request-timeout`,
  `--checkpoint-interval`, `--verbose`, `--debug`.
- **azure-defend** — Common: `--subscription-id` (str) | `--all-subscriptions` (toggle),
  `--log-analysis-days` (int), `--output-filename`. Advanced: `--errors-log-filename`,
  `--verbose`, `--debug`.
- **azure-devops** — Required: `--org`/`--organization` (auto-detect `ado_org`), `--token`
  (env `ADO_TOKEN`). Common: `--proj`, `--repo`, `--days`, `--output-dir`. Advanced:
  `--mask-emails`, `--include-disabled`, `--include-empty-repositories`, `--project-page-size`,
  `--commit-page-size`, `--max-repositories`, `--max-commits-per-repo`, `--max-retries`,
  `--retry-delay`, `--max-run-minutes`, `--checkpoint-interval`, `--progress-interval`,
  `--fail-fast`, `--verbose`.
- **aws-cloud** — Common: `--all` (all accounts in org), `--data`, `--images`, `--regions`
  (idfile→`regions.txt`), `--output-dir`. Advanced: `--accounts` (idfile→`accounts.txt`),
  `--id` (single account), `--role-name`, `--gov`, `--china`, `--include-account-regex`,
  `--exclude-account-regex`, `--start-after-account`, `--max-accounts`, `--max-workers`,
  `--max-run-minutes`, `--max-image-tags`, `--max-lambda-versions`, `--checkpoint-interval`,
  `--verbose`, `--debug`.
- **aws-defend** — Common: `--defend-detailed`. **No `--output-dir`** (writes
  `aws-defend-log-volume.csv` to cwd). Advanced: `--defend-cloudtrail-logs-bucket`,
  `--defend-cloudtrail-logs-bucket-prefix`, `--defend-cloudtrail-logs-bucket-days`,
  `--defend-cloudtrail-logs-bucket-sample-size`, `--defend-cloudtrail-logs-compression-factor`,
  `--defend-vpc-flow-logs-bucket`, `--defend-vpc-flow-logs-compression-factor`,
  `--defend-route53-resolver-logs-bucket`, `--defend-route53-resolver-logs-compression-factor`,
  `--max-workers`, `--verbose`, `--debug`.
- **gcp-cloud** — Common: `--all`, `--data`, `--images`, `--projects` (idfile→`projects.txt`),
  `--output-dir`. Advanced: `--id` (single project), `--exclude` (idfile→`excluded-folders.txt`),
  `--include-project-regex`, `--exclude-project-regex`, `--start-after-project`,
  `--max-projects`, `--max-pages-per-request`, `--max-workers`, `--max-run-minutes`,
  `--max-image-tags`, `--request-timeout`, `--checkpoint-interval`, `--inventory-instructions`,
  `--verbose`, `--debug`.
- **gcp-defend** — Common: `--project-id` (str) | `--organization-id` + `--org-aggregate`
  (toggle; org id from `gcp_org` detect), `--log-analysis-days` (int), `--output-filename`.
  Advanced: `--use-sink-metrics`, `--sink-name`, `--no-exclusion-adjustment`, `--workers`,
  `--errors-log-filename`, `--verbose`, `--debug`.
- **github** — Required: `--token` (env `GITHUB_TOKEN`, launcher convention). Common: `--org`,
  `--repo`, `--url` (Enterprise), `--output-dir`. Advanced: `--max-workers`,
  `--progress-interval`, `--decrypt`, `--verbose`, `--debug`.
- **gitlab** — Required: `--token` (env `GITLAB_TOKEN`, launcher convention). Common: `--group`,
  `--project`, `--url`, `--output-dir`. Advanced: `--max-workers`, `--progress-interval`,
  `--decrypt`, `--verbose`, `--debug`.
- **m365** (`-` PowerShell flags) — Common: `-SummaryOnly`, `-MaxSites`, `-ProgressInterval`.
  Advanced: `-AppName`, `-KeepTemporaryApp`, `-MaxRetries`, `-MaxRetryDelaySeconds`,
  `-PermissionPropagationSeconds`, `-UseDeviceCode`.

## Appendix C — Mode ids, profiles, and CLI contract

Each `wiz-*.py` accepts the same flags: `--list`, `--mode <id>`, `--profile <id>`, `--dry-run`,
`--set=--flag=value` (repeatable; attached `=` form), and the per-mode flags from Appendix B.

- `wiz-azure.py` modes: `azure-cloud`, `azure-defend`, `azure-devops`.
  Profiles: `azure-recommended` (azure-cloud `--all` + azure-defend `--all-subscriptions`; offer
  azure-devops + m365), `azure-microsoft` (azure-cloud + azure-defend → azure-devops → m365 as
  committed steps).
- `wiz-aws.py` modes: `aws-cloud`, `aws-defend`. Profile: `aws-recommended` (aws-cloud `--all`
  `--data` `--images` → aws-defend).
- `wiz-gcp.py` modes: `gcp-cloud`, `gcp-defend`. Profile: `gcp-recommended` (gcp-cloud `--all`
  `--data` `--images` → gcp-defend `--org-aggregate` with detected `--organization-id`).
- `wiz-code.py` modes: `github`, `gitlab` (no profile).

## Appendix D — Per-file Definition of Done

A `wiz-<x>.py` is complete when:
1. Every mode listed for it runs via menu and `--mode`, and `--list`/`--dry-run`/`--profile`
   work with **no SDKs installed** (lazy imports).
2. CSV writer paths match the legacy `writerow` calls (§9.1) and `tests/` assert the §3
   filename + headers for each mode (§9.2).
3. Scaffolding unit tests pass (§9.3); all Appendix-B flags are present and serialize correctly
   (idfile → bare toggle + `.txt`; single-target → `--id`; `aws-defend` has **no** `--output-dir`).
4. Dependency preflight shows the correct `pip3 install …` (with `--user` for Azure/GCP Defend)
   and re-probes after install.
5. Token modes prompt masked, reuse the right env var, and auto-detect where specified.
6. The legacy script(s) for those modes are deleted and no path references remain.
7. The in-shell matrix step (§9.4) is documented for an operator to run.
