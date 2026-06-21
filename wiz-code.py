#!/usr/bin/env python3
"""Wiz Sizing — Code (self-contained, curl-able).

Bundles the source-code developer-count modes into one file you can run
anywhere (each prompts for a token):

  * GitHub   — active developer count
  * GitLab   — active developer count

One-line bootstrap (run anywhere):
  curl -fsSL https://downloads.wiz.io/sizing/wiz-code.py -o wiz-code.py && python3 wiz-code.py

Run with no arguments for the interactive menu, or:
  python3 wiz-code.py --list
  python3 wiz-code.py --mode github --dry-run

The scanning logic is the original standalone sizing scripts, embedded verbatim
and run in-process, so the CSV output is byte-identical to those.
"""

FILE_TITLE = "Wiz Sizing — Code (GitHub / GitLab)"
FILE_BASENAME = "wiz-code.py"
ONELINER = ("curl -fsSL https://downloads.wiz.io/sizing/wiz-code.py "
            "-o wiz-code.py && python3 wiz-code.py")

MODES = [
    {
        "id": "github",
        "label": "GitHub — active developer count",
        "runner": "python3",
        "blob": "GITHUB",
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
        "label": "GitLab — active developer count",
        "runner": "python3",
        "blob": "GITLAB",
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
]

PROFILES = []

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
    'GITHUB': (
        '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'
        '6UgJgVoAAA=='
    ),
    'GITLAB': (
        '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'
        'STzzvKAKPAb/DxJq+1i6WwAA'
    ),
}

if __name__ == "__main__":
    sys.exit(main())
