# Wiz Sizing TUI Launcher

An interactive, menu-driven launcher for the Wiz sizing scripts. It runs **inside
each cloud's CloudShell** with **zero install footprint of its own** — it is pure
Python standard library, so there is nothing to `pip install` for the launcher
itself. It presents a full-screen arrow-key menu (via `curses`) and automatically
falls back to numbered prompts on a dumb or non-TTY terminal.

The launcher only *wraps* the existing sizing scripts. It never imports a cloud
SDK and never edits the target scripts; the menu is generated from a declarative
manifest embedded in `wiz-sizing.py`, so adding a script is a data edit.

## What it covers

- **Cloud resource count** — AWS, Azure, GCP
- **Defend log volume** — AWS, Azure, GCP
- **SaaS** — Microsoft 365 (runs via `pwsh`)
- **Code** — GitHub, GitLab, Azure DevOps (prompt for a token)

## Quick start

Open your cloud's CloudShell (AWS / Azure / GCP), then clone the repo and run the
launcher. The scans need the sizing scripts present, so cloning is the normal path:

```bash
git clone https://github.com/wiz-sec/wiz-sizing.git
cd wiz-sizing/sizing-scripts/launcher
python3 wiz-sizing.py
```

That's it — no `pip install` for the launcher itself. It auto-detects which
CloudShell it is running in and lands you on that provider's submenu, with a
**Switch provider / category** item that opens the full cross-provider menu.

Per-CSP shims do the same as `--csp`:

```bash
./launch-aws.sh      # same as: python3 wiz-sizing.py --csp aws
./launch-azure.sh    # --csp azure
./launch-gcp.sh      # --csp gcp
```

### Grab just the launcher (inspect / dry-run)

`wiz-sizing.py` is a single self-contained file, so you can pull only the launcher
to read it, list the menu, or preview commands:

```bash
curl -fsSL https://downloads.wiz.io/sizing/wiz-sizing.py -o wiz-sizing.py
python3 wiz-sizing.py --list                 # show the menu leaves
python3 wiz-sizing.py --dry-run --profile aws  # preview a sweep's commands
```

Note: to actually *run* a scan the launcher must find the sizing scripts in a
sibling `sizing-scripts/` tree (i.e. its parent directory). On its own it will
print where to get them rather than running anything — so for real scans, clone
the repo as above.

## What happens when you run it

1. **Detection.** The launcher figures out which CloudShell it's in and opens that
   provider's submenu. `--csp aws|azure|gcp` overrides detection if a signal is
   wrong.
2. **Pick what to run.** Either the **★ Recommended full sweep** (top item — see
   below) or a single script (e.g. *Azure — Cloud resource count*).
3. **Set options.** Common options show first; an **Advanced options** toggle
   reveals the rest. Toggles are checkboxes; everything else is an inline text
   field with its default shown.
