#!/usr/bin/env python3
"""Wiz Sizing — Azure (self-contained, curl-able).

Bundles the Azure sizing modes into one file you can drop into Azure Cloud Shell:

  * Azure Cloud      — resource count
  * Azure Defend     — log-volume estimation
  * Azure DevOps     — active developer count

It also drives Microsoft 365 sizing (wiz-365.ps1) from its profiles.

One-line bootstrap (Azure Cloud Shell):
  curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-azure.py -o wiz-azure.py && python3 wiz-azure.py

Run with no arguments for the interactive menu, or:
  python3 wiz-azure.py --list
  python3 wiz-azure.py --mode azure-cloud --dry-run
  python3 wiz-azure.py --profile azure-recommended

The cloud scanning logic is the original standalone sizing scripts, embedded
verbatim and run in-process, so the CSV output is byte-identical to those.
"""

FILE_TITLE = "Wiz Sizing — Azure"
FILE_BASENAME = "wiz-azure.py"
ONELINER = ("curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-azure.py "
            "-o wiz-azure.py && python3 wiz-azure.py")

M365_ONELINER = ("curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-365.ps1 "
                 "-o wiz-365.ps1 && pwsh ./wiz-365.ps1")

MODES = [
    {
        "id": "azure-cloud",
        "label": "Azure — Cloud resource count",
        "runner": "python3",
        "blob": "AZURE_CLOUD",
        "auth": "ambient",
        "probe": ["azure.mgmt.resourcegraph", "azure.identity"],
        "pip": "azure-identity azure-mgmt-resource azure-mgmt-resourcegraph "
               "azure-mgmt-subscription azure-mgmt-compute",
        "options": [
            {"flag": "--all", "kind": "toggle", "advanced": False,
             "help": "Count resources in ALL subscriptions in the current Management Group"},
            {"flag": "--data", "kind": "toggle", "advanced": False,
             "help": "Include Cloud Data Security resources (buckets, databases, …)"},
            {"flag": "--images", "kind": "toggle", "advanced": False,
             "help": "Include registry container images"},
            {"flag": "--subscriptions", "kind": "idfile", "advanced": False,
             "idfile": "subscriptions.txt",
             "help": "Limit to specific subscription IDs (comma/space list → subscriptions.txt)"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output CSV"},
            {"flag": "--graph", "kind": "toggle", "advanced": True,
             "help": "Use Resource Graph queries"},
            {"flag": "--id", "kind": "str", "advanced": True,
             "help": "Scan only this single subscription ID"},
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
        "label": "Azure — Defend log volume",
        "runner": "python3",
        "blob": "AZURE_DEFEND",
        "auth": "ambient",
        "probe": ["azure.identity", "azure.monitor.query", "requests"],
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
        "id": "azure-devops",
        "label": "Azure DevOps — developer count",
        "runner": "python3",
        "blob": "AZURE_DEVOPS",
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
             "env": "AZURE_DEVOPS_ORG", "detect": "ado_org"},
            {"flag": "--token", "prompt": "Azure DevOps PAT", "secret": True,
             "env": "ADO_TOKEN"},
        ],
    },
    {
        "id": "m365",
        "label": "Microsoft 365 — sizing (PowerShell)",
        "runner": "pwsh",
        "ps_file": "wiz-365.ps1",
        "oneliner": M365_ONELINER,
        "hidden": True,
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
]

PROFILES = [
    {
        "id": "azure-recommended",
        "label": ("★ Recommended full sweep — Azure Cloud + Defend (tenant-wide), "
                  "then offer Azure DevOps + Microsoft 365"),
        "confirm_detect": "azure_tenant",
        "steps": [
            {"mode": "azure-cloud",
             "values": {"--all": True, "--data": True, "--images": True}},
            {"mode": "azure-defend", "values": {"--all-subscriptions": True}},
        ],
        "optins": ["azure-devops", "m365"],
    },
    {
        "id": "azure-microsoft",
        "label": ("★ All Microsoft estate — Cloud + Defend → Azure DevOps → "
                  "Microsoft 365 (committed steps)"),
        "confirm_detect": "azure_tenant",
        "steps": [
            {"mode": "azure-cloud",
             "values": {"--all": True, "--data": True, "--images": True}},
            {"mode": "azure-defend", "values": {"--all-subscriptions": True}},
            {"mode": "azure-devops", "values": {}},
            {"mode": "m365", "values": {}},
        ],
        "optins": [],
    },
]

# ===========================================================================
# Shared scaffolding (engine) — identical across every wiz-<csp>.py
# ===========================================================================
# This block is appended verbatim to each generated wiz-*.py by tools/build_wiz.py.
# It is pure Python standard library. It drives a numbered/curses menu, handles
# on-demand dependency install, masked tokens, scope idfiles, and one-confirmation
# profiles, then runs the chosen mode's *embedded* legacy source IN-PROCESS so the
# CSV output is byte-identical to the original standalone script.
#
# Per-file globals expected to be defined ABOVE this block:
#   FILE_TITLE     str   e.g. "Wiz Sizing — Azure"
#   FILE_BASENAME  str   e.g. "wiz-azure.py"
#   ONELINER       str   the curl bootstrap for this file (shown in --help/docs)
#   MODES          list  mode dicts (see build_wiz.py for the schema)
#   PROFILES       list  profile dicts
# And BELOW this block (generated):
#   BLOBS          dict  blob-key -> gzip+base64 of the verbatim legacy source

import argparse
import base64
import getpass
import gzip
import importlib.util
import os
import shlex
import shutil
import signal
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

SELF_PATH = Path(__file__).resolve()
SELF_DIR = SELF_PATH.parent

# Set by --dry-run: never execute, just print what would run.
DRY_RUN = False


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------
def mode_by_id(mode_id):
    for mode in MODES:
        if mode["id"] == mode_id:
            return mode
    return None


def profile_by_id(profile_id):
    for profile in PROFILES:
        if profile["id"] == profile_id:
            return profile
    return None


# ---------------------------------------------------------------------------
# Scope-identity auto-detection (best-effort; never blocks)
# ---------------------------------------------------------------------------
def _run_capture(cmd, timeout=8):
    """Run a command, return stripped stdout or None on any failure."""
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode != 0:
        return None
    out = res.stdout.decode("utf-8", "replace").strip()
    return out or None


def detect_gcp_org():
    out = _run_capture(["gcloud", "organizations", "list",
                        "--format=value(ID)", "--limit=1"])
    return out.splitlines()[0].strip() if out else None


def detect_azure_tenant():
    out = _run_capture(["az", "account", "show", "--query", "tenantId", "-o", "tsv"])
    return out.splitlines()[0].strip() if out else None


def detect_ado_org():
    env_org = os.environ.get("AZURE_DEVOPS_ORG")
    if env_org:
        return env_org.strip()
    out = _run_capture(["az", "devops", "configure", "--list"])
    if not out:
        return None
    for line in out.splitlines():
        if line.strip().startswith("organization"):
            _, _, val = line.partition("=")
            val = val.strip().rstrip("/")
            if val:
                return val.rsplit("/", 1)[-1] if "/" in val else val
    return None


DETECTORS = {
    "gcp_org": detect_gcp_org,
    "azure_tenant": detect_azure_tenant,
    "ado_org": detect_ado_org,
}


# ---------------------------------------------------------------------------
# Value / command serialization
# ---------------------------------------------------------------------------
def default_value(opt):
    if "default" in opt:
        return opt["default"]
    if opt["kind"] == "toggle":
        return False
    if opt["kind"] == "psbool":
        return None
    return ""


def parse_id_list(raw):
    """Split a comma/space/newline separated id list into clean tokens."""
    if not raw:
        return []
    tokens = []
    for chunk in str(raw).replace(",", " ").split():
        chunk = chunk.strip()
        if chunk:
            tokens.append(chunk)
    return tokens


def idfile_plan(mode, values):
    """Return [(filename, [ids]), ...] for idfile options with a value set."""
    plan = []
    for opt in mode["options"]:
        if opt["kind"] != "idfile":
            continue
        ids = parse_id_list(values.get(opt["flag"], ""))
        if ids:
            plan.append((opt["idfile"], ids))
    return plan


def materialize_idfiles(mode, values, cwd):
    """Write the idfile .txt files into cwd. Returns the written paths."""
    written = []
    for filename, ids in idfile_plan(mode, values):
        path = Path(cwd) / filename
        path.write_text("\n".join(ids) + "\n", encoding="utf-8")
        written.append(str(path))
    return written


def build_argv(mode, values, tokens=None):
    """Serialize a mode + collected values into the embedded script's argv."""
    tokens = tokens or {}
    cmd = []
    for targ in mode.get("token_args", []):
        val = tokens.get(targ["flag"])
        if val:
            cmd.extend([targ["flag"], str(val)])
    for opt in mode["options"]:
        flag = opt["flag"]
        kind = opt["kind"]
        val = values.get(flag, default_value(opt))
        if kind == "toggle":
            if val:
                cmd.append(flag)
        elif kind == "psbool":
            if val is None:
                continue
            cmd.append("%s:$%s" % (flag, "true" if val else "false"))
        elif kind == "idfile":
            # bare toggle; the IDs go into a sibling .txt file (see idfile_plan)
            if parse_id_list(val):
                cmd.append(flag)
        else:
            if val not in (None, ""):
                cmd.extend([flag, str(val)])
    return cmd


def _mask_tokens(mode, tokens):
    if not tokens:
        return tokens
    masked = dict(tokens)
    for targ in mode.get("token_args", []):
        if targ.get("secret") and masked.get(targ["flag"]):
            masked[targ["flag"]] = "***"
    return masked


def quote_command(cmd):
    if cmd and cmd[0] == "pwsh":
        parts = []
        for tok in cmd:
            if tok and all(c.isalnum() or c in "-_./:$" for c in tok):
                parts.append(tok)
            else:
                parts.append("'%s'" % tok.replace("'", "''"))
        return " ".join(parts)
    return " ".join(shlex.quote(t) for t in cmd)


def preview_command(mode, values, tokens=None, extra_argv=None):
    """A copy-pasteable command line that reproduces this run."""
    argv = build_argv(mode, values, _mask_tokens(mode, tokens)) + list(extra_argv or [])
    if mode["runner"] == "pwsh":
        return quote_command(["pwsh", "-File", mode.get("ps_file", "")] + argv)
    base = ["python3", FILE_BASENAME, "--mode", mode["id"]]
    if argv:
        base.append("--")
    return quote_command(base + argv)


# ---------------------------------------------------------------------------
# Dependency preflight
# ---------------------------------------------------------------------------
def probe_ok(mode):
    """Return (ok, detail). pwsh modes check for pwsh on PATH."""
    if mode["runner"] == "pwsh":
        return (True, "") if shutil.which("pwsh") else (False, "pwsh-missing")
    missing = []
    for name in mode.get("probe", []):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError, ModuleNotFoundError):
            spec = None
        if spec is None:
            missing.append(name)
    if missing:
        return (False, ", ".join(missing))
    return (True, "")


