#!/usr/bin/env python3
"""Wiz Sizing TUI Launcher.

An interactive, menu-driven launcher for the Wiz sizing scripts. It is designed
to run inside each cloud's CloudShell with zero install footprint of its own:
pure Python standard library only, with a curses full-screen menu that degrades
to numbered input() prompts on dumb/non-TTY terminals.

The launcher only *wraps* the existing sizing scripts. It never imports a cloud
SDK and never edits the target scripts. The menu is generated from the embedded
SCRIPTS manifest below, so adding a script is a data edit, not new UI code.

Usage:
    python3 wiz-sizing.py                # auto-detect the CloudShell you're in
    python3 wiz-sizing.py --csp aws      # force a provider's submenu
    python3 wiz-sizing.py --list         # print the manifest leaves and exit
    python3 wiz-sizing.py --dry-run      # build & print the command, never run
    python3 wiz-sizing.py --no-curses    # force the numbered-prompt fallback
    python3 wiz-sizing.py --dry-run --leaf aws-cloud   # print one leaf's default cmd
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
LAUNCHER_DIR = Path(__file__).resolve().parent          # .../sizing-scripts/launcher
SIZING_ROOT = LAUNCHER_DIR.parent                        # .../sizing-scripts
ORIGIN_URL = "https://downloads.wiz.io/"
REPO_HINT = "git clone https://github.com/wiz-sec/wiz-sizing.git"

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
# One dict per menu leaf. Schema:
#   id      stable key
#   csp     aws|azure|gcp|None
#   group   cloud|defend|code|saas
#   label   menu text
#   script  path relative to SIZING_ROOT
#   runner  python3 | pwsh
#   auth    ambient | token | device-code
#   probe   list of modules to import-check (python); [] for pwsh
#   pip     exact install args (after `pip3 install --upgrade ...`)
#   options list of {flag, kind, advanced, help, default, choices}
#             kind in: toggle|str|int|csv|path|choice
#   token_args  for auth=token: list of {flag, prompt, secret, env}
SCRIPTS = [
    {
        "id": "aws-cloud",
        "csp": "aws",
        "group": "cloud",
        "label": "AWS — Cloud resource count",
        "script": "cloud/aws/resource-count-aws-v2.py",
        "runner": "python3",
        "auth": "ambient",
        "probe": ["boto3"],
        "pip": "boto3 botocore eks_token kubernetes urllib3",
        "options": [
            {"flag": "--all", "kind": "toggle", "advanced": False,
             "help": "Count all supported resource types"},
            {"flag": "--data", "kind": "toggle", "advanced": False,
             "help": "Include data-sensitive resource counts"},
            {"flag": "--images", "kind": "toggle", "advanced": False,
             "help": "Include container image counts"},
            {"flag": "--regions", "kind": "csv", "advanced": False,
             "help": "Comma-separated regions to scan"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output CSV"},
            {"flag": "--accounts", "kind": "csv", "advanced": True,
             "help": "Comma-separated account IDs"},
            {"flag": "--id", "kind": "str", "advanced": True,
             "help": "Run identifier"},
            {"flag": "--role-name", "kind": "str", "advanced": True,
             "help": "Cross-account role name"},
            {"flag": "--gov", "kind": "toggle", "advanced": True,
             "help": "Target AWS GovCloud partition"},
            {"flag": "--china", "kind": "toggle", "advanced": True,
             "help": "Target AWS China partition"},
            {"flag": "--include-account-regex", "kind": "str", "advanced": True},
            {"flag": "--exclude-account-regex", "kind": "str", "advanced": True},
            {"flag": "--start-after-account", "kind": "str", "advanced": True},
            {"flag": "--max-accounts", "kind": "int", "advanced": True},
            {"flag": "--max-workers", "kind": "int", "advanced": True},
            {"flag": "--max-run-minutes", "kind": "int", "advanced": True},
            {"flag": "--max-image-tags", "kind": "int", "advanced": True},
            {"flag": "--max-lambda-versions", "kind": "int", "advanced": True},
            {"flag": "--checkpoint-interval", "kind": "int", "advanced": True},
            {"flag": "--verbose", "kind": "toggle", "advanced": True},
            {"flag": "--debug", "kind": "toggle", "advanced": True},
        ],
        "token_args": [],
    },
    {
        "id": "aws-defend",
        "csp": "aws",
        "group": "defend",
        "label": "AWS — Defend log volume",
        "script": "defend/aws/log-volume-estimation-aws.py",
        "runner": "python3",
        "auth": "ambient",
        "probe": ["boto3"],
        "pip": "boto3 botocore",
        "options": [
            {"flag": "--defend-detailed", "kind": "toggle", "advanced": False,
             "help": "Produce a detailed per-source breakdown"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output CSV"},
            {"flag": "--defend-cloudtrail-logs-bucket", "kind": "str", "advanced": True},
            {"flag": "--defend-cloudtrail-logs-bucket-prefix", "kind": "str", "advanced": True},
            {"flag": "--defend-cloudtrail-logs-bucket-days", "kind": "int", "advanced": True},
            {"flag": "--defend-cloudtrail-logs-bucket-sample-size", "kind": "int", "advanced": True},
            {"flag": "--defend-cloudtrail-logs-compression-factor", "kind": "str", "advanced": True},
            {"flag": "--defend-vpc-flow-logs-bucket", "kind": "str", "advanced": True},
            {"flag": "--defend-vpc-flow-logs-compression-factor", "kind": "str", "advanced": True},
            {"flag": "--defend-route53-resolver-logs-bucket", "kind": "str", "advanced": True},
            {"flag": "--defend-route53-resolver-logs-compression-factor", "kind": "str", "advanced": True},
            {"flag": "--max-workers", "kind": "int", "advanced": True},
            {"flag": "--verbose", "kind": "toggle", "advanced": True},
            {"flag": "--debug", "kind": "toggle", "advanced": True},
        ],
        "token_args": [],
    },
    {
        "id": "azure-cloud",
        "csp": "azure",
        "group": "cloud",
        "label": "Azure — Cloud resource count",
        "script": "cloud/azure/resource-count-azure-v2.py",
        "runner": "python3",
        "auth": "ambient",
        "probe": ["azure.mgmt.resourcegraph"],
        "pip": "azure-identity azure-mgmt-resource azure-mgmt-resourcegraph "
               "azure-mgmt-subscription azure-mgmt-compute",
        "options": [
            {"flag": "--all", "kind": "toggle", "advanced": False,
             "help": "Count all supported resource types"},
            {"flag": "--data", "kind": "toggle", "advanced": False,
             "help": "Include data-sensitive resource counts"},
            {"flag": "--images", "kind": "toggle", "advanced": False,
             "help": "Include container image counts"},
            {"flag": "--subscriptions", "kind": "csv", "advanced": False,
             "help": "Comma-separated subscription IDs"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output CSV"},
            {"flag": "--graph", "kind": "toggle", "advanced": True,
             "help": "Use Resource Graph queries"},
            {"flag": "--id", "kind": "str", "advanced": True},
            {"flag": "--gov", "kind": "toggle", "advanced": True},
            {"flag": "--china", "kind": "toggle", "advanced": True},
            {"flag": "--germany", "kind": "toggle", "advanced": True},
            {"flag": "--include-subscription-regex", "kind": "str", "advanced": True},
            {"flag": "--exclude-subscription-regex", "kind": "str", "advanced": True},
            {"flag": "--start-after-subscription", "kind": "str", "advanced": True},
            {"flag": "--max-subscriptions", "kind": "int", "advanced": True},
            {"flag": "--max-workers", "kind": "int", "advanced": True},
            {"flag": "--max-run-minutes", "kind": "int", "advanced": True},
            {"flag": "--max-image-tags", "kind": "int", "advanced": True},
            {"flag": "--request-timeout", "kind": "int", "advanced": True},
            {"flag": "--checkpoint-interval", "kind": "int", "advanced": True},
            {"flag": "--verbose", "kind": "toggle", "advanced": True},
            {"flag": "--debug", "kind": "toggle", "advanced": True},
        ],
        "token_args": [],
    },
    {
        "id": "azure-defend",
        "csp": "azure",
        "group": "defend",
        "label": "Azure — Defend log volume",
        "script": "defend/azure/log-volume-estimation-azure.py",
        "runner": "python3",
        "auth": "ambient",
        "probe": ["requests"],
        "pip": "--user azure-identity azure-mgmt-resource azure-mgmt-subscription "
               "azure-monitor-query requests",
        "options": [
            {"flag": "--subscription-id", "kind": "str", "advanced": False,
             "help": "Single subscription to analyze"},
            {"flag": "--all-subscriptions", "kind": "toggle", "advanced": False,
             "help": "Analyze every accessible subscription"},
            {"flag": "--log-analysis-days", "kind": "int", "advanced": False,
             "help": "Look-back window in days"},
            {"flag": "--output-filename", "kind": "path", "advanced": False,
             "help": "Output CSV filename"},
            {"flag": "--errors-log-filename", "kind": "path", "advanced": True},
            {"flag": "--verbose", "kind": "toggle", "advanced": True},
            {"flag": "--debug", "kind": "toggle", "advanced": True},
        ],
        "token_args": [],
    },
    {
        "id": "gcp-cloud",
        "csp": "gcp",
        "group": "cloud",
        "label": "GCP — Cloud resource count",
        "script": "cloud/gcp/resource-count-gcp-v2.py",
        "runner": "python3",
        "auth": "ambient",
        "probe": ["googleapiclient.discovery", "google.auth"],
        "pip": "google-api-python-client google-auth",
        "options": [
            {"flag": "--all", "kind": "toggle", "advanced": False,
             "help": "Count all supported resource types"},
            {"flag": "--data", "kind": "toggle", "advanced": False,
             "help": "Include data-sensitive resource counts"},
            {"flag": "--images", "kind": "toggle", "advanced": False,
             "help": "Include container image counts"},
            {"flag": "--projects", "kind": "csv", "advanced": False,
             "help": "Comma-separated project IDs"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output CSV"},
            {"flag": "--id", "kind": "str", "advanced": True},
            {"flag": "--exclude", "kind": "csv", "advanced": True,
             "help": "Comma-separated projects to exclude"},
            {"flag": "--include-project-regex", "kind": "str", "advanced": True},
            {"flag": "--exclude-project-regex", "kind": "str", "advanced": True},
            {"flag": "--start-after-project", "kind": "str", "advanced": True},
            {"flag": "--max-projects", "kind": "int", "advanced": True},
            {"flag": "--max-pages-per-request", "kind": "int", "advanced": True},
            {"flag": "--max-workers", "kind": "int", "advanced": True},
            {"flag": "--max-run-minutes", "kind": "int", "advanced": True},
            {"flag": "--max-image-tags", "kind": "int", "advanced": True},
            {"flag": "--request-timeout", "kind": "int", "advanced": True},
            {"flag": "--checkpoint-interval", "kind": "int", "advanced": True},
            {"flag": "--inventory-instructions", "kind": "toggle", "advanced": True},
            {"flag": "--verbose", "kind": "toggle", "advanced": True},
            {"flag": "--debug", "kind": "toggle", "advanced": True},
        ],
        "token_args": [],
    },
    {
        "id": "gcp-defend",
        "csp": "gcp",
        "group": "defend",
        "label": "GCP — Defend log volume",
        "script": "defend/gcp/log-volume-estimation-gcp.py",
        "runner": "python3",
        "auth": "ambient",
        "probe": ["google.auth"],
        "pip": "--user google-cloud-monitoring google-api-core google-auth "
               "google-cloud-resource-manager google-cloud-logging",
        "options": [
            {"flag": "--project-id", "kind": "str", "advanced": False,
             "help": "Single project to analyze"},
            {"flag": "--organization-id", "kind": "str", "advanced": False,
             "help": "Organization to analyze"},
            {"flag": "--org-aggregate", "kind": "toggle", "advanced": False,
             "help": "Aggregate across the whole organization"},
            {"flag": "--log-analysis-days", "kind": "int", "advanced": False,
             "help": "Look-back window in days"},
            {"flag": "--output-filename", "kind": "path", "advanced": False,
             "help": "Output CSV filename"},
            {"flag": "--use-sink-metrics", "kind": "toggle", "advanced": True},
            {"flag": "--sink-name", "kind": "str", "advanced": True},
            {"flag": "--no-exclusion-adjustment", "kind": "toggle", "advanced": True},
            {"flag": "--workers", "kind": "int", "advanced": True},
            {"flag": "--errors-log-filename", "kind": "path", "advanced": True},
            {"flag": "--verbose", "kind": "toggle", "advanced": True},
            {"flag": "--debug", "kind": "toggle", "advanced": True},
        ],
        "token_args": [],
    },
    {
        "id": "m365",
        "csp": None,
        "group": "saas",
        "label": "Microsoft 365",
        "script": "saas/microsoft-365/365_Sizing_Script.ps1",
        "runner": "pwsh",
        "auth": "device-code",
        "probe": [],
        "pip": "",
        "options": [
            {"flag": "-SummaryOnly", "kind": "toggle", "advanced": False,
             "help": "Only emit the summary, skip per-site detail"},
            {"flag": "-MaxSites", "kind": "int", "advanced": False,
             "help": "Cap the number of sites scanned (0 = all)"},
            {"flag": "-ProgressInterval", "kind": "int", "advanced": False,
             "help": "Progress print cadence"},
            {"flag": "-AppName", "kind": "str", "advanced": True},
            {"flag": "-KeepTemporaryApp", "kind": "toggle", "advanced": True},
            {"flag": "-MaxRetries", "kind": "int", "advanced": True},
            {"flag": "-MaxRetryDelaySeconds", "kind": "int", "advanced": True},
            {"flag": "-PermissionPropagationSeconds", "kind": "int", "advanced": True},
            {"flag": "-UseDeviceCode", "kind": "psbool", "advanced": True, "default": True,
             "help": "Use device-code auth (recommended in Cloud Shell)"},
        ],
        "token_args": [],
    },
    {
        "id": "github",
        "csp": None,
        "group": "code",
        "label": "Code — GitHub",
        "script": "code/github/active-developer-count-github.py",
        "runner": "python3",
        "auth": "token",
        "probe": ["github"],
        "pip": "PyGithub",
        "options": [
            {"flag": "--org", "kind": "str", "advanced": False,
             "help": "Organization to scan"},
            {"flag": "--repo", "kind": "str", "advanced": False,
             "help": "Single repository (owner/name)"},
            {"flag": "--url", "kind": "str", "advanced": False,
             "help": "GitHub Enterprise base URL"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output"},
            {"flag": "--max-workers", "kind": "int", "advanced": True},
            {"flag": "--progress-interval", "kind": "int", "advanced": True},
            {"flag": "--decrypt", "kind": "toggle", "advanced": True},
            {"flag": "--verbose", "kind": "toggle", "advanced": True},
            {"flag": "--debug", "kind": "toggle", "advanced": True},
        ],
        "token_args": [
            {"flag": "--token", "prompt": "GitHub token", "secret": True,
             "env": "GITHUB_TOKEN"},
        ],
    },
    {
        "id": "gitlab",
        "csp": None,
        "group": "code",
        "label": "Code — GitLab",
        "script": "code/gitlab/active-developer-count-gitlab.py",
        "runner": "python3",
        "auth": "token",
        "probe": ["gitlab"],
        "pip": "python-gitlab",
        "options": [
            {"flag": "--group", "kind": "str", "advanced": False,
             "help": "Group to scan"},
            {"flag": "--project", "kind": "str", "advanced": False,
             "help": "Single project"},
            {"flag": "--url", "kind": "str", "advanced": False,
             "help": "Self-managed GitLab base URL"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output"},
            {"flag": "--max-workers", "kind": "int", "advanced": True},
            {"flag": "--progress-interval", "kind": "int", "advanced": True},
            {"flag": "--decrypt", "kind": "toggle", "advanced": True},
            {"flag": "--verbose", "kind": "toggle", "advanced": True},
            {"flag": "--debug", "kind": "toggle", "advanced": True},
        ],
        "token_args": [
            {"flag": "--token", "prompt": "GitLab token", "secret": True,
             "env": "GITLAB_TOKEN"},
        ],
    },
    {
        "id": "ado",
        "csp": None,
        "group": "code",
        "label": "Code — Azure DevOps",
        "script": "code/azure-devops/active-developer-count-ado.py",
        "runner": "python3",
        "auth": "token",
        "probe": ["azure.devops"],
        "pip": "azure-devops",
        "options": [
            {"flag": "--proj", "kind": "str", "advanced": False,
             "help": "Project to scan"},
            {"flag": "--repo", "kind": "str", "advanced": False,
             "help": "Single repository"},
            {"flag": "--days", "kind": "int", "advanced": False,
             "help": "Look-back window in days"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output"},
            {"flag": "--mask-emails", "kind": "toggle", "advanced": True},
            {"flag": "--include-disabled", "kind": "toggle", "advanced": True},
            {"flag": "--include-empty-repositories", "kind": "toggle", "advanced": True},
            {"flag": "--project-page-size", "kind": "int", "advanced": True},
            {"flag": "--commit-page-size", "kind": "int", "advanced": True},
            {"flag": "--max-repositories", "kind": "int", "advanced": True},
            {"flag": "--max-commits-per-repo", "kind": "int", "advanced": True},
            {"flag": "--max-retries", "kind": "int", "advanced": True},
            {"flag": "--retry-delay", "kind": "int", "advanced": True},
            {"flag": "--max-run-minutes", "kind": "int", "advanced": True},
            {"flag": "--checkpoint-interval", "kind": "int", "advanced": True},
            {"flag": "--progress-interval", "kind": "int", "advanced": True},
            {"flag": "--fail-fast", "kind": "toggle", "advanced": True},
            {"flag": "--verbose", "kind": "toggle", "advanced": True},
        ],
        "token_args": [
            {"flag": "--org", "prompt": "Azure DevOps organization", "secret": False,
             "env": "AZURE_DEVOPS_ORG"},
            {"flag": "--token", "prompt": "Azure DevOps PAT", "secret": True,
             "env": "AZURE_DEVOPS_EXT_PAT"},
        ],
    },
]

CSP_LABELS = {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}

# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def leaf_by_id(leaf_id):
    for leaf in SCRIPTS:
        if leaf["id"] == leaf_id:
            return leaf
    return None


def resolve_script_path(leaf):
    return (SIZING_ROOT / leaf["script"]).resolve()


def script_exists(leaf):
    return resolve_script_path(leaf).is_file()


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

def detect_csp():
    """Return aws|azure|gcp|None for the CloudShell we're running in."""
    env = os.environ

    # AWS
    if "CloudShell" in env.get("AWS_EXECUTION_ENV", ""):
        return "aws"
    # GCP
    if env.get("CLOUD_SHELL") == "true":
        return "gcp"
    # Azure
    azure_signals = (env.get("AZUREPS_HOST_ENVIRONMENT", "") +
                     env.get("AZURE_HTTP_USER_AGENT", ""))
    if "cloud-shell" in azure_signals.lower():
        return "azure"

    # Backups
    if env.get("AWS_REGION") and (Path.home() / ".aws").exists():
        return "aws"
    if env.get("DEVSHELL_PROJECT_ID") or env.get("GOOGLE_CLOUD_PROJECT"):
        return "gcp"
    if any(k.startswith("ACC_") for k in env):
        return "azure"
    return None


