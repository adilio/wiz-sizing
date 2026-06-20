# Wiz Sizing TUI Launcher — v2 Plan (active)

> **Status (2026-06-20): v2 COMPLETE — shipped on `main` (`9b0c684`).** All six prioritized
> items in §C are built in `sizing-scripts/launcher/wiz-sizing.py`, verified, and committed:
> the B1 scope-flag bug is fixed (`idfile` kind writes `.txt` + bare toggle), an additional
> B1-class bug was caught and fixed (AWS Defend has no `--output-dir`), ADO now uses
> `ADO_TOKEN` with `--org` auto-detect, per-CSP "recommended full sweep" profiles run under one
> confirmation with M365/AzDO opt-ins, scope-identity detection (GCP org / Azure tenant / ADO
> org) is best-effort, the README has a `curl | python3` bootstrap, and `test_wiz_sizing.py`
> (14 tests, all passing) asserts non-default argv. See [§E](#e-v2-completion-record) for the
> completion record. **Sections 1–10 below are DEPRECATED** — kept for history only; do not
> implement against them. See [§D](#d-deprecated-v1-spec-below).

## A. Goal (restated)

Exceptional CloudShell UX with **absolutely minimal dependencies** (pure stdlib, no
`pip install` for the launcher itself), runnable in **AWS / Azure / GCP CloudShell**, that
**auto-detects as much as possible** and offers **logical groupings with sane, inclusive
defaults**. The headline default per CSP should be a one-confirmation "recommended full sweep"
— e.g. Azure default = scan **all** Azure Cloud resources **and** Azure Defend ingestion across
the tenant, with **opt-in** Microsoft 365 and Azure DevOps, auto-detecting tenant level, M365
tenant, and the Azure DevOps root org.

## B. Evaluation findings (what's wrong with v1 today)

### B1. Correctness bug — scope flags don't match the scripts (highest priority)

The v1 manifest models `--regions`, `--accounts`, `--subscriptions`, `--projects`, and
`--exclude` as `kind: "csv"` taking a comma-separated value. In the **actual scripts** all five
are `action="store_true"` toggles that read IDs from a **sibling `.txt` file**:

| Manifest says (v1) | Script actually does | File read |
|---|---|---|
| `--regions us-east-1,us-west-2` | `--regions` (no value) | `regions.txt` |
| `--accounts 111,222` | `--accounts` (no value) | `accounts.txt` |
| `--subscriptions <ids>` | `--subscriptions` (no value) | `subscriptions.txt` |
| `--projects <ids>` | `--projects` (no value) | `projects.txt` |
| `--exclude <ids>` | `--exclude` (no value) | `excluded-folders.txt` |

Consequence: if a user types a list into the menu, `build_command` emits e.g.
`python3 … --regions us-east-1,us-west-2`, which argparse rejects (`--regions` accepts no
argument). **The most common scoping action through the menu is broken.** It slipped through
because `--dry-run --leaf` only serializes *default (empty)* values, so the csv flags are never
exercised. The correct single-target flag in every cloud script is **`--id`** (currently buried
as advanced `str`). Fix: write the `.txt` file from the launcher when a list is entered and pass
the bare toggle; route single-target to `--id`.

### B2. Token env-var mismatches

- **ADO**: manifest reuses `AZURE_DEVOPS_EXT_PAT`, but the script's own env var is **`ADO_TOKEN`**
  (`active-developer-count-ado.py:59`). The reuse prompt never fires for the variable the script
  honors. Also `--org` is `required` with **no env fallback**.
- `GITHUB_TOKEN` / `GITLAB_TOKEN` have **no script-side default** — they are launcher-only
  conventions; document them as such rather than implying the scripts read them.

### B3. Structural gap — no "recommended profile" concept

The session driver runs exactly **one leaf**. The inclusive Azure example (Cloud `--all` +
Defend `--all-subscriptions`, opt-in M365 + AzDO) cannot be expressed. Also every toggle
defaults **off**, so the "easy path" today scans nothing org-wide.

### B4. Scope auto-detection is provider-only

`detect_csp()` identifies *which cloud* but never the *scope identity* needed for inclusive
defaults:
- GCP Defend `--org-aggregate` requires `--organization-id` — nothing derives it.
- Azure "all" is management-group-wide; tenant is neither surfaced nor confirmed.
- ADO has no root-org detection; `--org` is required with no fallback.
These are exactly the "auto-detect Azure tenant level, M365 tenant, ADO root org" pieces.

### B5. No one-line bootstrap

README says "get the repo into your CloudShell" and leaves it to the user. Since the launcher is
a single self-contained file, a `curl …/wiz-sizing.py -o wiz-sizing.py && python3 wiz-sizing.py`
bootstrap is achievable and is the biggest perceived-UX win.

### B6. Test blind spot

`--dry-run --leaf` only builds default commands, so a regression like B1 passes. Tests must
cover representative **non-default** option combinations.

## C. v2 plan (prioritized)

1. [x] **[correctness] Fix scope-flag handling.** Replaced `csv` semantics for `--regions`,
   `--accounts`, `--subscriptions`, `--projects`, `--exclude` with: (a) `--id` for a single
   target, (b) a new data-driven `idfile` kind — a list input writes the script's expected
   `.txt` file into the run cwd (verified the scripts `open()` these from cwd, not output-dir)
   and passes the bare toggle. Also corrected the wrong `--all` help text (it is org/mgmt-group
   /project-wide, not "all resource types").
2. [x] **[correctness] Fix ADO env var** to `ADO_TOKEN`; added an `--org` env/auto-detect
   fallback (`detect: ado_org`); README now flags GitHub/GitLab token vars as launcher
   conventions (the scripts don't read them).
3. [x] **[UX] Per-CSP "Recommended full sweep" profile.** `PROFILES` + `PROFILE_OPTINS` drive
   an ordered sequence under one confirmation, then offer the opt-ins (M365, AzDO). Inclusive
   defaults: AWS org `--all`, Azure mgmt-group `--all` + Defend `--all-subscriptions`, GCP
   `--all` + Defend `--org-aggregate`. Wired into both the curses and prompt menus as the top
   per-CSP item.
4. [x] **[auto-detect] Scope identity detection** (`DETECTORS`): GCP org id (`gcloud`), Azure
   tenant (`az`), ADO org (env then `az devops configure`). Best-effort with fast timeout,
   confirmation, and a prompt fallback; never blocks if detection fails.
5. [x] **[UX] `curl | python3` bootstrap one-liner** added to the README per CloudShell.
6. [x] **[tests] Extended dry-run/testability**: `--set=--flag=value` injects non-defaults into
   `--leaf`, `--profile` dumps a profile's steps, and `test_wiz_sizing.py` (13 tests) asserts
   argv for non-default combinations incl. the B1 regression.

**Additional finding fixed during implementation (B1-class):** the v1 manifest listed
`--output-dir` for the **AWS Defend** leaf, but that script has *no* output flag — it writes
`aws-defend-log-volume.csv` into the working directory. Passing `--output-dir` would make
argparse reject the command (and it was in the recommended profile). Removed from the manifest;
guarded by a test. (Azure/GCP Defend correctly use `--output-filename`, a bare filename written
to cwd.)

Constraints unchanged from v1: pure stdlib, never import a cloud SDK, never edit the target
scripts, manifest-driven menu.

---

## E. v2 completion record

**Shipped on `main` in `9b0c684`** ("Launcher v2: fix scope flags, add recommended sweep
profiles"). Files touched:

| File | What changed |
|---|---|
| `sizing-scripts/launcher/wiz-sizing.py` | `idfile` kind + `materialize_idfiles`/`idfile_plan`; `PROFILES`/`PROFILE_OPTINS` + `run_profile`; `DETECTORS` (`detect_gcp_org`/`detect_azure_tenant`/`detect_ado_org`); ADO `ADO_TOKEN` + `--org` detect; corrected `--all` help; removed bad AWS-Defend `--output-dir`; `--set`/`--profile` CLI |
| `sizing-scripts/launcher/test_wiz_sizing.py` | **New.** 14 unit tests (scope flags, idfile materialization, ADO env, profiles, output-flag regression, `--set` parser) |
| `sizing-scripts/launcher/README.md` | Bootstrap one-liner, profile + scoping + detection docs, credential conventions, `--set`/`--profile` flags, test instructions |

### How to verify (runnable anywhere, no CloudShell)

```bash
cd sizing-scripts/launcher
python3 test_wiz_sizing.py          # 14 tests
python3 wiz-sizing.py --list        # manifest leaves
python3 wiz-sizing.py --dry-run --profile azure   # preview a sweep's commands
python3 wiz-sizing.py --dry-run --leaf aws-cloud --set=--all=on --set=--regions=us-east-1,eu-west-1
```

### Still deferred (unchanged from v1, not regressed)

- **Manifest-only additions** for the out-of-scope providers (OCI, Alibaba, Linode, Snowflake,
  vSphere, HCP Terraform) — a future data-only PR; no UI work needed.
- **In-shell manual matrix** (§8 below): detection, live preflight/install, and a real
  small-scope scan must still be exercised by an operator inside each live CloudShell, since
  ambient auth and env detection can't be reproduced from outside.

---

## D. DEPRECATED v1 spec (below)

> **⚠️ DEPRECATED — historical only.** The sections below describe the v1 design as shipped in
> `27324c2`. They contain the known-wrong `csv` scope-flag modeling (see §B1) and predate the
> v2 goals. Retained for context; supersede with §A–§C above.

# Wiz Sizing TUI Launcher — Full Design & Implementation Spec

> **Status (2026-06-20): v1 COMPLETE.** All in-scope work is built, committed to `main`
> (`27324c2`), and verified via `--dry-run`/`--list`. The launcher, three shims, and README
> live under `sizing-scripts/launcher/`. Only the explicitly-deferred out-of-scope scripts
> remain (a future manifest-only PR). Checklist boxes below reflect this.

## 1. Context & goal

The repo has 14 sizing scripts (now 17 with the Defend additions) that are invoked as raw CLI commands with long, script-specific flag sets. The goal is an **interactive, menu-driven launcher** that runs **inside each cloud's CloudShell**, has **zero install footprint of its own**, batches scripts sensibly (chosen: by CSP with auto-detect), and builds/executes the right command for the user.

## 2. Decisions made in this thread (with rationale)

| # | Decision | Why |
|---|---|---|
| D1 | **Grouping = auto-detect the CloudShell you're in, with per-CSP entry points as the explicit fallback** | Your choice. The only cross-cloud reality is that each CloudShell is a *separate* environment, so a single launcher can't span clouds at runtime — it detects where it's running and lands you on that provider; `--csp` and `.sh` shims cover the explicit path. |
| D2 | **Tech = pure-stdlib Python with a `curses` full-screen menu, degrading to numbered `input()` prompts** | You delegated this with "best UX but minimal deps." `curses` ships with CPython on every Linux CloudShell → arrow-key UX at **zero `pip install`**. Third-party TUIs (Textual/Rich/questionary) were rejected because they'd require installs. Prompt fallback guarantees it still works on a non-TTY/dumb terminal. |
| D3 | **v1 scope = AWS, Azure, GCP (both Cloud resource-count *and* Defend log-volume) + Microsoft 365 + GitHub, GitLab, Azure DevOps** | Your stated scope. Defend was confirmed present (commit `5c7cb50`) for exactly these three clouds. |
| D4 | **Launcher wraps existing scripts; it never imports a cloud SDK and never edits the targets** | Keeps each script's `wiz-copy`/`modified` status and `SCRIPT_STATUS.md` accurate; isolates all SDK/dependency concerns inside the scripts where they already live. |
| D5 | **Menu is generated from a declarative manifest, not hand-coded per script** | The flag surface is highly regular; a data-driven menu makes adding the deferred scripts (OCI/Alibaba/Linode/Snowflake/vSphere/HCP) a data edit, not new UI code. |
| D6 | **Two-axis menu within each CSP: "Cloud resource count" vs "Defend log volume"** | Discovering the Defend scripts revealed a clean per-CSP sizing-type split; both run in the same CloudShell with the same ambient auth. |
| D7 | **Single self-contained `wiz-sizing.py` (manifest embedded), plus optional thin per-CSP shims** | The robust CloudShell workflow is "get one file, run it." A single file with no sibling-import requirement is the most portable; shims are convenience only. |
| D8 | **Rebase the planning branch onto current `main` (`a9e3dc7`) before building** | The branch `claude/sizing-scripts-tui-plan-m83xs3` was cut before the Defend + M365 + ADO commits landed; the launcher must reference the real `defend/` paths. |
| D9 | **Defend ingestion IS in scope (3 real scripts), correcting my earlier wrong assumption** | Verified by fetching `main`; `sizing-scripts/defend/{aws,azure,gcp}/log-volume-estimation-*.py` exist. |

**Out of scope for v1 (deferred, not rejected):** OCI, Alibaba, Linode, Snowflake, vSphere (cloud) and HCP Terraform (code). They slot in later as pure manifest additions. No new sizing scripts are written. No changes to the underlying scripts.

## 3. The in-scope scripts and their real interfaces

All cloud + Defend scripts use **ambient auth** (no token flags — they rely on the preauthenticated CloudShell). All follow the same pattern: stdlib imports, one `try/except ImportError` that prints a `pip3 install …` hint. Code scripts require a **`--token`**.

| Menu path | Script (relative to `sizing-scripts/`) | Runner | Auth | Probe import(s) | pip install hint |
|---|---|---|---|---|---|
| AWS › Cloud resource count | `cloud/aws/resource-count-aws-v2.py` | python3 | ambient | `boto3` | `boto3 botocore eks_token kubernetes urllib3` |
| AWS › Defend log volume | `defend/aws/log-volume-estimation-aws.py` | python3 | ambient | `boto3` | `boto3 botocore` |
| Azure › Cloud resource count | `cloud/azure/resource-count-azure-v2.py` | python3 | ambient | `azure.mgmt.resourcegraph` | (multi-line azure-mgmt set) |
| Azure › Defend log volume | `defend/azure/log-volume-estimation-azure.py` | python3 | ambient | `requests` (+ azure-identity) | `--user azure-identity azure-mgmt-resource azure-mgmt-subscription azure-monitor-query requests` |
| GCP › Cloud resource count | `cloud/gcp/resource-count-gcp-v2.py` | python3 | ambient | `googleapiclient.discovery`, `google.auth` | `google-api-python-client` |
| GCP › Defend log volume | `defend/gcp/log-volume-estimation-gcp.py` | python3 | ambient | `google.auth` | `--user google-cloud-monitoring google-api-core google-auth google-cloud-resource-manager google-cloud-logging` |
| Microsoft 365 | `saas/microsoft-365/365_Sizing_Script.ps1` | pwsh | device-code | `pwsh` on PATH | n/a (PowerShell modules handled by script) |
| Code › GitHub | `code/github/active-developer-count-github.py` | python3 | token | `github` | `PyGithub` |
| Code › GitLab | `code/gitlab/active-developer-count-gitlab.py` | python3 | token | `gitlab` | `python-gitlab` |
| Code › Azure DevOps | `code/azure-devops/active-developer-count-ado.py` | python3 | token | `azure.devops` | `azure-devops` |

### Per-script options to surface (verified from each script's argparse / param block)

The launcher splits options into **Common** (shown by default) and **Advanced** (behind an "Advanced options…" item). Below, the exact flags:

- **AWS resource-count** — Common: `--all`, `--data`, `--images`, `--regions` (csv), `--output-dir`. Advanced: `--accounts`, `--id`, `--role-name`, `--gov`, `--china`, `--include-account-regex`, `--exclude-account-regex`, `--start-after-account`, `--max-accounts`, `--max-workers`, `--max-run-minutes`, `--max-image-tags`, `--max-lambda-versions`, `--checkpoint-interval`, `--verbose`, `--debug`.
- **AWS Defend** — Common: `--defend-detailed` (toggle), `--output` via working dir. Advanced: `--defend-cloudtrail-logs-bucket`, `--defend-cloudtrail-logs-bucket-prefix`, `--defend-cloudtrail-logs-bucket-days`, `--defend-cloudtrail-logs-bucket-sample-size`, `--defend-cloudtrail-logs-compression-factor`, `--defend-vpc-flow-logs-bucket`, `--defend-vpc-flow-logs-compression-factor`, `--defend-route53-resolver-logs-bucket`, `--defend-route53-resolver-logs-compression-factor`, `--max-workers`, `--verbose`, `--debug`.
- **Azure resource-count** — Common: `--all`, `--data`, `--images`, `--subscriptions` (csv), `--output-dir`. Advanced: `--graph`, `--id`, `--gov`, `--china`, `--germany`, `--include-subscription-regex`, `--exclude-subscription-regex`, `--start-after-subscription`, `--max-subscriptions`, `--max-workers`, `--max-run-minutes`, `--max-image-tags`, `--request-timeout`, `--checkpoint-interval`, `--verbose`, `--debug`.
- **Azure Defend** — Common: `--subscription-id` (str) or `--all-subscriptions` (toggle), `--log-analysis-days` (int), `--output-filename`. Advanced: `--errors-log-filename`, `--verbose`, `--debug`.
- **GCP resource-count** — Common: `--all`, `--data`, `--images`, `--projects` (csv), `--output-dir`. Advanced: `--id`, `--exclude`, `--include-project-regex`, `--exclude-project-regex`, `--start-after-project`, `--max-projects`, `--max-pages-per-request`, `--max-workers`, `--max-run-minutes`, `--max-image-tags`, `--request-timeout`, `--checkpoint-interval`, `--inventory-instructions`, `--verbose`, `--debug`.
- **GCP Defend** — Common: `--project-id` (str) or `--organization-id` + `--org-aggregate` (toggle), `--log-analysis-days` (int), `--output-filename`. Advanced: `--use-sink-metrics`, `--sink-name`, `--no-exclusion-adjustment`, `--workers`, `--errors-log-filename`, `--verbose`, `--debug`.
- **M365** — Common: `-SummaryOnly` (switch), `-MaxSites` (int), `-ProgressInterval` (int). Advanced: `-AppName`, `-KeepTemporaryApp`, `-MaxRetries`, `-MaxRetryDelaySeconds`, `-PermissionPropagationSeconds`, `-UseDeviceCode`.
- **GitHub** — Required: `--token` (prompted). Common: `--org`, `--repo`, `--url` (Enterprise), `--output-dir`. Advanced: `--max-workers`, `--progress-interval`, `--decrypt`, `--verbose`, `--debug`.
- **GitLab** — Required: `--token`. Common: `--group`, `--project`, `--url`, `--output-dir`. Advanced: `--max-workers`, `--progress-interval`, `--decrypt`, `--verbose`, `--debug`.
- **Azure DevOps** — Required: `--token`, `--org`. Common: `--proj`, `--repo`, `--days`, `--output-dir`. Advanced: `--mask-emails`, `--include-disabled`, `--include-empty-repositories`, `--project-page-size`, `--commit-page-size`, `--max-repositories`, `--max-commits-per-repo`, `--max-retries`, `--retry-delay`, `--max-run-minutes`, `--checkpoint-interval`, `--progress-interval`, `--fail-fast`, `--verbose`.

## 4. File layout to create — ✅ all created

```
sizing-scripts/
└─ launcher/
   ├─ wiz-sizing.py     # ✅ single self-contained stdlib launcher (manifest embedded)
   ├─ launch-aws.sh     # ✅ exec python3 "$(dirname "$0")/wiz-sizing.py" --csp aws  "$@"
   ├─ launch-azure.sh   # ✅ ... --csp azure
   ├─ launch-gcp.sh     # ✅ ... --csp gcp
   └─ README.md         # ✅ one-liners + usage per CloudShell
```

The shims are 2 lines each. `wiz-sizing.py` is the source of truth.

## 5. `wiz-sizing.py` — exact internal design

### 5.1 Imports (stdlib only)
`os, sys, shlex, subprocess, shutil, getpass, argparse, textwrap` and `curses` (imported lazily inside the curses UI so the prompt fallback works even if curses init fails).

### 5.2 Path resolution
```
LAUNCHER_DIR = Path(__file__).resolve().parent          # .../sizing-scripts/launcher
SIZING_ROOT  = LAUNCHER_DIR.parent                       # .../sizing-scripts
```
Each manifest `script` path is joined to `SIZING_ROOT` to get an absolute path. Before running, verify the file exists; if not, print the canonical `https://downloads.wiz.io/...` origin URL and the `git clone` hint, then return to the menu. (Primary distribution = the repo is present; this is a guard, not a downloader.)

### 5.3 The manifest (embedded `SCRIPTS` list)
A list of dicts near the top of the file, one per menu leaf. Exact schema:

```python
{
  "id": "aws-cloud",                  # stable key
  "csp": "aws",                       # aws|azure|gcp|None
  "group": "cloud",                   # cloud|defend|code|saas
  "label": "AWS — Cloud resource count",
  "script": "cloud/aws/resource-count-aws-v2.py",
  "runner": "python3",                # python3 | pwsh
  "auth": "ambient",                  # ambient | token | device-code
  "probe": ["boto3"],                 # modules to import-check (python); [] for pwsh
  "pip": "boto3 botocore eks_token kubernetes urllib3",  # exact install args
  "options": [
     {"flag": "--all",        "kind": "toggle", "advanced": False,
      "help": "Count all resource types"},
     {"flag": "--regions",    "kind": "csv",    "advanced": False,
      "help": "Comma-separated regions"},
     {"flag": "--output-dir", "kind": "path",   "advanced": False, "default": "."},
     {"flag": "--max-workers","kind": "int",    "advanced": True},
     # ...
  ],
  "token_args": [],                   # for auth=token: e.g. ["--token", "--org"]
}
```

`kind` ∈ `toggle | str | int | csv | path | choice`. For M365, `runner: "pwsh"`, flags use the PowerShell `-Name value` / `-Switch` form, and serialization (5.7) handles that style.

### 5.4 Environment detection (`detect_csp()`)
Checks in this order; first match wins; returns `aws|azure|gcp|None`:
1. **AWS:** `os.environ.get("AWS_EXECUTION_ENV","")` contains `"CloudShell"`. Backup: `AWS_REGION` set **and** `~/.aws` exists.
2. **GCP:** `os.environ.get("CLOUD_SHELL") == "true"`. Backup: `DEVSHELL_PROJECT_ID` or `GOOGLE_CLOUD_PROJECT` set.
3. **Azure:** `"cloud-shell"` in `os.environ.get("AZUREPS_HOST_ENVIRONMENT","")` **or** in `AZURE_HTTP_USER_AGENT`. Backup: any `ACC_*` var present.

`--csp aws|azure|gcp` on the command line overrides detection. These signals are documented as **needs in-shell confirmation** (I can't run inside a live CloudShell from here) — the `--csp` override and `--dry-run` make the launcher usable even if a signal is wrong.

### 5.5 Top-level flow
1. Parse args: `--csp`, `--dry-run` (build & print command, don't execute), `--list` (print manifest leaves and exit), `--no-curses` (force prompt mode).
2. `csp = args.csp or detect_csp()`.
3. If `csp` is set → open that CSP's submenu (its `cloud` + `defend` leaves) as the landing screen, with a visible "Switch provider / category" item that opens the full grouped menu.
4. If `csp` is None → open the full menu grouped **Cloud (AWS/Azure/GCP × count/Defend) · SaaS (M365) · Code (GitHub/GitLab/ADO)**.
5. User selects a leaf → option screen (5.6) → preflight (5.8) → command preview + confirm (5.9) → execute (5.10) → return to menu or quit.

### 5.6 Option collection
- Render Common options first; an "Advanced options…" entry expands the advanced set.
- Rendering by `kind`: `toggle` → on/off (space toggles); `int`/`str`/`csv`/`path` → inline text field with default shown; `choice` → cycle/list.
- `auth == "token"`: before options, prompt for each `token_args` value. Tokens read via `getpass.getpass()` (masked, never echoed, never written to disk). If a known env var is already set (e.g. the script's own default), offer to reuse it.
- `auth == "ambient"`: no credential prompt; a one-line banner notes "Using CloudShell credentials."

### 5.7 Argv serialization (`build_command(leaf, values) -> list[str]`)
- python runner: `["python3", ABS_SCRIPT] + flags`. `toggle` true → append `flag`; false → omit. Valued kinds → append `flag, str(value)` (csv passed as the single comma-joined string the scripts expect). Empty/unset → omit.
- pwsh runner (M365): `["pwsh", "-File", ABS_SCRIPT] + ps_flags`. Switch true → `-Name`; valued → `-Name`, `value`; bool `-UseDeviceCode` → `-UseDeviceCode:$true/$false`.

### 5.8 Dependency preflight (`preflight(leaf)`)
- pwsh leaf: `shutil.which("pwsh")`; if missing, explain M365 needs Azure Cloud Shell / PowerShell and return to menu.
- python leaf: run `subprocess.run([runner, "-c", "import a, b"], ...)` using the `probe` modules. On failure, display the exact `pip3 install --upgrade <pip>` line and offer **[Install now] / [Copy & skip] / [Back]**. "Install now" runs the pip command live (honoring the `--user` flag where the script's hint specifies it, e.g. Defend Azure/GCP), then re-probes.

### 5.9 Command preview & confirm
Print the exact command with `shlex.quote` (or the PowerShell-quoted form) so it's copy-pasteable and auditable, then require an explicit confirm. `--dry-run` stops here.

### 5.10 Execution
- `subprocess.run(cmd, cwd=<chosen output dir or SIZING_ROOT>)` with **inherited stdio** so live progress, interactive sub-prompts (M365 device-code, any script prompt), and Ctrl-C all behave normally. Curses screen is torn down before exec and restored after.
- On completion, show exit code and, when known, the output CSV path the script wrote (`*-resources.csv`, log-volume CSV, or developer-count output), then offer **[Run another] / [Quit]**.

### 5.11 Fallback (`--no-curses` or curses init failure or non-TTY)
Identical flow implemented with numbered `print` menus and `input()`/`getpass`. `build_command`, `preflight`, and `execute` are shared — only the rendering layer differs.

## 6. README content (`launcher/README.md`)
- One-paragraph "what this is."
- Per-CloudShell quick start, e.g. AWS: `cd sizing-scripts/launcher && python3 wiz-sizing.py` (auto-detects AWS) or `./launch-aws.sh`.
- Note that cloud/Defend scripts use the CloudShell's existing credentials; code scripts prompt for a token; M365 runs via `pwsh` in Azure Cloud Shell.
- `--dry-run`, `--csp`, `--list`, `--no-curses` documented.

## 7. Build sequence (phased, each independently testable)
1. [x] **Skeleton + manifest + AWS leaves** — detection, curses+fallback, preflight, serialization, dry-run, execute. Validate end-to-end in AWS CloudShell.
2. [x] **Azure + GCP cloud leaves + Defend leaves for all three** + per-CSP `.sh` shims.
3. [x] **Code group** (GitHub/GitLab/ADO) with masked token prompts.
4. [x] **M365** via the `pwsh` runner + `shutil.which` gate.
5. [x] **README** — done. [ ] follow-up PR folding in the deferred scripts as manifest-only additions (out of scope for v1, not yet started).

## 8. Testing approach (given I can't enter live CloudShells from here)
- [x] `--dry-run` (with `--leaf`) asserts the exact argv for representative option combinations per leaf (unit-style, runnable anywhere).
- [x] `--csp` override exercises each provider's submenu without the matching environment.
- [x] A short **manual matrix** to run in each real CloudShell: detection correct, preflight detects missing/installed SDK, a real small-scope scan completes, output file path reported. Documented in the launcher README. *(The matrix is documented; the in-shell runs themselves are for the operator to perform.)*

## 9. Risks / to confirm during the build
- **Azure Cloud Shell env vars differ between its bash and pwsh modes** — confirm `detect_csp()` against a live Azure shell; `--csp azure` is the safety valve.
- **`curses` over web terminals** (AWS/Azure/GCP are xterm.js) is expected fine; the prompt fallback is the net.
- **M365 needs `pwsh`** (present in Azure Cloud Shell, not AWS/GCP) — the leaf is hidden/blocked where `pwsh` is absent.
- **Defend scripts are `wiz-copy`** (unhardened); the launcher only wraps them, so no behavior change, but their flags are taken as-is from current `main`.

## 10. Prerequisite before coding — ✅ done
- [x] Rebase `claude/sizing-scripts-tui-plan-m83xs3` onto `origin/main` (`a9e3dc7`) so the `defend/` paths, hardened ADO flags, and updated M365 params referenced by the manifest actually exist in the tree. The launcher now lives on `main` (`27324c2`); the `defend/{aws,azure,gcp}/log-volume-estimation-*.py` paths it references all exist.