def preflight(mode):
    """Interactive dependency check. Returns True to proceed."""
    ok, detail = probe_ok(mode)
    if ok:
        return True
    if detail == "pwsh-missing":
        print("\n  Microsoft 365 sizing needs PowerShell (pwsh), which ships with")
        print("  Azure Cloud Shell. Install PowerShell 7+ or run it there.")
        input("\n  Press Enter to return to the menu... ")
        return False

    install = "pip3 install --upgrade %s" % mode["pip"]
    print("\n  Missing Python dependency for this mode.")
    print("  Could not import: %s" % detail)
    print("\n  Suggested install:\n    %s" % install)
    print("\n  [i] Install now   [c] Continue anyway   [b] Back")
    choice = input("  Choose [i/c/b]: ").strip().lower()
    if choice == "i":
        pip_args = mode["pip"].split()
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + pip_args
        print("\n  Running: %s\n" % " ".join(shlex.quote(c) for c in cmd))
        subprocess.run(cmd)
        importlib.invalidate_caches()
        ok, _ = probe_ok(mode)
        if ok:
            print("\n  Dependency now importable. Continuing.")
            return True
        again = input("  Still not importable. Continue anyway? [y/N]: ").strip().lower()
        return again == "y"
    if choice == "c":
        return True
    return False


# ---------------------------------------------------------------------------
# Token collection (masked)
# ---------------------------------------------------------------------------
def collect_tokens(mode):
    """Prompt for token_args. Returns dict flag->value or None if cancelled."""
    tokens = {}
    for targ in mode.get("token_args", []):
        flag = targ["flag"]
        env_name = targ.get("env")
        env_val = os.environ.get(env_name) if env_name else None
        if env_val:
            reuse = input("  Reuse %s from $%s? [Y/n]: "
                          % (targ["prompt"], env_name)).strip().lower()
            if reuse in ("", "y", "yes"):
                tokens[flag] = env_val
                continue
        suggested = ""
        if targ.get("detect") and not targ.get("secret"):
            detector = DETECTORS.get(targ["detect"])
            if detector:
                suggested = detector() or ""
        if suggested:
            ans = input("  %s [detected: %s]: " % (targ["prompt"], suggested)).strip()
            tokens[flag] = ans or suggested
            continue
        prompt = "  %s: " % targ["prompt"]
        val = getpass.getpass(prompt) if targ.get("secret") else input(prompt).strip()
        if not val:
            print("  (required value, aborting this run)")
            return None
        tokens[flag] = val
    return tokens


# ---------------------------------------------------------------------------
# Execution — in-process for python modes, subprocess for pwsh
# ---------------------------------------------------------------------------
def run_cwd():
    """Directory the embedded scanner runs in (where scope idfiles are read)."""
    return os.getcwd()


def output_location(mode, values):
    """Resolved directory the chosen mode writes its CSV to (for reporting only).

    The embedded scanners own --output-dir themselves (they makedirs + join on
    it), so the engine does NOT chdir into it — doing so would double-apply a
    relative path (e.g. out/ -> out/out/). This is used only for the post-run
    message so the operator sees where the CSV actually landed.
    """
    for opt in mode["options"]:
        if opt["flag"] == "--output-dir":
            val = values.get(opt["flag"]) or opt.get("default") or "."
            return str(Path.cwd() / Path(val).expanduser())
    return os.getcwd()


def decode_blob(blob_key):
    """Return the verbatim legacy source for a blob key."""
    return gzip.decompress(base64.b64decode(BLOBS[blob_key])).decode("utf-8")


