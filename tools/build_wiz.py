#!/usr/bin/env python3
"""Assemble the self-contained wiz-<csp>.py files.

Each output file = a per-file config (header/docstring + MODES + PROFILES)
followed by the shared engine, followed by a generated BLOBS dict that holds
each legacy sizing script's *verbatim* source (gzip + base64). The legacy code
is run in-process by the engine, so the CSV output stays byte-identical.

This is a developer convenience, not a runtime dependency: the emitted
wiz-*.py files are fully self-contained and are what ship / get committed.

Usage:
    python3 tools/build_wiz.py            # build everything in SPECS
    python3 tools/build_wiz.py azure      # build one
    python3 tools/build_wiz.py --check    # fail if any output is stale
"""

import base64
import gzip
import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
LEGACY = ROOT / "sizing-scripts"

# output stem -> (config file, {BLOB_KEY: legacy script path relative to LEGACY})
SPECS = {
    "azure": {
        "config": "config_azure.py",
        "blobs": {
            "AZURE_CLOUD": "cloud/azure/resource-count-azure-v2.py",
            "AZURE_DEFEND": "defend/azure/log-volume-estimation-azure.py",
            "AZURE_DEVOPS": "code/azure-devops/active-developer-count-ado.py",
        },
    },
    "aws": {
        "config": "config_aws.py",
        "blobs": {
            "AWS_CLOUD": "cloud/aws/resource-count-aws-v2.py",
            "AWS_DEFEND": "defend/aws/log-volume-estimation-aws.py",
        },
    },
    "gcp": {
        "config": "config_gcp.py",
        "blobs": {
            "GCP_CLOUD": "cloud/gcp/resource-count-gcp-v2.py",
            "GCP_DEFEND": "defend/gcp/log-volume-estimation-gcp.py",
        },
    },
    "code": {
        "config": "config_code.py",
        "blobs": {
            "GITHUB": "code/github/active-developer-count-github.py",
            "GITLAB": "code/gitlab/active-developer-count-gitlab.py",
        },
    },
}

FOOTER = '\n\nif __name__ == "__main__":\n    sys.exit(main())\n'


def encode_source(path):
    """gzip+base64 a source file. Returns (b64_text, original_text)."""
    text = path.read_text(encoding="utf-8")
    blob = base64.b64encode(gzip.compress(text.encode("utf-8"), 9)).decode("ascii")
    # round-trip self-check: the embedded payload must decode to the exact source
    back = gzip.decompress(base64.b64decode(blob)).decode("utf-8")
    if back != text:
        raise SystemExit("Round-trip mismatch embedding %s" % path)
    compile(text, str(path), "exec")  # the legacy source must at least parse
    return blob, text


def existing_blob(stem, key):
    """Read an already-embedded blob from a previously built wiz-<stem>.py.

    Used when the legacy source tree has been removed (it lives in git history):
    the embedded payload in the current output is the source of truth, so
    scaffolding-only changes can still be regenerated.
    """
    out = ROOT / ("wiz-%s.py" % stem)
    if not out.is_file():
        return None
    spec = importlib.util.spec_from_file_location("wiz_%s_prev" % stem, out)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BLOBS.get(key)


def render_blobs(blob_map):
    lines = ["", "", "# ---------------------------------------------------------------------------",
             "# Embedded legacy sizing scripts (verbatim source, gzip+base64).",
             "# Decoded and run in-process so CSV output is byte-identical to the originals.",
             "# Regenerate with: python3 tools/build_wiz.py",
             "# ---------------------------------------------------------------------------",
             "BLOBS = {"]
    for key in sorted(blob_map):
        b64 = blob_map[key]
        lines.append("    %r: (" % key)
        for i in range(0, len(b64), 100):
            lines.append("        %r" % b64[i:i + 100])
        lines.append("    ),")
    lines.append("}")
    return "\n".join(lines)


def build_one(stem, spec):
    config_text = (TOOLS / spec["config"]).read_text(encoding="utf-8")
    engine_text = (TOOLS / "_engine.py").read_text(encoding="utf-8")
    blob_map = {}
    for key, rel in spec["blobs"].items():
        legacy = LEGACY / rel
        if legacy.is_file():
            blob_map[key], _ = encode_source(legacy)
        else:
            reused = existing_blob(stem, key)
            if reused is None:
                raise SystemExit(
                    "Cannot embed %s: legacy source %s is gone and no existing "
                    "blob to reuse. Restore it from git history to rebuild."
                    % (key, legacy))
            blob_map[key] = reused
    parts = [config_text.rstrip(), "\n\n", engine_text.strip("\n"),
             "\n", render_blobs(blob_map), FOOTER]
    assembled = "".join(parts)
    compile(assembled, "wiz-%s.py" % stem, "exec")  # the whole file must parse
    return assembled


def main(argv):
    check = "--check" in argv
    targets = [a for a in argv if not a.startswith("-")] or list(SPECS)
    stale = []
    for stem in targets:
        spec = SPECS.get(stem)
        if spec is None:
            print("Unknown target: %s" % stem, file=sys.stderr)
            return 2
        if not (TOOLS / spec["config"]).is_file():
            print("Skipping %s — %s not present yet." % (stem, spec["config"]))
            continue
        out = ROOT / ("wiz-%s.py" % stem)
        assembled = build_one(stem, spec)
        if check:
            current = out.read_text(encoding="utf-8") if out.is_file() else ""
            if current != assembled:
                stale.append(stem)
            continue
        out.write_text(assembled, encoding="utf-8")
        out.chmod(0o755)
        print("Wrote %s (%d bytes)" % (out.name, len(assembled)))
    if check and stale:
        print("Stale (re-run build_wiz.py): %s" % ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
