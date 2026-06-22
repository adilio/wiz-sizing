# Wiz Sizing

Self-contained, **curl-able** sizing scripts — one file per cloud. Open your
cloud's CloudShell, paste one line, and you're sizing in seconds. No install, no
build, no tree to navigate: what's in the repo is exactly what you run.

| File | Run it in | Modes |
|---|---|---|
| `wiz-azure.py` | Azure Cloud Shell | Azure Cloud · Azure Defend · Azure DevOps (+ drives Microsoft 365) |
| `wiz-aws.py` | AWS CloudShell | AWS Cloud · AWS Defend |
| `wiz-gcp.py` | GCP Cloud Shell | GCP Cloud · GCP Defend |
| `wiz-code.py` | anywhere (token) | GitHub · GitLab |
| `wiz-365.ps1` | Azure Cloud Shell (`pwsh`) | Microsoft 365 |

## One-line bootstrap

**Azure Cloud Shell**

```bash
curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-azure.py -o wiz-azure.py && python3 wiz-azure.py
```

**AWS CloudShell**

```bash
curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-aws.py -o wiz-aws.py && python3 wiz-aws.py
```

**GCP Cloud Shell**

```bash
curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-gcp.py -o wiz-gcp.py && python3 wiz-gcp.py
```

**GitHub / GitLab** (run anywhere; prompts for a token)

```bash
curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-code.py -o wiz-code.py && python3 wiz-code.py
```

**Microsoft 365** (Azure Cloud Shell / `pwsh`)

```bash
curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-365.ps1 -o wiz-365.ps1 && pwsh ./wiz-365.ps1
```

The Python files have **no dependencies of their own** — the menu, dependency
handling, and CSV output are pure standard library. Each mode's cloud SDK is
imported only when you pick that mode, and the script offers to `pip install` it
on the spot. (The same files also run straight from a `git clone`.)

## Using it

Run a file with no arguments for the interactive menu (arrow-key where a real
terminal is available, numbered prompts otherwise). The menu lists **profiles**
first, then individual modes.

A **profile** is a recommended, one-confirmation sweep:

- `wiz-azure.py` → **Recommended full sweep** (Azure Cloud + Defend tenant-wide,
  then offers Azure DevOps + Microsoft 365), and **All Microsoft estate** (Cloud
  + Defend → Azure DevOps → Microsoft 365 as committed steps).
- `wiz-aws.py` → **Recommended full sweep** (all accounts + regions, then Defend).
- `wiz-gcp.py` → **Recommended full sweep** (all projects, then Defend org-wide;
  the org id is auto-detected via `gcloud`).

Scope identity is auto-detected best-effort and never blocks: Azure tenant
(`az`), GCP org (`gcloud`), Azure DevOps org (`az devops`).

### Non-interactive flags

Every file accepts the same flags:

```bash
python3 wiz-azure.py --list                       # list modes & profiles
python3 wiz-azure.py --mode azure-cloud --dry-run # show the command, run nothing
python3 wiz-azure.py --profile azure-recommended  # run a profile
python3 wiz-azure.py --mode azure-cloud --set=--all=on --set=--max-workers=8
python3 wiz-azure.py --mode azure-cloud -- --all --debug   # pass flags through after --
```

`--set=--flag=value` sets an option (use the attached `=` form; repeatable).
Anything after a bare `--` is passed straight to the underlying mode.

### Scope lists

Options that take a list of IDs (regions, subscriptions, projects, accounts,
excluded folders) are entered as a comma/space list. The file writes them to the
sibling `.txt` file the scanner reads (`regions.txt`, `subscriptions.txt`,
`projects.txt`, `accounts.txt`, `excluded-folders.txt`) and passes the bare flag.

## Credentials

- **Cloud & Defend** modes use the CloudShell's existing credentials (ambient
  auth) — no prompt.
- **Azure DevOps / GitHub / GitLab** prompt for a token (input masked). They
  reuse `ADO_TOKEN` / `GITHUB_TOKEN` / `GITLAB_TOKEN` from the environment if set.