def _run_embedded(blob_key, argv, cwd):
    """Run an embedded legacy script in-process, exactly as if invoked directly.

    sys.argv, cwd and the SIGINT handler are saved/restored so the menu survives.
    """
    src = decode_blob(blob_key)
    old_argv = sys.argv[:]
    old_cwd = os.getcwd()
    old_sigint = signal.getsignal(signal.SIGINT)
    sys.argv = [FILE_BASENAME] + list(argv)
    namespace = {
        "__name__": "__main__",
        "__file__": os.path.join(cwd or old_cwd, FILE_BASENAME),
    }
    try:
        if cwd:
            os.chdir(cwd)
        exec(compile(src, "<%s>" % blob_key, "exec"), namespace)
        return 0
    except SystemExit as exc:
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, int) else 1
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        return 130
    finally:
        signal.signal(signal.SIGINT, old_sigint)
        sys.argv = old_argv
        os.chdir(old_cwd)


def _resolve_ps_file(mode):
    name = mode.get("ps_file")
    if not name:
        return None
    for cand in (SELF_DIR / name, Path.cwd() / name):
        if cand.is_file():
            return str(cand)
    return None


def _run_pwsh(mode, values, cwd, extra_argv=None):
    ps_file = _resolve_ps_file(mode)
    if not ps_file:
        print("\n  Microsoft 365 sizing runs in PowerShell. Fetch and run it with:")
        print("    " + mode.get("oneliner", ""))
        return 1
    argv = build_argv(mode, values) + list(extra_argv or [])
    cmd = ["pwsh", "-File", ps_file] + argv
    print("\n  Running: %s\n" % quote_command(cmd))
    try:
        return subprocess.run(cmd, cwd=cwd).returncode
    except FileNotFoundError:
        print("  pwsh not found on PATH.")
        return 127


def _dry(mode, values, tokens, cwd, extra_argv=None):
    print("\n  [dry-run] Would run:")
    print("    " + preview_command(mode, values, tokens, extra_argv))
    print("  [dry-run] In: %s" % cwd)
    for filename, ids in idfile_plan(mode, values):
        print("  [dry-run] Would write %s: %s"
              % (str(Path(cwd) / filename), ", ".join(ids)))
    return 0


def run_mode(mode, values, tokens=None, extra_argv=None):
    cwd = run_cwd()
    if DRY_RUN:
        return _dry(mode, values, tokens, cwd, extra_argv)
    if mode["runner"] == "pwsh":
        return _run_pwsh(mode, values, cwd, extra_argv)
    for path in materialize_idfiles(mode, values, cwd):
        print("  Wrote scope file: %s" % path)
    argv = build_argv(mode, values, tokens) + list(extra_argv or [])
    print("\n  Running %s in: %s" % (mode["label"], cwd))
    print("  " + "-" * 60)
    rc = _run_embedded(mode["blob"], argv, cwd)
    print("  " + "-" * 60)
    print("  Exit code: %s" % rc)
    print("  Output written under: %s" % output_location(mode, values))
    return rc


def auth_banner(mode):
    auth = mode.get("auth")
    if auth == "ambient":
        return "Using the CloudShell's existing credentials (ambient auth)."
    if auth == "token":
        return "This mode requires a token; you'll be prompted (input masked)."
    if auth == "device-code":
        return "Auth via device-code flow handled by the script."
    return ""


# ===========================================================================
# Numbered-prompt frontend (default; robust over web terminals)
# ===========================================================================
class PromptUI:
    @contextmanager
    def suspend(self):
        yield

    def pick(self):
        while True:
            print("\n=== %s ===" % FILE_TITLE)
            rows = []
            n = 1
            for profile in PROFILES:
                rows.append(("profile", profile))
                print("  %d) %s" % (n, profile["label"]))
                n += 1
            for mode in MODES:
                if mode.get("hidden"):
                    continue
                rows.append(("mode", mode))
                print("  %d) %s" % (n, mode["label"]))
                n += 1
            print("  q) Quit")
            raw = input("Select: ").strip().lower()
            if raw == "q":
                return None
            if raw.isdigit() and 1 <= int(raw) <= len(rows):
                return rows[int(raw) - 1]

    def collect_options(self, mode):
        print("\n--- %s ---" % mode["label"])
        print("  %s" % auth_banner(mode))
        values = {}
        show_advanced = False
        opts = [o for o in mode["options"] if not o["advanced"]]
        while True:
            if opts:
                print("\n  Options (Enter to accept default/skip):")
            for opt in opts:
                self._prompt_option(opt, values)
            if not show_advanced and any(o["advanced"] for o in mode["options"]):
                more = input("\n  Show advanced options? [y/N]: ").strip().lower()
                if more == "y":
                    show_advanced = True
                    opts = [o for o in mode["options"] if o["advanced"]]
                    continue
            break
        return values

    def _prompt_option(self, opt, values):
        flag = opt["flag"]
        kind = opt["kind"]
        helptext = (" — " + opt["help"]) if opt.get("help") else ""
        if kind in ("toggle", "psbool"):
            cur = values.get(flag, opt.get("default", False))
            raw = input("    %s [on/off, default %s]%s: "
                        % (flag, "on" if cur else "off", helptext)).strip().lower()
            if raw in ("on", "y", "yes", "true", "1"):
                values[flag] = True
            elif raw in ("off", "n", "no", "false", "0"):
                values[flag] = False
        else:
            default = opt.get("default", "")
            dshow = (" [default %s]" % default) if default else ""
            raw = input("    %s%s%s: " % (flag, dshow, helptext)).strip()
            if raw:
                values[flag] = raw
            elif default:
                values[flag] = default

    def confirm_command(self, mode, values, tokens=None):
        print("\n  Command to run:\n")
        print("    " + preview_command(mode, values, tokens))
        for filename, ids in idfile_plan(mode, values):
            print("    (writes %s: %s)" % (filename, ", ".join(ids)))
        ans = input("\n  Run this now? [Y/n]: ").strip().lower()
        return ans in ("", "y", "yes")

    def ask_run_another(self):
        ans = input("\n  [r] Run another   [q] Quit : ").strip().lower()
        return ans == "r"


# ===========================================================================
# Curses frontend (arrow-key menu; better UX where a real TTY exists)
# ===========================================================================
class CursesUI:
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

    def _select(self, title, rows, footer):
        curses = self._curses
        idx, top = 0, 0
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
                y = 2 + (row_i - top)
                attr = curses.A_REVERSE if row_i == idx else curses.A_NORMAL
                self.stdscr.addnstr(y, 2, rows[row_i][0].ljust(width - 4),
                                    width - 4, attr)
            self.stdscr.addnstr(height - 1, 0, footer, width - 1, curses.A_DIM)
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                idx = (idx - 1) % len(rows)
            elif key in (curses.KEY_DOWN, ord("j")):
                idx = (idx + 1) % len(rows)
            elif key in (curses.KEY_ENTER, 10, 13):
                return rows[idx][1]
            elif key in (27, ord("q")):
                return None

    def pick(self):
        rows = []
        for profile in PROFILES:
            rows.append((profile["label"], ("profile", profile)))
        for mode in MODES:
            if mode.get("hidden"):
                continue
            rows.append((mode["label"], ("mode", mode)))
        return self._select(FILE_TITLE, rows, "↑/↓ move · Enter select · q quit")

    def collect_options(self, mode):
        curses = self._curses
        values = {}
        show_advanced = False
        idx, top = 0, 0
        while True:
            opts = [o for o in mode["options"]
                    if (not o["advanced"]) or show_advanced]
            controls = []
            if any(o["advanced"] for o in mode["options"]):
                controls.append(("ADV", "%s advanced options"
                                 % ("Hide" if show_advanced else "Show")))
            controls.append(("RUN", "▶ Continue / run"))
            controls.append(("BACK", "‹ Back to menu"))
            total = len(opts) + len(controls)
            idx = max(0, min(idx, total - 1))

            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()
            self.stdscr.addnstr(0, 0, mode["label"], width - 1, curses.A_BOLD)
            self.stdscr.addnstr(1, 0, auth_banner(mode), width - 1, curses.A_DIM)
            body_h = height - 4
            if idx < top:
                top = idx
            if idx >= top + body_h:
                top = idx - body_h + 1

            def render_row(i):
                if i < len(opts):
                    return self._option_row(opts[i], values)
                return controls[i - len(opts)][1]

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
                        idx = top = 0
                    elif ctl == "RUN":
                        return values
                    elif ctl == "BACK":
                        return None

    def _option_row(self, opt, values):
        flag = opt["flag"]
        if opt["kind"] in ("toggle", "psbool"):
            cur = values.get(flag, opt.get("default", False))
            return "%s %s" % ("[x]" if cur else "[ ]", flag)
        cur = values.get(flag, opt.get("default", ""))
        return "%s = %s" % (flag, cur if cur != "" else "(unset)")

    def _edit_option(self, opt, values):
        flag = opt["flag"]
        if opt["kind"] in ("toggle", "psbool"):
            values[flag] = not values.get(flag, opt.get("default", False))
            return
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

    def confirm_command(self, mode, values, tokens=None):
        with self.suspend():
            return self._prompt.confirm_command(mode, values, tokens)

    def ask_run_another(self):
        with self.suspend():
            return self._prompt.ask_run_another()


