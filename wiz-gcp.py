#!/usr/bin/env python3
"""Wiz Sizing — GCP (self-contained, curl-able).

Bundles the GCP sizing modes into one file you can drop into GCP Cloud Shell:

  * GCP Cloud    — resource count
  * GCP Defend   — log-volume estimation

One-line bootstrap (GCP Cloud Shell):
  curl -fsSL https://downloads.wiz.io/sizing/wiz-gcp.py -o wiz-gcp.py && python3 wiz-gcp.py

Run with no arguments for the interactive menu, or:
  python3 wiz-gcp.py --list
  python3 wiz-gcp.py --mode gcp-cloud --dry-run
  python3 wiz-gcp.py --profile gcp-recommended

The cloud scanning logic is the original standalone sizing scripts, embedded
verbatim and run in-process, so the CSV output is byte-identical to those.
"""

FILE_TITLE = "Wiz Sizing — GCP"
FILE_BASENAME = "wiz-gcp.py"
ONELINER = ("curl -fsSL https://downloads.wiz.io/sizing/wiz-gcp.py "
            "-o wiz-gcp.py && python3 wiz-gcp.py")

MODES = [
    {
        "id": "gcp-cloud",
        "label": "GCP — Cloud resource count",
        "runner": "python3",
        "blob": "GCP_CLOUD",
        "auth": "ambient",
        "probe": ["googleapiclient.discovery", "google.auth"],
        "pip": "google-api-python-client google-auth",
        "options": [
            {"flag": "--all", "kind": "toggle", "advanced": False,
             "help": "Count resources in ALL accessible GCP projects"},
            {"flag": "--data", "kind": "toggle", "advanced": False,
             "help": "Include Cloud Data Security resources (buckets, databases, …)"},
            {"flag": "--images", "kind": "toggle", "advanced": False,
             "help": "Include registry container images"},
            {"flag": "--projects", "kind": "idfile", "advanced": False,
             "idfile": "projects.txt",
             "help": "Limit to specific project IDs (comma/space list → projects.txt)"},
            {"flag": "--output-dir", "kind": "path", "advanced": False, "default": ".",
             "help": "Directory for the output CSV"},
            {"flag": "--id", "kind": "str", "advanced": True,
             "help": "Scan only this single project ID"},
            {"flag": "--exclude", "kind": "idfile", "advanced": True,
             "idfile": "excluded-folders.txt",
             "help": "Exclude folder IDs (comma/space list → excluded-folders.txt)"},
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
        "label": "GCP — Defend log volume",
        "runner": "python3",
        "blob": "GCP_DEFEND",
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
]

PROFILES = [
    {
        "id": "gcp-recommended",
        "label": "★ Recommended full sweep — all projects, then Defend (org-wide)",
        "steps": [
            {"mode": "gcp-cloud",
             "values": {"--all": True, "--data": True, "--images": True}},
            {"mode": "gcp-defend",
             "values": {"--org-aggregate": True},
             "detect": {"gcp_org": "--organization-id"}},
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
def choose_cwd(mode, values):
    """Pick a working directory from an --output-dir option if present."""
    for opt in mode["options"]:
        if opt["flag"] == "--output-dir":
            val = values.get(opt["flag"]) or opt.get("default")
            if val:
                p = Path(val).expanduser()
                if p.is_dir():
                    return str(p)
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
    cwd = choose_cwd(mode, values)
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
    print("  Output written under: %s" % cwd)
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
    'GCP_CLOUD': (
        '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'
    ),
    'GCP_DEFEND': (
        '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'
    ),
}

if __name__ == "__main__":
    sys.exit(main())
