# Wiz Sizing

Self-contained, **curl-able** sizing scripts — one bash file per cloud. Open
your cloud's shell, paste one line, and you're sizing in seconds. No install,
no modules, no build: what you paste is what runs, using only what each cloud
shell already ships (`az` / `aws` / `gcloud` + `jq` + `curl`, bash 4+).

| File | Run it in | Default run | Opt-ins |
|---|---|---|---|
| `wiz-azure.sh` | Azure Cloud Shell (bash) | Azure cloud resources **+ Defend ingest** | `--data` `--images` `--azdo` `--m365` |
| `wiz-aws.sh` | AWS CloudShell | AWS cloud resources **+ Defend ingest** | `--data` `--images` `--org` `--defend-detailed` |
| `wiz-gcp.sh` | Google Cloud Shell | GCP cloud resources **+ Defend ingest** | `--data` `--images` `--use-sink-metrics` |
| `wiz-code.sh` | anywhere (token) | — (opt-in domain) | GitHub · GitLab · HCP Terraform |
| `wiz-365.ps1` | Azure Cloud Shell (`pwsh`) | — (opt-in domain) | Microsoft 365 identity/drives |

Everything is **read-only** and uses your existing elevated session — no app
registrations, service principals, or consent grants for the default runs.
(The one scoped exception: `wiz-365.ps1` creates a *temporary, self-deleting*
Entra app so M365 counts are accurate; that's why M365 is opt-in.)

## One-line bootstrap

**Azure Cloud Shell (bash)**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-azure.sh)
```

**AWS CloudShell**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-aws.sh)
```

**Google Cloud Shell**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-gcp.sh)
```

**GitHub / GitLab / HCP Terraform** (run anywhere; prompts for a token, or set
`GITHUB_TOKEN` / `GITLAB_TOKEN` / `HCP_TOKEN`)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-code.sh)
```

**Microsoft 365** (Azure Cloud Shell / `pwsh`)

```powershell
iex (irm https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-365.ps1)
```

## Using it

Run a script with **no arguments** for a numbered interactive menu (profiles
first, then individual domains — robust in web terminals). Or drive it
non-interactively with a subcommand:

```bash
wiz-azure.sh                     # interactive menu
wiz-azure.sh all                 # cloud + Defend, accurate (the default)
wiz-azure.sh cloud --fast        # fast Resource Graph estimate
wiz-aws.sh all --org             # every ACTIVE org account via assume-role
wiz-gcp.sh defend --days 14      # Defend only, 14-day window
wiz-code.sh github --org my-org  # developer counting, one provider
```

Common flags on every CSP script:

| Flag | What it does |
|---|---|
| `--fast` | Fast estimate from each cloud's index (Resource Graph / Resource Explorer / Cloud Asset Inventory) with graceful per-dimension fallback to the accurate path. Deviations below. |
| `--data` | Adds Data Security resources (buckets, PaaS databases, warehouses) — lengthens the scan, off by default like the official scripts |
| `--images` | Adds registry container images (ACR / ECR / Artifact Registry) |
| `--resume` | Continues an interrupted scan from its per-scope checkpoints |
| `--output-dir DIR` | Where the CSVs land |
| `--max-parallel N` | Concurrent scope scans (default 8) |
| `--dry-run` | Prints every API call the run would make and exits — needs **no cloud session** |
| `--quiet` | Progress off (CSVs unchanged) |
| `--help` / `--list` | Full usage / mode list |