# ===========================================================================
# Profile runner (one-confirmation sweeps)
# ===========================================================================
def _resolve_profile_steps(profile):
    steps = []
    for step in profile["steps"]:
        mode = mode_by_id(step["mode"])
        if mode is None:
            continue
        values = dict(step.get("values", {}))
        skip = False
        for det_key, flag in step.get("detect", {}).items():
            detector = DETECTORS.get(det_key)
            detected = detector() if detector else None
            if not detected:
                detected = input(
                    "  Could not auto-detect %s for %s.\n"
                    "  Enter %s value (blank to skip this step): "
                    % (det_key.replace("_", " "), mode["label"], flag)).strip()
            if detected:
                values[flag] = detected
            else:
                print("  Skipping %s — no %s available." % (mode["label"], flag))
                skip = True
        if not skip:
            steps.append((mode, values))
    return steps


def _offer_profile_optins(profile):
    text = PromptUI()
    for mode_id in profile.get("optins", []):
        mode = mode_by_id(mode_id)
        if mode is None:
            continue
        ans = input("\n  Also size %s? [y/N]: " % mode["label"]).strip().lower()
        if ans not in ("y", "yes"):
            continue
        if mode["runner"] == "pwsh":
            run_mode(mode, {})
            continue
        values = text.collect_options(mode)
        if values is None:
            continue
        tokens = collect_tokens(mode)
        if tokens is None:
            continue
        if not DRY_RUN and not preflight(mode):
            continue
        run_mode(mode, values, tokens)