- **Microsoft 365** authenticates via device-code flow handled by `wiz-365.ps1`.

## Output (CSV)

Each mode writes the same CSV file(s) it always has:

| Mode | Default file(s) | Columns |
|---|---|---|
| `azure-cloud` | `azure-resources.csv` (+ `-log`) | Resource Type, Resource Count (+ Subscription) |
| `azure-defend` | `azure-defend-log-volume-<timestamp>.csv` | Log Source Type, Billable Category, Specific Metric, Resource/Scope Details, Estimated 30-Day Uncompressed Volume (GB) |
| `azure-devops` | active-developer CSV | Organization, Project, Repository, Developers (Last N Days), Commits Scanned, Status, Error |
| `aws-cloud` | `aws-resources.csv` (+ `-log`) | Resource Type, Resource Count (+ Account, Region) |
| `aws-defend` | `aws-defend-log-volume.csv` | Log Source Type, Billable Category, Specific Metric, Bucket/Prefix Details, Estimated 30-Day Uncompressed Volume (GB) |
| `gcp-cloud` | `gcp-resources.csv` (+ `-log`) | Resource Type, Resource Count (+ Project, Region) |
| `gcp-defend` | `gcp-defend-log-volume-<timestamp>.csv` | Log Source Type, Billable Category, Specific Metric, Resource/Scope Details, Estimated 30-Day Uncompressed Volume (GB) |
| `github` | active-developer CSV | Organization, Repository, Developers (Last N Days) |
| `gitlab` | active-developer CSV | Group, Project, Developers (Last N Days) |

The scanning logic is the original standalone sizing scripts, **embedded
verbatim and run in-process**, so the CSV output is byte-identical to running
those scripts directly.

## Repository layout

```
wiz-azure.py  wiz-aws.py  wiz-gcp.py  wiz-code.py  wiz-365.ps1   # what you run
tests/        # output-contract + scaffolding tests (pure stdlib)
tools/        # how the wiz-*.py files are assembled (dev only; see below)
```

### Maintaining the files

The `wiz-*.py` files are generated by combining a small per-file config
(`tools/config_<csp>.py`: menu, options, profiles), the shared engine
(`tools/_engine.py`), and the embedded legacy sources:

```bash
python3 tools/build_wiz.py          # rebuild every wiz-*.py
python3 tools/build_wiz.py azure    # rebuild one
python3 tools/build_wiz.py --check  # CI: fail if a committed file is stale
python3 -m unittest discover -s tests
```

The embedded payload inside each `wiz-*.py` is the source of truth, so
**scaffolding** changes (anything in `tools/_engine.py` or `tools/config_*.py`)
regenerate cleanly even though the original `sizing-scripts/` tree has been
removed — `build_wiz.py` reuses the blob already embedded in the committed file.

Changing a **scanner** (the lifted per-cloud logic) is the one case that needs
the legacy source back. It lives in git history; restore, edit, and rebuild:

```bash
# bring back the one scanner you need to change
git checkout ef801dc -- sizing-scripts/cloud/azure/resource-count-azure-v2.py
# edit it, then rebuild — the new source is re-embedded into wiz-azure.py
python3 tools/build_wiz.py azure
python3 -m unittest discover -s tests   # CSV-contract + scaffolding gates
```

(The per-scanner paths are listed in `tools/build_wiz.py`'s `SPECS`.) Because the
embedded blob is byte-checked only at build time, keep scanner edits going through
this restore-edit-rebuild path rather than hand-editing the base64 in `wiz-*.py`.

## Verifying a real run (operator checklist)

The cloud scans need a live, authenticated CloudShell and can't run off-box. To
validate a release in each CloudShell: curl the file, run a recommended sweep at
small scope, byte-diff the produced CSV against the legacy script's CSV for the
same scope, and confirm the on-demand dependency install works.

## License

MIT — see [`LICENSE`](LICENSE).