4. **Credentials.** Cloud/Defend scripts use ambient CloudShell auth (no prompt).
   Code scripts (GitHub/GitLab/ADO) prompt for a token, read masked. See
   [Credentials](#credentials).
5. **Dependency preflight.** The launcher import-checks the script's SDK and, if
   missing, offers to `pip install` it for you. See
   [Dependency preflight](#dependency-preflight).
6. **Preview & confirm.** It prints the exact, copy-pasteable command and waits for
   an explicit `y` before running anything.
7. **Run.** The script runs with live output (Ctrl-C works); on exit you get the
   return code and where output was written, then **Run another / Quit**.

**Navigation (full-screen menu):** `↑`/`↓` (or `j`/`k`) to move, `Enter` to
select / toggle / edit a field, `q` or `Esc` to go back. On a non-TTY or dumb
terminal it falls back to numbered prompts with the identical flow.

## Recommended full sweep (one confirmation)

Each provider's submenu starts with **★ Recommended full sweep** — an inclusive,
org-wide profile that runs under a single confirmation:

| CSP | What it runs |
|-----|--------------|
| AWS | Cloud resource count `--all --data --images` (all accounts in the Organization), then Defend log volume |
| Azure | Cloud resource count `--all --data --images` (all subscriptions in the Management Group), then Defend `--all-subscriptions` (tenant-wide) |
| GCP | Cloud resource count `--all --data --images` (all projects), then Defend `--org-aggregate` (org-wide) |

After the core steps it offers the opt-ins **Microsoft 365** and **Azure DevOps**.
Where an org-wide scan needs a scope identity, the launcher auto-detects it
best-effort (GCP organization id via `gcloud`, Azure tenant via `az`) and asks you
to confirm; detection never blocks — if it fails you are prompted for the value.

## Scoping a scan (regions / accounts / subscriptions / projects)

The cloud scripts read scope IDs from a sibling text file (`regions.txt`,
`accounts.txt`, `subscriptions.txt`, `projects.txt`, `excluded-folders.txt`) and
are enabled by a bare flag. The launcher handles this for you: type a
comma/space-separated list into e.g. `--regions`, and it writes the `.txt` file
into the run directory and passes the bare `--regions` flag. To scan a single
target instead, use `--id`.

## Credentials

- **Cloud and Defend scripts** use the CloudShell's existing credentials
  (ambient auth) — no token is requested.
- **Code scripts** (GitHub / GitLab / Azure DevOps) prompt for a token. Tokens are
  read masked via `getpass`, never echoed and never written to disk.
  - **Azure DevOps** reads `ADO_TOKEN` natively; the launcher offers to reuse it
    if set. The `--org` is auto-detected best-effort (from `AZURE_DEVOPS_ORG`, then
    `az devops configure`) and you confirm it.
  - `GITHUB_TOKEN` and `GITLAB_TOKEN` are **launcher conventions** — the GitHub and
    GitLab scripts do not read them themselves; the launcher simply reuses them to
    fill `--token` if they happen to be set.
- **Microsoft 365** runs through `pwsh` (present in Azure Cloud Shell, not in
  AWS/GCP CloudShell) and authenticates with a device-code flow. The M365 leaf is
  blocked where `pwsh` is absent.

## Dependency preflight

Before running a Python script, the launcher import-checks the script's required
module(s). If they are missing it shows the exact `pip3 install --upgrade …` line
and offers **[Install now] / [Copy & skip] / [Back]**. "Install now" runs the pip
command live (honoring `--user` where the script's own hint specifies it, e.g. the
Azure/GCP Defend scripts) and then re-probes.

## Output files

Each script writes its own CSV. Cloud resource-count scripts honor `--output-dir`
(default: the current directory); the Defend scripts write into the working
directory (e.g. `aws-defend-log-volume.csv`), and Azure/GCP Defend also accept
`--output-filename`. After a run the launcher prints the exit code and the
directory the output was written to. Scope files the launcher creates
(`regions.txt`, `subscriptions.txt`, …) are also left in the run directory.

## Flags

| Flag | Effect |
|------|--------|
| `--csp aws\|azure\|gcp` | Force a provider's submenu; overrides auto-detection. |
| `--dry-run` | Build and print the exact command, but never execute it. |
| `--list` | Print the manifest leaves (id, label, script path) and exit. |
| `--no-curses` | Force the numbered-prompt fallback UI. |
| `--leaf ID` | Print one leaf's command (combine with `--dry-run` for testing). |
| `--set=--flag=value` | With `--leaf`: override an option (repeatable; use the attached `=` form, e.g. `--set=--all=on`). |
| `--profile aws\|azure\|gcp` | With `--dry-run`: print a recommended-sweep profile's steps. |

The printed command uses `shlex.quote` (or PowerShell-style quoting for M365) so it
is copy-pasteable and auditable.

## Manual validation matrix (run in each real CloudShell)

`--dry-run`, `--list`, `--profile`, and the unit tests are runnable anywhere and
assert the menu/command wiring (including non-default scope combinations):

```bash
python3 test_wiz_sizing.py
```

The following must be confirmed inside each live CloudShell, since environment
detection and ambient auth can't be exercised from outside:

1. **Detection** — `python3 wiz-sizing.py` lands on the correct provider. If a
   signal is wrong, `--csp <provider>` is the safety valve.
2. **Preflight** — with the SDK absent, the install prompt appears; "Install now"
   makes the re-probe pass.
3. **Real small-scope scan** — e.g. a single account/subscription/project completes
   and the output file path is reported.
4. **Azure note** — Azure Cloud Shell's env vars differ between its bash and pwsh
   modes; verify detection in the mode you use, or pass `--csp azure`.

## Adding more scripts later

Deferred providers (OCI, Alibaba, Linode, Snowflake, vSphere, HCP Terraform) slot
in as additions to the `SCRIPTS` manifest in `wiz-sizing.py` — no UI changes
needed.