# ---------------------------------------------------------------------------
# Command serialization
# ---------------------------------------------------------------------------

def default_value(opt):
    if "default" in opt:
        return opt["default"]
    if opt["kind"] in ("toggle",):
        return False
    if opt["kind"] == "psbool":
        return None
    return ""


def build_command(leaf, values, tokens=None):
    """Serialize a leaf + collected values into an argv list."""
    script = str(resolve_script_path(leaf))
    tokens = tokens or {}

    if leaf["runner"] == "pwsh":
        cmd = ["pwsh", "-File", script]
        for opt in leaf["options"]:
            flag = opt["flag"]
            val = values.get(flag, default_value(opt))
            kind = opt["kind"]
            if kind == "toggle":
                if val:
                    cmd.append(flag)
            elif kind == "psbool":
                if val is None:
                    continue
                cmd.append("%s:$%s" % (flag, "true" if val else "false"))
            else:
                if val not in (None, ""):
                    cmd.extend([flag, str(val)])
        return cmd

    # python runner
    cmd = ["python3", script]
    # token / required args first so they're easy to read
    for targ in leaf.get("token_args", []):
        val = tokens.get(targ["flag"])
        if val:
            cmd.extend([targ["flag"], str(val)])
    for opt in leaf["options"]:
        flag = opt["flag"]
        val = values.get(flag, default_value(opt))
        kind = opt["kind"]
        if kind == "toggle":
            if val:
                cmd.append(flag)
        else:
            if val not in (None, ""):
                cmd.extend([flag, str(val)])
    return cmd