Scoping: `wiz-azure.sh --subscription ID | --subscriptions-file F`,
`wiz-aws.sh --org | --accounts-file F | --regions LIST`,
`wiz-gcp.sh --projects LIST | --org ORG_ID` (GCP `--org` scopes every scan —
accurate, Defend, fast — to the org's projects, folders included). Defaults
scan everything your session can see (all subscriptions / current account /
all listable projects).

### Long scans

Scans survive the realities of big tenants: tokens are re-acquired from the
CLI per audience as they near expiry (AWS re-assumes member-account roles),
each scope writes to its own temp file merged by a single writer, `Ctrl-C`
flushes partial CSVs plus a resume hint, and `--resume` skips completed
scopes. Progress goes to stderr; data to stdout and the CSVs. Every run ends
with an error rollup — failures are never silent.

## Wiz Defend ingest

The default `all` run estimates Defend ingest alongside the cloud count, and
**auto-discovers its sources** — you don't need to know bucket or workspace
names:

- **Azure** — Log Analytics workspaces from tenant (Entra), management-group
  and subscription diagnostic settings; the official Usage-table KQL and
  fallbacks. `--defend-workspace GUIDs` supplements discovery.
- **AWS** — CloudTrail buckets from `describe-trails`, s3-destination VPC flow
  logs and Route 53 resolver query-log configs. Default is the official
  metrics-based basic estimation; `--defend-detailed` opts into the official
  S3 object-sampling breakdown (slower, minor API cost).
  `--defend-*-bucket` flags override or supplement.
- **GCP** — Cloud Monitoring `byte_count` metrics with the official exclusion
  ratios; `--use-sink-metrics` measures actual Wiz sink volume instead.

If nothing is discoverable and no flags are given, Defend prints a one-line
note and the run continues — it never fails the scan.

## Opt-in domains (never in a CSP default)

- **Azure DevOps** — `wiz-azure.sh --azdo [--org ORG]` counts active repo
  developers over AzDO REST. If an org is detected in your environment the
  script asks once (30s timeout, defaults to *skip*, so unattended runs never
  block); `--no-azdo` silences the prompt.
- **Microsoft 365** — `wiz-azure.sh --m365` hands off to `wiz-365.ps1` via
  `pwsh` (or prints the one-liner). Device-code auth + a self-cleaning
  temporary Entra app for accurate Graph counts; the app is deleted when the
  script finishes.
- **Code sizing** — `wiz-code.sh` covers GitHub, GitLab and HCP Terraform
  active-developer counts. Token-based (masked prompt; reuses `*_TOKEN` env
  vars). Developer identities are sha256-hashed on disk unless `--decrypt`.

## Output (CSV)

Filenames and headers are identical to the official Wiz sizing scripts, so
downstream tooling keeps working:

| Mode | Default file(s) | Columns |
|---|---|---|
| Azure cloud | `azure-resources.csv` (+ `-log`) | Resource Type, Resource Count (+ Subscription) |
| Azure Defend | `azure-defend-log-volume-<timestamp>.csv` | Log Source Type, Billable Category, Specific Metric, Resource/Scope Details, Estimated 30-Day Uncompressed Volume (GB) |
| Azure DevOps | `azure_devops-<org>-developers.txt` (+ `-log`) | Organization, Project, Repository, Developers (Last N Days), Commits Scanned, Status, Error |
| AWS cloud | `aws-resources.csv` (+ `-log`) | Resource Type, Resource Count (+ Account, Region) |
| AWS Defend | `aws-defend-log-volume.csv` | Log Source Type, Billable Category, Specific Metric, Bucket/Prefix Details, Estimated 30-Day Uncompressed Volume (GB) |
| GCP cloud | `gcp-resources.csv` (+ `-log`) | Resource Type, Resource Count (+ Project, Region) |
| GCP Defend | `gcp-defend-log-volume-<timestamp>.csv` | Log Source Type, Billable Category, Specific Metric, Resource/Scope Details, Estimated 30-Day Uncompressed Volume (GB) |
| GitHub / GitLab / HCP | `<provider><slug>-developers.txt` (+ `-log`), `hcpt-developers.txt`, `active-developers.txt` | Organization/Group, Repository/Project, Developers (Last N Days) |

Each run ends with a summary block whose lines map 1:1 onto the
billable-units calculator, so you paste numbers instead of transcribing CSVs.

## Fidelity: how the counts are validated

These bash scripts are **reimplementations** of the official Wiz sizing
scripts, so fidelity is engineered, not assumed:

1. The official (field-hardened) scripts live under [`reference/`](reference/)
   — the *parity oracle*. They are never shipped or curled.
2. [`parity/mapping.md`](parity/mapping.md) maps **every count** to the
   official source line and the exact bash call + `jq` reduction that
   reproduces it — reviewable with no credentials.
3. [`tests/contract.bats`](tests/) pins each script's CSV filenames and header
   rows to the officials'; [`tests/smoke.bats`](tests/) proves `--help` /
   `--list` / `--dry-run` / the menu run with the cloud CLIs stubbed out
   entirely. CI runs both plus `shellcheck` on every push.
4. [`tests/mock_e2e.bats`](tests/) runs the real counting paths end-to-end
   against fixture APIs (stubbed `curl`/`az`/`aws`/`gcloud`, no network) and
   diffs each produced `<csp>-resources.csv` against hand-verified expected
   files — including fast-mode fallback, GCP `--org` scoping, and
   one-token-per-audience acquisition. CI runs it on every push.
5. [`parity/diff.sh`](parity/diff.sh) runs the official Python and the bash
   script against the *same live scope* (both sides get an explicit
   `--scope <ID>`) and diffs the CSVs per resource type — the final, live
   gate.

Known, deliberate deviations are documented in
[`PLAN.md` §9](PLAN.md) (D1–D6) — each notes its direction; where a deviation
has one, it leans **high**, so a sizing quote is never short.

> **Status — awaiting live parity.** The retired-in-waiting Python
> (`wiz-*.py`, `tools/`) stays in-tree as the safety net until each cloud has
> passed at least one live `parity/diff.sh` run against a real tenant/account.
> Structural checks alone never trigger deletion. Once a CSP passes its live
> diff, its Python leaves via git history.

## Repository layout

```
wiz-azure.sh  wiz-aws.sh  wiz-gcp.sh  wiz-code.sh  wiz-365.ps1   # what you run
reference/    # official + hardened source scripts — the parity oracle (not shipped)
parity/       # mapping.md (per-count citations) + diff.sh (live parity harness)
tests/        # contract.bats + smoke.bats + mock_e2e.bats (+ mocks/) — no-creds CI gates
wiz-*.py, tools/   # previous Python generation — retained awaiting live parity
```

## License

MIT — see [`LICENSE`](LICENSE).