def run_profile(frontend, profile):
    with frontend.suspend():
        print("\n" + "=" * 64)
        print("  %s" % profile["label"])
        print("=" * 64)
        if profile.get("confirm_detect"):
            detector = DETECTORS.get(profile["confirm_detect"])
            ident = detector() if detector else None
            name = profile["confirm_detect"].replace("_", " ")
            if ident:
                print("  Detected %s: %s" % (name, ident))
            else:
                print("  Could not auto-detect %s; ambient scope will be used." % name)

        steps = _resolve_profile_steps(profile)
        if not steps:
            print("\n  No runnable steps. Returning to menu.")
            input("  Press Enter to continue... ")
            return

        print("\n  This will run %d step(s) in order:" % len(steps))
        for i, (mode, values) in enumerate(steps, 1):
            print("\n   %d) %s" % (i, mode["label"]))
            print("      %s" % preview_command(mode, values))
            for filename, ids in idfile_plan(mode, values):
                print("      (writes %s: %s)" % (filename, ", ".join(ids)))

        ans = input("\n  Run all of the above now? [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("  Cancelled.")
            return

        for i, (mode, values) in enumerate(steps, 1):
            print("\n  --- Step %d/%d: %s ---" % (i, len(steps), mode["label"]))
            if mode["runner"] == "pwsh":
                run_mode(mode, values)
                continue
            tokens = None
            if mode.get("token_args"):
                tokens = collect_tokens(mode)
                if tokens is None:
                    print("  Skipping %s — no token provided." % mode["label"])
                    continue
            if not DRY_RUN and not preflight(mode):
                print("  Skipping %s — dependency not satisfied." % mode["label"])
                continue
            run_mode(mode, values, tokens)

        _offer_profile_optins(profile)
        input("\n  Sweep complete. Press Enter to return to the menu... ")


# ===========================================================================
# Session driver
# ===========================================================================
def run_session(frontend):
    while True:
        sel = frontend.pick()
        if sel is None:
            return
        kind, obj = sel
        if kind == "profile":
            run_profile(frontend, obj)
            continue
        mode = obj
        values = frontend.collect_options(mode)
        if values is None:
            continue
        with frontend.suspend():
            tokens = collect_tokens(mode)
            if tokens is None:
                continue
            if not preflight(mode):
                continue
        if not frontend.confirm_command(mode, values, tokens):
            continue
        with frontend.suspend():
            run_mode(mode, values, tokens)
        if not frontend.ask_run_another():
            return


# ===========================================================================
# Non-interactive helpers
# ===========================================================================
def cmd_list():
    print("%s\n" % FILE_TITLE)
    print("Modes (run with --mode <id>):")
    for mode in MODES:
        print("  %-14s %s" % (mode["id"], mode["label"]))
    if PROFILES:
        print("\nProfiles (run with --profile <id>):")
        for profile in PROFILES:
            print("  %-18s %s" % (profile["id"], profile["label"]))


def _parse_set_values(mode, set_args):
    kinds = {o["flag"]: o["kind"] for o in mode["options"]}
    values = {}
    for raw in set_args or []:
        flag, sep, val = raw.partition("=")
        if not sep:
            flag, val = raw, "on"
        kind = kinds.get(flag)
        if kind in ("toggle", "psbool"):
            values[flag] = val.strip().lower() in ("on", "y", "yes", "true", "1")
        else:
            values[flag] = val
    return values


def cmd_dry_run_profile(profile):
    print("# profile: %s" % profile["label"])
    for step in profile["steps"]:
        mode = mode_by_id(step["mode"])
        if mode is None:
            continue
        values = dict(step.get("values", {}))
        for det_key, flag in step.get("detect", {}).items():
            detector = DETECTORS.get(det_key)
            detected = detector() if detector else None
            values[flag] = detected or "<%s>" % det_key
        print(preview_command(mode, values))
        for filename, ids in idfile_plan(mode, values):
            print("# writes %s: %s" % (filename, ", ".join(ids)))
    optins = [mode_by_id(m) for m in profile.get("optins", [])]
    optins = [m["label"] for m in optins if m]
    if optins:
        print("# opt-ins offered after: %s" % ", ".join(optins))
    return 0


# ===========================================================================
# Entry point
# ===========================================================================
def main(argv=None):
    global DRY_RUN
    parser = argparse.ArgumentParser(
        prog=FILE_BASENAME,
        description="%s. Run with no flags for the interactive menu." % FILE_TITLE,
        epilog="One-line bootstrap:\n  %s" % ONELINER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list", action="store_true",
                        help="List modes and profiles, then exit.")
    parser.add_argument("--mode", metavar="ID", help="Run a single mode by id.")
    parser.add_argument("--profile", metavar="ID", help="Run a profile by id.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would run; never execute.")
    parser.add_argument("--set", metavar="FLAG=VALUE", action="append",
                        help="With --mode: set an option (e.g. --set=--all=on). "
                             "Repeatable; use the attached = form.")
    parser.add_argument("--no-curses", action="store_true",
                        help="Force the numbered-prompt menu.")
    args, passthrough = parser.parse_known_args(argv)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    DRY_RUN = args.dry_run

    if args.list:
        cmd_list()
        return 0

    if args.profile:
        profile = profile_by_id(args.profile)
        if profile is None:
            print("Unknown profile id: %s" % args.profile, file=sys.stderr)
            return 2
        if DRY_RUN:
            return cmd_dry_run_profile(profile)
        run_profile(PromptUI(), profile)
        return 0

    if args.mode:
        mode = mode_by_id(args.mode)
        if mode is None:
            print("Unknown mode id: %s" % args.mode, file=sys.stderr)
            return 2
        values = _parse_set_values(mode, args.set)
        tokens = None
        if mode.get("token_args") and not DRY_RUN:
            tokens = collect_tokens(mode)
            if tokens is None:
                return 1
        if mode["runner"] != "pwsh" and not DRY_RUN and not preflight(mode):
            return 1
        rc = run_mode(mode, values, tokens, extra_argv=passthrough)
        return rc if isinstance(rc, int) else 0

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
        run_session(frontend)
    finally:
        if isinstance(frontend, CursesUI):
            frontend.stop()
    print("\nDone.")
    return 0


# ---------------------------------------------------------------------------
# Embedded legacy sizing scripts (verbatim source, gzip+base64).
# Decoded and run in-process so CSV output is byte-identical to the originals.
# Regenerate with: python3 tools/build_wiz.py
# ---------------------------------------------------------------------------
BLOBS = {
    'AZURE_CLOUD': (
        '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'
    ),
    'AZURE_DEFEND': (
        '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'
    ),
    'AZURE_DEVOPS': (
        'H4sIAAAAAAAC/+U9/XPjtrG/669AlXkj6k6i7cslk6hVpq7PyfPkcnfPdpp2XA+HJiGJNUWqBOmP0+h/f7v4IkCCkuz4Oq/zMpmz'
        'SACLxWKxu1jsgl/94aBixcFNkh3Q7I6sHstFnn3d630FP9MkKyckTlh4k9Jpkt2FaRKPs3BJe71+v09+Sz6TCTmOyuSOknf0jqb5'
        'ihbkJK+yEgs+VwV//3HFCNRHoO/zKEwJK8OyYhOyzONkltCYzIp8ScoFRZDjRc5KeMeiIlmVPjT6WCTzJJuQRVmu2OTgIM7vszQP'
        'Y+bfJ5/9JD+IKlbmS1qMZ0lK2YFoyQ6O3308CDl241hhN44Qu3EY5/7qUSMULcJsTgGjWfJAGSnoioaIA/zIWVLmxSP8ZFGYMRJG'
        'Rc4YWRX5P2lUwnMWkzCOGVKsyOdQjY3IKgSEwzLJsxFhy7AogSwFLQEMdBQDXedYpygT6DuvylVVjjigeRUWcREmKYKb5QVJw2JO'
        'SV7Mwyz5zAEyv9dLlqu8KAmUARBG1XOUZ1FVFDQr/VlVAvGZLmF36mcMAyuTpW60CNkiTW7UY67bFIBQvlRPLJlnYaqfHnW1clHQ'
        'MIYR6RcIvMdnVLwB6PKX/BPAvFcpRX44BgIC7GyeUjnhRM3uiNxTeCBZXpJVdZMmbAF1C/qvKinoEgbJ/PKh9MlxVeZxHlX4CmgD'
        'RJ70CPyniIRc6MP85yvm39GCAQ15OcfQKgX6ZTCnUEE1PtFv6iZLBoQt/bACfs3KJArNBn8JWRIdW0U9+hBRGNcZr3FaFHkhEFwV'
        'sL68/j+y0/Pzj+cT8kvCkBJqiLG9gC7e/QwsE92Gc+qT8yrjy2WWp2l+j42ifLlEDipzkmSwvtL0oFrNizCmk39k/aHZ4SpZfa0q'
        'kfFYVhOkGAtSyAYwzT59SErvaMgn6y5PYmCYIo7yGPBTLDPjuPyUlP9T0eLxBDBJSnZSJMD1SYiLnKYTaO4i+d3fgr/786T0eS2m'
        'QHbAckilaEwfSprhrI6zfLykyxta9HgfgegjkJNOpk5e8P96en5x9vGDz1YpjHTgD4aSk42Gs77ddO3q4OrwehO4S46uN8Yo+70u'
        'Wk3tFeLZiAz9Lrr0erLKdPDG/84/GvTenf54/Ov7y+CX478Fv308/xkGCdCXSeZ9NyJeDsy+qgIuC70hyBdyNCSvyVuY5t5X8B8Q'
        '+kQy1Psko+S4mPP1xURpr8flToEklTLIV1U+8RIvpmI5C/oNhE6wGLqpNxgQXoD1QZ4GoYTncU4cjMdlfkuzwYg/Lmi6QrAXKxol'
        's0fOf7wc+b9i+ACCOgJZbPXpk5MwI2HKcnID8oaW5D4pFwT0RHD58efTD74EH9NZWKUl9ACEArWYFMAncwrcoasCstvRBZk9GMkf'
        'Wng30BdUESqKaBUFq0CsbsZHlzQlgQmQeEpaDCVsLT2m5LKo6A4sUY0JNKVCexEMJSzgM84AYTpsEfZDnu3CDZWvwK1Wwy+CnqHV'
        '0ZhB9j979zuRFVp8HCdFA8V3MBkR7wv1uahGuJ1CPNnDhEi1DVJNVm7jAIJpBwoxjYrHlZrBMFJrD2wjkEglMEMTNdGA0CVYHGjE'
        'oPFCOfU68JRSN26j9yOsql00Wobsdsw7Y/sj+Qs0qqfWhSuIQJBr2pJ6MXTZIr+vDccnoPwJ9SyhYbRADKIcZDOwYD0GEE5cYCm8'
        '2whzXpmFDO3GkzSvYnIBwFNSVBl73mDi8JHtuXi4TIyEhlErKQVcyAeCUAx0vz9UyJSPK4raKyubyH1/uAMz0dMYTGY6Zsln2sJS'
        'IAJEQ9EGphdBGtqq5NMZmtzUQO3o8HAP5LDWHhIS1mQnfp/URuDpCO6F38419SApyMa4vRFC01aSZb4iuHnJ0FAMTfEXzpDDPujZ'
        'rtGrsjSBV/Xa6UZyHxR1nwllLvQEIhrJD8Rs8AXRqrIxrMGqdGNVE03SSdble7V7NL70Lg7EEXT7BVG9z4vbWgpJNGcgHh+SZbW0'
        '6QWsiKgbG8L00cBs7TAONyNuNx1xycOQjzMc127cHbB2jCbJorSKYashhd3+gvUCB6VlpDXke9hx2WsuxK0RCDBTIcAmsuSTx26T'
        'lRvS88SrGhNdrspHF7fvOzoOYNfQCgq7+4yhZF4ao+OD4rVjWoJMwsE9bzjKkwHjAsa/C1OnhlO1COgOECadi/bNN7vZ6M03u9TE'
        'gka3qxyadiH1m7UgpTGgUONLuck0NYqHo5ax8HsFXumQdefcBxSWJU4z42utpSciYFwTtT2I981+KvZJeIk2Qmu50Hqzx5zuNPCh'
        'V7Cw0rBp159liZSqiBevgZYIoyDR4n8f3RTB3EjWoteJ5A0t72lz5boQPdoD06NdqM7ALB6jxbi/vDl9gPnNpSMpKVjZRpWit8qU'
        'n/mci08YYQmq8JnSBZbkTc7obkxjNKagQDZAr0hzEB/FMpc1oMVNNZ+jyk4y4JKl3CQ/YUcA2DJ4lPjzPzgC5g17vWTGvZH46HN3'
        'g+XIk2486akgCav34mALcF+E8h5gIaOl7/CzQR8cPje1/0SO3F3w0mUF5LmhsG5JStFAP9oCT6znANdzgGYswsadr7vwB/INmMbu'
        'vpsGO4padAIW6EOfkKsj4vu8+fUWdKRZ3YFPu/QHbqu7EWqZ6E6MjnZgBIs9kHZwAJZ0gJoCkOro02V36wk5xIGAagxBT+3o0dJH'
        'W3uzaj6npyoLlP26vaPaKH5OP9JQtebTfP8D+fZtd+eqlmsGv327g6O4NRIo86B79bTMmycuJW2KmH11rZa23fI8PiklixxtY5HS'
        '4o6nCIa9OmkbEk/ri6vKQKjKzk4Mjfs06GoIO3to6PX9esmxg1sag6b0eHfCwgzgxYhAJVYG+e0Ufa6WFz2bJfOqEHoIVedPaX4T'
        'ptqRLoGgow07BI3WPLHkx1yDXlbhyUaQzwIu+6e1lujhymYlnjKCskVdhkdw/jIHXZVnSYSaq4ZWyzbR39W1WShON4VUgkLQUdCa'
        'WwEsQOVv/Scah2UIRdEtaRbqk0H/PRQDHD4NjrqOquIF1oXl0lGVF0JdNO1x/GC4NsCuhcWhzmoDBvbYAI395nuxOTCKTGHbbGaX'
        '7WgKW7JVdzFabVapUkBtsFGIgCx9IUo39pkNsNn75KYIwSQ9AXNJ8RkYOvIMN+BH0LTwAvlc0IgCx8UjEsyKcEmHYtHgCT+wb1nk'
        '6fiEn99bh5ZnKMyKagVM5xPceqHR1fSG3FAwwiiuDixW5o7keVnJQ99ioOZixF2N1jD1UblcXNbCPBzKwSkbUSAIG2B0MxtD+au0'
        'EOW+UI1HyQ7TxBSN6tHOYLjvTv/y608TspaAN33VL18cdq8jbh/Th3I6GBgY8KPfZv+yJj9jXMuHzYT0ETFVRsEyJbL+EtQWbsmw'
        '/us1SK8VA67ABe8NN0RKOA1oLWzgQBxBgwjShNno7lmeKqrhQNeyh42cLGS7LA74MD1ZNrRIh0wc4NajplsRJoDyeZUhYnzcnjE8'
        'BxGtcdQkO+eODlWM7m8u2zT1VAHfM3lNsUfGxBaNAu9FXhUwRwUeJWQxP8WMkzuYeE+CG5Gvvz08FJWlITTS2zpdWbcfkW8PNUU4'
        'cIMQYgAweFFw+CbeTNYSqHySkPlTv2e32lZTLmoeSyMnUM1PTcELXtzkOu7ir8Vxm+HbrGXyhejZ5h1ZbLP8JRfWYxbOaOuYZk9c'
        'NMuJTp3sWHd4zIsJOtL4asOe00cVtCOMS6lCmI2B1mM1ArXe80W3HcigsMJaXpHfO3AxHe6oQ6HW78PLocwVgoiBQg623nVNr/5p'
        'ohjH5smPPJiacxOFn4+/FJ6mXeFXKwxCMjGSKCdZJEJ7uDr38HB2RMIlnlNNjwy0z1Q9DB5CrylW/3241kbEFXZ7TV5PZc8Stzkt'
        'a3KqyImWpFIHuVWW/KsyTtUIb/D7UJRSIaWZ10FZRcdOqd/CN0Q/3wpMTqIrEzN0Az1teuGi+YoM3FahCePxRFlEax3IymLYQl6W'
        'wkZglYZQGxROfwTarj80XhXylfCJqXguvSID6SbDP3pkfhDgvAWBwX1YEkjtCtjUdffvXcZunSriTAhpxyDdFDkIOU3AcRRW80XZ'
        'HHqf60FBMim0MYwKcEPW0q0Do0xjbDbS5oJ8MV0bLTbccDDBm8ZDrVdqQm7WBtyNtnDEY99g/u0Y1pz1F8rKMZ3NMI4LYBTSvweb'
        '+f++vPwkcSMcNx4P1opyE2JXsxeyYFiWBZ9fdLB6AwMBDBARjwOD21r0RQA1a2pwIx7aMdTtbNrV8AziISMZdYaSsGwF2tDZ2UAV'
        'DszeoCfdKGHcrYiFu4ag2uhRKyJwyNyd0FVz8HKD5WWDgZLaTOy6cS0EYZzvI3fuFxQ0TYGK2pp/obWBIGlyi5IS2CdjCUpUxQ7P'
        'WjpdQ9XDrGECg60Hbw+/Q8Z6e/g9//OG//nm8FD8eSP+fC3+vB1sejvkTZrfw35LyTM5omCF5y14jAf7aI3RAO0tELDSP61fxaT5'
        'kmJsYFgk6aP1Os/JMsweVSwCMwsLULuEn0qbb42wV2Aa2lUW3uRoRpuljBZ3SURB24V3MFJkAFl8zf/NYE5q1nCPF9pW5QI2ep9t'
        '2LDsb5I41iF//CUukxloUqtmnFOxgLgTxizhh6l2e+3xhy1yFi0s0s3eHh4dHn3fenf03aH57o69Pfz6LU6/MVTcDGWPnhwjcpHJ'
        'DyjDjCI3XdraUpxJGC/276LNZso4kLtveL3w0O3EBaHDMtBBYFhTxQFF0p8l+BFLdciaXqESVzD0sKX/zzzJ2g6zumeJVoY2Swpc'
        'ECQxxh7MElgyd2Fambh9UJV44J6Iwzh7Jw4EweKJFuiEaOCBK5HDQekIuxMfXiQrr16Vzf55iNmWrpshaOK0FPe6T+hc/B30B008'
        'MEhOosD/NVDgoXCid8sukzMhD5nowypNogRnhq34mSRTwgBmzTDa9FFW3WV758pfqxaDPw94q0S+b9Ue/GnB1+wPA17CPXQjEue4'
        'U4ZlzxupQOs/g/g8GjbsEt7iavLmevPq1as/r0XLeq8Lm+g0BjGfrwKgAB5pdHgMlH5BnkWvAeoIijHr+EIFehLZntxUMSiSDtpY'
        'Jye7l+geXgjyw9R9LPOKfHtoWFx5MQ9uQkaDqkg95wrtjgv+9fy9MK94ALIeGv6WncNPzY2FZMeDgdaXohhwZrgf8QaYfDM5gArI'
        'ya5CxktbBIKq9hzrLB5654uoetiCHKyhnmVu4uAlB3M54SIAMgQmIJgD51birO1ok/236WoOXvEm/LwaH11LdNDJHoTzPEhYbqJx'
        'EqZRlaJODck7+HOJvBQS4alHg5d76qGhRiIugwx2/1OdhePrH/De0w/4z2cw1vyqjIaqZT6bmS25VUDTMvSwm6l9PqDNUnG47cmO'
        'xxLO0IehiF2iNEts9+ms/w5RP57nsCGwIW9AnsBLAVo5CSVxxUu1WNNqnswePaRuNme2Vxm6w807j8fK0TjjddCLl+O0wjb5gGeb'
        'cT3Bp7SeRzmmwUDag6LpFKuCSPTQyB2p10O9hRAveICGKDJMbegukOUIV6isSAj2ugV3yQLhwhQo4g2HBqdzlF7jpmy8NqDZ7jyL'
        'OrYPXO3iZRZHEAm/e8AeQWgvmcl0REY8KBe79CVgLo+KcVJ5KxIKkVBqLqw9PvwIR5GIH0IlXHPjxICebuptY3kDMbC+T7NYCoHm'
        'kdWQq2cO9A9TYhx02VsN7u6AVpnXtEyGuHkCLUEzsMyBnNNBVc7G3yFgZjqX2jDtUfo8RSj2Gk18dLt4as3L+fwKpGlcoQbFdW3A'
        'aFOOcXvYwzMyw5U17HUPyqABju1+59gaQ8NJqsuEJcDNQNW7TYWvyGkmIvwZZkiJOO+wDNWxzL08tYE1B5L21rcam0pQZhZsobFE'
        'ZqrSCX22CN98863XqODz4YIsH/oL+hAnczBKvGHPDZLPEY+yxcODBqRNI6vN/A2rkKxtN9lwQy7zElR+nW5krpy/yhUjz7vIhVwx'
        'akXhprCxFDZbur/MxU6KWxutfrmtOMKAMYqqA7qXGXSDV80lJBMwOrqvz/14/ivuoDrP/lDv4d48SnFTYAqUn2jJ3YB6oye9wJZt'
        '8dFUsUqO2Dqjf/zpbMKhnSBznfCOXE68CHYPIroYV5EjY9IbwMKog6xq/jCQnBq5mZ5S5tO2dh/x7tjU6LSG95UaPMcVTDcYdj8C'
        '7Pvq1arI72A/wlQ2GdCmPqksabiEP7SM/JYymBrI+gIYwxSyAMHrWXD6GFEC0IfneBrNs0j6MHS+n/V/zRAWDkWiiD87Z3uiWA/s'
        'MyHW7MwqPkXqZLfZWf9Unvz6Zg0zqqJLP2KQJGfYcJWYyYSwc6yyaERe4R8emDciaEar2NWpUP8CCfTrUPnmlWhxe49tbCMutUfP'
        'B2lna2uWN7vCfErz0Qx2ktExpgMTK+FK5iFN3pGNNnlNjgzlaq0X03qGIXjm0O1R1XPwYixVzyirlkuULNP28YLJa1J3GBPg9m82'
        'gGPFqwF/GFzjVtHs06WYtngdAZ2uftTaGBGuUjRbbYgIxRCTnwEdNHDRsj9sQZRzwpMDGwiq6f7BZpFnYyXyT9YSzobUyMlXHhs+'
        'AUOWUroK6hPtpfLQNCKoRu2orVfEewNcRzw1xDEw7hCTh8V9AX6VJcgf3qHe3Tc82koMXf12fHZ5TZzjRY6V8PWgD9YmKfGkwuKR'
        'jU94FLs08tfWGCf+0WzD/AaJ+DaK1/Os2kNDZ86Tck+d+VNSKi/Z81UnAvmP1ZxAq22K047pkZFOT1Wf5nz839Gecu6/kBL9e16h'
        'cnnMq0JmuS9D1E13uFtj1WwmKI7uQIZmLCPep/phwm1B4p3DbmfIvTcsAgvz5VU2To+M29u2ajBaWlTjZJP8IpyoKl3NDJkQ1640'
        'fHOwzeCnXGacIOyo6n5NT5RZya+ryOOjFkfJsXW0MgarLEGvNqwbo9XJoQl31zlFgeZ4uRPvEg0Klksw8MwvTEzSm+oFbrsxXs7W'
        'OframqltYbVUx6xv4Y8dTNf476Y/alWux++bdGlXLPPV1B3g367Lu8R/rBLOwJJStsxQu3zVe8skwR2hLiR/6sg0aOvoG+CD214T'
        'NR4g4oTwRcXSiBgSaN5mi66FaQpfr+bmkeKIBuOem8kG+3HqrGZVqzWwvsQRpKDszUeX3sbFybX872RPwZr79mEzVj1yv0mVkWuh'
        'TBWwJO65WPDLTfOsMc9Po6mLDfCuGJXh4mKBkSF1zd+Bjo0yz8P+ntA01onj4mYfU2y7LZ2Z6SXQNwzosT1yz7J66OaSqL4wp+NK'
        'HMOrpCr7iGSA/nPuRjd9+t2C9BGHySNMdwtXRYz9ZGvX+K3pPGiRY4cobjC4srIcWwMNNonbxYpm7RJrs92RQDLatsubOjmr3aS9'
        'ArfoiC2qppnbZquTppLQ916wjv2qE/urgYzkv1bX7uxWItKSkR3uo3aMtNwk6264NaENXfKKp81jyGbFNlgD5w4aSEpH4QpAhNEC'
        '6eGGw2HZwZ7OBIdhZ+snoNA1JbWcbBUpCoGOP3IXSvL3/g2EfymiP5/gL0Ds9ub//MO1lIEgLldEQuBMvksGqu2Ui34bhx/EufjQ'
        'HJSNtTXYlBVPNgadwubfZyQ8U6f0zf33XuLNOFTg6WpmpPkO06JhabaugcPTkNBA3zA/NWqtTjHZa9MzlLDKoNKK2zkwbOZi44mI'
        '64Adpc7QUi+Ei3JCBoNNr9eWyi9nZLkGY8mjpmUlJp9n/+APfkLU6VCWgxaxdyK0ljtd8K0v3nLe2NJIHfk1I6dsICKIqdMz/Vyf'
        'dHPw+O4Ck+3Q/ycoMVLiRV2secwxAlbjYZkWoexRissNek5NbY1+8lI4nXJoOzHqtSwVezLweGHLKmmeKXTXvHJAv1YSnw2ubU7E'
        'GPPfCVtna5r/DZADYa05+bVt8mn0Jg2tLVeq0s94sZuTKo7z9ZGRw7GDun5ixmoYc2dl2Kn3P2IYay32eOC9/H0lxn29Id7aCAds'
        'YDbcDIUr0WyoJ2ijdIGSAlLjbRvAkPygsti3YS4OtNc7oW1Mod69Y913AygcTVZO09bZuKWPTEV18Gj7rYqtGXgP/NgXZf1elwHl'
        'SuWVTum0u8ftBlvde7ueynlk1FVf6gjpJm3aeo284lFTtVjJnjqh7codiae1mS+SKBozNtrNaa3+R3Ikoy6yyaPB64Z/o7sP1x3m'
        'ZZ6PMTp+zL26zBGJ5dXH++4cZG4HGDaMDMc6l+FYz8yJCzBaRIcUdaZ3bckADFgWrkCyIRiM3vIcdYaO1MZWu7po6MiOM6vHSVR6'
        'dVEdQKUE5o+wJHrtoB5hbuhbleVlyWsVMNjJdNrdqs8lV/n1cNMImulvCcBy4PFlArFak/v/LTJL8sL7fO7iAuS7L8sJY8za3Zsb'
        'LHy2ckTE7hq8gG84LTCRHB4EYQpP1Rw6aso6+b13Nfho3Q+tLxTFn+fGvcdAI0Odeu/xmpJWaC5G7Q77o/rW1Ast7wcXKgtscCpE'
        '6dBiZzReGjzcEi0Ny8YxHISiJ//CiN4wJLVMixI5jE3lr6dTZDLqR5HHCA1k1J5tfuC9jRvLRa5uqxBnM80ua1NEc5LRHz46+9On'
        'R5v62EWF1es51J3p3honwW6mlrHCaXhDcbX2P8mrNKRi4dip6zVETqcq6dk3Vaw5CLAd2ztr8zLfFu/wsPFGVKUjkrIl2Sw7b92e'
        '5826MQubtYtcm3bHDq1z1b605XpjHFOKd3/saOu8ueXaZpynwZDXu7RgiPd7DqlpnNXGu0KmX6cxOgE4PHnX7UsdOvt3NW+MSLnn'
        '3DefOS922RnU3jNjxWxjpJny/aUUhujaVhbdCsOBy1ZlIeq3w9NR3spM12z76G0q2HqXv6vjoG0pcCqSqLFyKT6LsHZgrxYdyGpY'
        'kOUj4beVifSZLH0U312JGpYwFGZ2NI9vClsmLkfQjjfA6Q4s+KCjmOctyu8FADVULZN7rXavp0emF0SlO2v32uAuYclNkiaY+clT'
        '7mR+HZlO8conjsygGRXhRFF1hZK3gfzU3CibIeDGHUkfPl6eTsiHvBZPPHXVrxdzAyrsvvkxQRfFntgpB9LsnJzNSJXRhxW8w10X'
        'LE78gIaI0vL13S5KZPOkSqp3RVsSufUkyiYi9U7nHYrkHGeKHTZspY3pQ4T7MCu5G9eZIKoBWNtC2QbDAJ2t2kzDHS6cXWBB79km'
        'iWWLjSSaofsU3Zxu7xbpjGPzJ1PPPjN6BvXqjeETqWc6sp9AQKvZNhomLOAJ3G4iWtdM2JdmP8r7r80oK2XbyYu6BWRL5W1J7eR3'
        'ipqXMBgjEJ8EsG924PWNqGdx5TgHYq3h5mxZHauFiBcjrUDVCdUtTGoPfscJhjJYQzDII27oLvJqvpBX5GD3cnspr3FM0WyrL7kX'
        'CZ2Nm96sL0d9KuhYABNobLNv3JaaTtI2IuOYkEXbgbUv5GtaKFy+ua3XDmo1AMBiq+QBpDzPUaR5CmrbLUJ7Bro7AOs/TFOaJmw5'
        'IdWK6+/mTaob+zLzEIMrMaS5BezEuMqbn2paEJtHlhsdA8E/YyEvrO7bd75tP7nGUoSHGy6v+0j8dcflwxhSTg4OyPbwjdb4wIxt'
        '06p1PGyNzlzJ4Q3eObvWuG84wTw2bNRUNwNZbli5QDQuMV2VC/wGhLCt/yg/5Cc/tmJf5Rs+qouiyRLs5mSVUvP2dWZ/vW1MLhcJ'
        'j08Rd1+JC49BGCZLDKMRiiFrfdZFZJ35jaQ1mamLzFwP0Nt+aMs/U4BCzZC3PMWl9SEZJUkaAX46D9txdOwOIXafI7/w2fr+3n33'
        'Sfy5HbIsUxmedPj+Uu73Q/6/OtsYORN2rofNKVkbN4n+EiaZmT6I1zC0U995xuQStkf0D3qy5eVxuy71dE2QaDrmDn+ciJ4dWyzj'
        'tc0sxp4d8uaK6O72A+3rBGqHH1hgnuC+sq8w0rEwZx9+/HgtXHWoGvdzF7W9Kg7XizNHVUeAd8WwS0eUMYF4Ib78adMioUYOuVvN'
        '1uUGgsaplr57f6/doH2uZoCxd3R2mE7zYL51EmkuQrcJwy0O+9RbWuHbt0qdQQXbLaVGpIfe0sqbpXbteqvsNsvvM7Cr/TIpU+q1'
        'XQTi/Hldt9vsCCk211FjfvcKMG+HGKHnwA7at+0z3aItPaYWFMuRbailmoM6LH0Xc3ScRTdjMnYYp+3QwXYYX+cmcSvjNIOZZBxT'
        '/538tEXfdIvYmy0W1N9cEotuKAXTaSbaNt0i+uBfskuz483eR/cNf81uxHDPpHe5atumqk0c4cJ2lIIOvGl/5WkPTLfPsLLx3fGh'
        'L6zFZW8mhQbm4c1WRkn23FHvRcnmNvs/kozyTrin0dD9uQ5+H2r39tK+5qlT/nRHxxoWpREhawa/mlA3zgTgDo27Z4y6e2TqsmHn'
        'RkFbXE/xW5heLXeVmmZ7xWs0jdueig1d4aUbccMHnYEWCsx1ksX0ofZQi2+pixBT9dUgwqob3JdiUzCnaVRBS2MxZXkmPl7ghG3Z'
        'EM7OgXe2sJbzcoDailJuqO3XpW1t7phantfiQufKOYQ6R889QtuW2rb5UlaRcWDNpwSvCZCU98V0eI2t7JaNozGzV+IvxiB6W+ub'
        '/jqnJX9xcgzr9gIdaeqj7NLLI+LatzqjzMe+cY1QnRbrS4R9ca/6pzxPTyUBPMMxNG16isRhlKw5aeQxIU4Sro6DN7/Xw32X25md'
        'M0zIWAOyhGrXi/ltHAGs9AB/ikzv5vjuw6R05E2JUkeuj7gzdXo06rgCIcCvIk4dHf14dn5xGZx8/OXT+9PL03fbc4NQOsXOpKD9'
        'F9sOiS8vJOwS9/VdgRv5ZQKPDflXzSOa8otKpBMTJ8/vu7M5+FVfYgElmXuS2lT3I96H5wb5xBi6+jsee+bjOPWyPQ73xLjFmJr9'
        'Vb6SrO8yBWxd4bRR8BI0kzxgnnVN+AubM7o/HifUZhuXddNJSWeGQGP+xdw65v9l75p5njdu+5UqL+CZ+4Izua+Xzg79t+2YqfjW'
        'WvP9f3V9GQ2PoVwNpk+wOrokmdCB6wZoIO/eyq9G64/C/dX67sKm9YEFef5DWA7TW7hE37avt4lvWjqJ56pun+K9qCB8UZ3c0su7'
        'dJXedHdqhZfUW45JehFFYiiRPTcLPeXrBuKoD0ngLPeDAD3fQdCfOJ2i0rHp8k/JIvGNLV/88eTTxdlPZx8uR/b3uBxp7sLrbp5z'
        '/Ewfb/KwiPXXt4xMAPvrXuLWs/pY+iUSr17gw13661C9/wXVKrizeowAAA=='
    ),
}

if __name__ == "__main__":
    sys.exit(main())
