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
