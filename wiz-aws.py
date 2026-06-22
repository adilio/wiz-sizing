#!/usr/bin/env python3
"""Wiz Sizing — AWS (self-contained, curl-able).

Bundles the AWS sizing modes into one file you can drop into AWS CloudShell:

  * AWS Cloud    — resource count
  * AWS Defend   — log-volume estimation

One-line bootstrap (AWS CloudShell):
  curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-aws.py -o wiz-aws.py && python3 wiz-aws.py

Run with no arguments for the interactive menu, or:
  python3 wiz-aws.py --list
  python3 wiz-aws.py --mode aws-cloud --dry-run
  python3 wiz-aws.py --profile aws-recommended

The cloud scanning logic is the original standalone sizing scripts, embedded
verbatim and run in-process, so the CSV output is byte-identical to those.
"""

FILE_TITLE = "Wiz Sizing — AWS"
FILE_BASENAME = "wiz-aws.py"
ONELINER = ("curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-aws.py "
            "-o wiz-aws.py && python3 wiz-aws.py")

MODES = [
    {
        "id": "aws-cloud",
        "label": "AWS — Cloud resource count",
        "runner": "python3",
        "blob": "AWS_CLOUD",
        "auth": "ambient",
        "probe": ["boto3"],
        "pip": "boto3 botocore eks_token kubernetes urllib3",
        "options": [
            {"flag": "--all", "kind": "toggle", "advanced": False,
             "help": "Count resources in ALL accounts in the current AWS Organization"},
            {"flag": "--data", "kind": "toggle", "advanced": False,
             "help": "Include Cloud Data Security resources (buckets, databases, …)"},
            {"flag": "--images", "kind": "toggle", "advanced": False,
             "help": "Include registry container images"},
            {"flag": "--regions", "kind": "idfile", "advanced": False,
             "idfile": "regions.txt",
             "help": "Limit to specific regions (comma/space list → regions.txt)"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output CSV"},
            {"flag": "--accounts", "kind": "idfile", "advanced": True,
             "idfile": "accounts.txt",
             "help": "Limit to specific account IDs (comma/space list → accounts.txt)"},
            {"flag": "--id", "kind": "str", "advanced": True,
             "help": "Scan only this single account ID"},
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
        "label": "AWS — Defend log volume",
        "runner": "python3",
        "blob": "AWS_DEFEND",
        "auth": "ambient",
        "probe": ["boto3"],
        "pip": "boto3 botocore",
        # NOTE: this mode has no --output-dir; it writes aws-defend-log-volume.csv
        # into the working directory.
        "options": [
            {"flag": "--defend-detailed", "kind": "toggle", "advanced": False,
             "help": "Produce a detailed per-source breakdown"},
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
]

PROFILES = [
    {
        "id": "aws-recommended",
        "label": "★ Recommended full sweep — all accounts + regions, then Defend",
        "steps": [
            {"mode": "aws-cloud",
             "values": {"--all": True, "--data": True, "--images": True}},
            {"mode": "aws-defend", "values": {}},
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
    'AWS_CLOUD': (
        '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'
        'ydj5/6zeTeJH+gAA'
    ),
    'AWS_DEFEND': (
        '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'
    ),
}

if __name__ == "__main__":
    sys.exit(main())