def quote_command(cmd):
    if cmd and cmd[0] == "pwsh":
        # PowerShell-ish quoting: wrap anything with whitespace in single quotes.
        parts = []
        for tok in cmd:
            if tok and all(c.isalnum() or c in "-_./:$" for c in tok):
                parts.append(tok)
            else:
                parts.append("'%s'" % tok.replace("'", "''"))
        return " ".join(parts)
    return " ".join(shlex.quote(t) for t in cmd)


# ---------------------------------------------------------------------------
# Dependency preflight (runs in plain text mode)
# ---------------------------------------------------------------------------

def probe_ok(leaf):
    """Return (ok, detail). pwsh leaves check for pwsh on PATH."""
    if leaf["runner"] == "pwsh":
        if shutil.which("pwsh"):
            return True, ""
        return False, "pwsh-missing"
    if not leaf["probe"]:
        return True, ""
    importline = ", ".join(leaf["probe"])
    try:
        res = subprocess.run(
            [leaf["runner"], "-c", "import %s" % importline],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        return False, "runner-missing"
    return (res.returncode == 0), importline


def preflight(leaf):
    """Interactive (plain text) dependency check. Returns True to proceed."""
    ok, detail = probe_ok(leaf)
    if ok:
        return True

    if detail == "pwsh-missing":
        print("\n  Microsoft 365 sizing needs PowerShell (pwsh), which ships with")
        print("  Azure Cloud Shell but not AWS/GCP CloudShell.")
        print("  Install PowerShell 7+ or run this leaf from Azure Cloud Shell.")
        input("\n  Press Enter to return to the menu... ")
        return False
    if detail == "runner-missing":
        print("\n  Could not find '%s' on PATH." % leaf["runner"])
        input("\n  Press Enter to return to the menu... ")
        return False

    install = "pip3 install --upgrade %s" % leaf["pip"]
    print("\n  Missing Python dependency for this script.")
    print("  Probe failed importing: %s" % detail)
    print("\n  Suggested install:\n    %s" % install)
    print("\n  [i] Install now   [c] Copy & skip (run anyway)   [b] Back")
    choice = input("  Choose [i/c/b]: ").strip().lower()
    if choice == "i":
        pip_args = leaf["pip"].split()
        cmd = [leaf["runner"], "-m", "pip", "install", "--upgrade"] + pip_args
        print("\n  Running: %s\n" % " ".join(shlex.quote(c) for c in cmd))
        subprocess.run(cmd)
        ok, _ = probe_ok(leaf)
        if ok:
            print("\n  Dependency now importable. Continuing.")
            return True
        print("\n  Still cannot import after install.")
        again = input("  Continue anyway? [y/N]: ").strip().lower()
        return again == "y"
    if choice == "c":
        return True
    return False


# ---------------------------------------------------------------------------
# Token collection (plain text, masked)
# ---------------------------------------------------------------------------

def collect_tokens(leaf):
    """Prompt for token_args. Returns dict flag->value or None if cancelled."""
    import getpass
    tokens = {}
    for targ in leaf.get("token_args", []):
        flag = targ["flag"]
        env_name = targ.get("env")
        env_val = os.environ.get(env_name) if env_name else None
        if env_val:
            reuse = input("  Reuse %s from $%s? [Y/n]: "
                          % (targ["prompt"], env_name)).strip().lower()
            if reuse in ("", "y", "yes"):
                tokens[flag] = env_val
                continue
        prompt = "  %s: " % targ["prompt"]
        if targ.get("secret"):
            val = getpass.getpass(prompt)
        else:
            val = input(prompt).strip()
        if not val:
            print("  (required value, aborting this run)")
            return None
        tokens[flag] = val
    return tokens


# ---------------------------------------------------------------------------
# Execution (plain text)
# ---------------------------------------------------------------------------

def choose_cwd(leaf, values):
    """Pick a working directory from an output-dir option if present."""
    for opt in leaf["options"]:
        if opt["flag"] in ("--output-dir",):
            val = values.get(opt["flag"]) or opt.get("default")
            if val:
                p = Path(val).expanduser()
                if p.is_dir():
                    return str(p)
    return str(SIZING_ROOT)


def execute(leaf, cmd, values):
    cwd = choose_cwd(leaf, values)
    print("\n  Running in: %s\n" % cwd)
    print("  " + "-" * 60)
    try:
        res = subprocess.run(cmd, cwd=cwd)
        rc = res.returncode
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        rc = 130
    except FileNotFoundError as exc:
        print("\n  Failed to launch: %s" % exc)
        rc = 127
    print("  " + "-" * 60)
    print("\n  Exit code: %d" % rc)
    print("  Any output file was written under: %s" % cwd)
    return rc


# ---------------------------------------------------------------------------
# Auth banner
# ---------------------------------------------------------------------------

def auth_banner(leaf):
    if leaf["auth"] == "ambient":
        return "Using the CloudShell's existing credentials (ambient auth)."
    if leaf["auth"] == "token":
        return "This script requires a token; you'll be prompted (input masked)."
    if leaf["auth"] == "device-code":
        return "Auth via device-code flow handled by the script."
    return ""


# ===========================================================================
# Prompt (numbered input) frontend
# ===========================================================================

class PromptUI:
    """Numbered-menu fallback. Also the shared text layer used by curses."""

    @contextmanager
    def suspend(self):
        yield

    # -- menu navigation --------------------------------------------------
    def pick_leaf(self, csp):
        while True:
            if csp:
                leaf = self._csp_menu(csp)
            else:
                leaf = self._full_menu()
            if leaf == "SWITCH":
                csp = None
                continue
            return leaf  # leaf dict or None

    def _csp_menu(self, csp):
        leaves = [l for l in SCRIPTS if l["csp"] == csp]
        print("\n=== Wiz Sizing — %s ===" % CSP_LABELS.get(csp, csp))
        for i, leaf in enumerate(leaves, 1):
            print("  %d) %s" % (i, leaf["label"]))
        print("  s) Switch provider / category")
        print("  q) Quit")
        raw = input("Select: ").strip().lower()
        if raw == "q":
            return None
        if raw == "s":
            return "SWITCH"
        if raw.isdigit() and 1 <= int(raw) <= len(leaves):
            return leaves[int(raw) - 1]
        return self._csp_menu(csp)

    def _full_menu(self):
        groups = [
            ("Cloud — resource count", [l for l in SCRIPTS if l["group"] == "cloud"]),
            ("Defend — log volume", [l for l in SCRIPTS if l["group"] == "defend"]),
            ("SaaS", [l for l in SCRIPTS if l["group"] == "saas"]),
            ("Code", [l for l in SCRIPTS if l["group"] == "code"]),
        ]
        flat = []
        print("\n=== Wiz Sizing — all scripts ===")
        n = 1
        for title, leaves in groups:
            if not leaves:
                continue
            print("  -- %s --" % title)
            for leaf in leaves:
                print("    %d) %s" % (n, leaf["label"]))
                flat.append(leaf)
                n += 1
        print("  q) Quit")
        raw = input("Select: ").strip().lower()
        if raw == "q":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(flat):
            return flat[int(raw) - 1]
        return self._full_menu()

    # -- option collection ------------------------------------------------
    def collect_options(self, leaf):
        print("\n--- %s ---" % leaf["label"])
        print("  %s" % auth_banner(leaf))
        values = {}
        show_advanced = False
        opts = [o for o in leaf["options"] if not o["advanced"]]
        while True:
            print("\n  Options (Enter to accept default/skip):")
            for opt in opts:
                self._prompt_option(opt, values)
            if not show_advanced and any(o["advanced"] for o in leaf["options"]):
                more = input("\n  Show advanced options? [y/N]: ").strip().lower()
                if more == "y":
                    show_advanced = True
                    opts = [o for o in leaf["options"] if o["advanced"]]
                    continue
            break
        return values

    def _prompt_option(self, opt, values):
        flag = opt["flag"]
        kind = opt["kind"]
        helptext = (" — " + opt["help"]) if opt.get("help") else ""
        if kind == "toggle":
            cur = values.get(flag, opt.get("default", False))
            raw = input("    %s [on/off, default %s]%s: "
                        % (flag, "on" if cur else "off", helptext)).strip().lower()
            if raw in ("on", "y", "yes", "true", "1"):
                values[flag] = True
            elif raw in ("off", "n", "no", "false", "0"):
                values[flag] = False
        elif kind == "psbool":
            cur = values.get(flag, opt.get("default"))
            raw = input("    %s [true/false, default %s]%s: "
                        % (flag, str(cur).lower(), helptext)).strip().lower()
            if raw in ("true", "on", "yes", "1"):
                values[flag] = True
            elif raw in ("false", "off", "no", "0"):
                values[flag] = False
        else:
            default = opt.get("default", "")
            dshow = (" [default %s]" % default) if default else ""
            raw = input("    %s%s%s: " % (flag, dshow, helptext)).strip()
            if raw:
                values[flag] = raw
            elif default:
                values[flag] = default

    # -- confirm / run-another -------------------------------------------
    def confirm_command(self, leaf, cmd):
        print("\n  Command to run:\n")
        print("    " + quote_command(cmd))
        ans = input("\n  Run this now? [y/N]: ").strip().lower()
        return ans in ("y", "yes")

    def ask_run_another(self):
        ans = input("\n  [r] Run another   [q] Quit : ").strip().lower()
        return ans == "r"


# ===========================================================================
# Curses frontend
# ===========================================================================

class CursesUI:
    """Full-screen arrow-key menu. Delegates text-heavy steps to PromptUI by
    suspending curses so the shared plain-text flow handles them."""

    def __init__(self):
        import curses  # noqa: F401  (validated by caller before constructing)
        self._curses = curses
        self.stdscr = None
        self._prompt = PromptUI()

    def start(self):
        self.stdscr = self._curses.initscr()
        self._curses.noecho()
        self._curses.cbreak()
        self.stdscr.keypad(True)
        try:
            self._curses.curs_set(0)
        except self._curses.error:
            pass

    def stop(self):
        if self.stdscr is not None:
            self.stdscr.keypad(False)
            self._curses.nocbreak()
            self._curses.echo()
            self._curses.endwin()
            self.stdscr = None

    @contextmanager
    def suspend(self):
        self._curses.endwin()
        try:
            yield
        finally:
            self.stdscr = self._curses.initscr()
            self._curses.noecho()
            self._curses.cbreak()
            self.stdscr.keypad(True)
            try:
                self._curses.curs_set(0)
            except self._curses.error:
                pass
            self.stdscr.clear()

    # -- generic scrollable selector -------------------------------------
    def _select(self, title, rows, footer):
        """rows: list of (text, value). Returns chosen value or None (back)."""
        curses = self._curses
        idx = 0
        top = 0
        while True:
            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()
            self.stdscr.addnstr(0, 0, title, width - 1, curses.A_BOLD)
            body_h = height - 3
            if idx < top:
                top = idx
            if idx >= top + body_h:
                top = idx - body_h + 1
            for row_i in range(top, min(len(rows), top + body_h)):
                text = rows[row_i][0]
                y = 2 + (row_i - top)
                attr = curses.A_REVERSE if row_i == idx else curses.A_NORMAL
                self.stdscr.addnstr(y, 2, text.ljust(width - 4), width - 4, attr)
            self.stdscr.addnstr(height - 1, 0, footer, width - 1, curses.A_DIM)
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                idx = (idx - 1) % len(rows)
            elif key in (curses.KEY_DOWN, ord("j")):
                idx = (idx + 1) % len(rows)
            elif key in (curses.KEY_ENTER, 10, 13):
                return rows[idx][1]
            elif key in (27, ord("q")):       # ESC / q
                return None

    def pick_leaf(self, csp):
        while True:
            if csp:
                rows = [(l["label"], l) for l in SCRIPTS if l["csp"] == csp]
                rows.append(("» Switch provider / category", "SWITCH"))
                title = "Wiz Sizing — %s" % CSP_LABELS.get(csp, csp)
                footer = "↑/↓ move · Enter select · q quit"
                choice = self._select(title, rows, footer)
            else:
                rows = []
                for title_g, group in (("Cloud", "cloud"), ("Defend", "defend"),
                                       ("SaaS", "saas"), ("Code", "code")):
                    leaves = [l for l in SCRIPTS if l["group"] == group]
                    for leaf in leaves:
                        rows.append(("[%s] %s" % (title_g, leaf["label"]), leaf))
                choice = self._select("Wiz Sizing — all scripts", rows,
                                      "↑/↓ move · Enter select · q quit")
            if choice == "SWITCH":
                csp = None
                continue
            return choice  # leaf dict or None

    def collect_options(self, leaf):
        curses = self._curses
        values = {}
        show_advanced = False
        idx = 0
        top = 0
        while True:
            opts = [o for o in leaf["options"]
                    if (not o["advanced"]) or show_advanced]
            # control rows appended after options
            controls = []
            if any(o["advanced"] for o in leaf["options"]):
                controls.append(("ADV", "%s advanced options"
                                 % ("Hide" if show_advanced else "Show")))
            controls.append(("RUN", "▶ Continue / run"))
            controls.append(("BACK", "‹ Back to menu"))
            total = len(opts) + len(controls)
            idx = max(0, min(idx, total - 1))

            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()
            self.stdscr.addnstr(0, 0, leaf["label"], width - 1, curses.A_BOLD)
            self.stdscr.addnstr(1, 0, auth_banner(leaf), width - 1, curses.A_DIM)
            body_h = height - 4
            if idx < top:
                top = idx
            if idx >= top + body_h:
                top = idx - body_h + 1

            def render_row(i):
                if i < len(opts):
                    opt = opts[i]
                    return self._option_row(opt, values, width)
                ctl = controls[i - len(opts)]
                return ctl[1]

            for i in range(top, min(total, top + body_h)):
                y = 3 + (i - top)
                attr = curses.A_REVERSE if i == idx else curses.A_NORMAL
                self.stdscr.addnstr(y, 2, render_row(i).ljust(width - 4),
                                    width - 4, attr)
            self.stdscr.addnstr(height - 1, 0,
                                "↑/↓ move · Enter edit/toggle · q back",
                                width - 1, curses.A_DIM)
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                idx = (idx - 1) % total
            elif key in (curses.KEY_DOWN, ord("j")):
                idx = (idx + 1) % total
            elif key in (27, ord("q")):
                return None
            elif key in (curses.KEY_ENTER, 10, 13):
                if idx < len(opts):
                    self._edit_option(opts[idx], values)
                else:
                    ctl = controls[idx - len(opts)][0]
                    if ctl == "ADV":
                        show_advanced = not show_advanced
                        idx = 0
                        top = 0
                    elif ctl == "RUN":
                        return values
                    elif ctl == "BACK":
                        return None

    def _option_row(self, opt, values, width):
        flag = opt["flag"]
        kind = opt["kind"]
        if kind == "toggle":
            cur = values.get(flag, opt.get("default", False))
            state = "[x]" if cur else "[ ]"
            return "%s %s" % (state, flag)
        if kind == "psbool":
            cur = values.get(flag, opt.get("default"))
            return "%s = $%s" % (flag, str(cur).lower())
        cur = values.get(flag, opt.get("default", ""))
        shown = cur if cur != "" else "(unset)"
        return "%s = %s" % (flag, shown)

    def _edit_option(self, opt, values):
        flag = opt["flag"]
        kind = opt["kind"]
        if kind == "toggle":
            cur = values.get(flag, opt.get("default", False))
            values[flag] = not cur
            return
        if kind == "psbool":
            cur = values.get(flag, opt.get("default"))
            values[flag] = not bool(cur)
            return
        # text entry: drop to an echoed line at the bottom of the screen
        curses = self._curses
        height, width = self.stdscr.getmaxyx()
        prompt = "  %s = " % flag
        self.stdscr.addnstr(height - 2, 0, " " * (width - 1), width - 1)
        self.stdscr.addnstr(height - 2, 0, prompt, width - 1, curses.A_BOLD)
        self.stdscr.refresh()
        curses.echo()
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        try:
            raw = self.stdscr.getstr(height - 2, len(prompt), 256)
        finally:
            curses.noecho()
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        text = raw.decode("utf-8", "replace").strip()
        if text:
            values[flag] = text
        elif flag in values:
            del values[flag]

    # confirm / run-another delegate to plain text under suspend()
    def confirm_command(self, leaf, cmd):
        with self.suspend():
            return self._prompt.confirm_command(leaf, cmd)

    def ask_run_another(self):
        with self.suspend():
            return self._prompt.ask_run_another()


# ===========================================================================
# Session driver (shared by both frontends)
# ===========================================================================

def run_session(frontend, csp):
    while True:
        leaf = frontend.pick_leaf(csp)
        if leaf is None:
            return

        if not script_exists(leaf):
            with frontend.suspend():
                print("\n  Script not found: %s" % resolve_script_path(leaf))
                print("  Get the sizing scripts from: %s" % ORIGIN_URL)
                print("  e.g.  %s" % REPO_HINT)
                input("\n  Press Enter to return to the menu... ")
            continue

        values = frontend.collect_options(leaf)
        if values is None:
            continue

        # everything below runs in plain text (curses suspended)
        with frontend.suspend():
            tokens = collect_tokens(leaf)
            if tokens is None:
                continue
            if not preflight(leaf):
                continue
            cmd = build_command(leaf, values, tokens)

        if not frontend.confirm_command(leaf, cmd):
            continue

        with frontend.suspend():
            execute(leaf, cmd, values)

        if not frontend.ask_run_another():
            return


# ===========================================================================
# Non-interactive helpers (--list, --dry-run --leaf)
# ===========================================================================

def cmd_list():
    print("Wiz Sizing — manifest leaves:\n")
    for leaf in SCRIPTS:
        mark = "" if script_exists(leaf) else "  (script missing)"
        print("  %-12s %-30s %s%s"
              % (leaf["id"], leaf["label"], leaf["script"], mark))


def cmd_dry_run_leaf(leaf_id):
    leaf = leaf_by_id(leaf_id)
    if leaf is None:
        print("Unknown leaf id: %s" % leaf_id, file=sys.stderr)
        return 2
    cmd = build_command(leaf, {})
    print(quote_command(cmd))
    return 0


# ===========================================================================
# Entry point
# ===========================================================================

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Interactive launcher for the Wiz sizing scripts.")
    parser.add_argument("--csp", choices=["aws", "azure", "gcp"],
                        help="Force a provider's submenu (overrides detection).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build and print the command; never execute.")
    parser.add_argument("--list", action="store_true",
                        help="Print the manifest leaves and exit.")
    parser.add_argument("--no-curses", action="store_true",
                        help="Force the numbered-prompt fallback UI.")
    parser.add_argument("--leaf", metavar="ID",
                        help="With --dry-run: print one leaf's default command.")
    args = parser.parse_args(argv)

    if args.list:
        cmd_list()
        return 0

    if args.leaf:
        # default-command dump, honoring --dry-run as the print-only mode
        return cmd_dry_run_leaf(args.leaf)

    csp = args.csp or detect_csp()

    # In dry-run interactive mode, swap execute() for a print-only shim.
    if args.dry_run:
        _install_dry_run()

    # Choose a frontend.
    use_curses = (not args.no_curses) and sys.stdin.isatty() and sys.stdout.isatty()
    frontend = None
    if use_curses:
        try:
            import curses  # noqa: F401
            frontend = CursesUI()
            frontend.start()
        except Exception:
            frontend = None
    if frontend is None:
        frontend = PromptUI()

    try:
        run_session(frontend, csp)
    finally:
        if isinstance(frontend, CursesUI):
            frontend.stop()
    print("\nDone.")
    return 0


def _install_dry_run():
    """Replace execute() with a print-only version for --dry-run sessions."""
    global execute

    def _dry_execute(leaf, cmd, values):
        print("\n  [dry-run] Would run:")
        print("    " + quote_command(cmd))
        print("  [dry-run] In: %s" % choose_cwd(leaf, values))
        return 0

    execute = _dry_execute


if __name__ == "__main__":
    sys.exit(main())
