#!/usr/bin/env python3
"""Wiz Sizing — GCP (self-contained, curl-able).

Bundles the GCP sizing modes into one file you can drop into GCP Cloud Shell:

  * GCP Cloud    — resource count
  * GCP Defend   — log-volume estimation

One-line bootstrap (GCP Cloud Shell):
  curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-gcp.py -o wiz-gcp.py && python3 wiz-gcp.py

Run with no arguments for the interactive menu, or:
  python3 wiz-gcp.py --list
  python3 wiz-gcp.py --mode gcp-cloud --dry-run
  python3 wiz-gcp.py --profile gcp-recommended

The cloud scanning logic is the original standalone sizing scripts, embedded
verbatim and run in-process, so the CSV output is byte-identical to those.
"""

FILE_TITLE = "Wiz Sizing — GCP"
FILE_BASENAME = "wiz-gcp.py"
ONELINER = ("curl -fsSL https://raw.githubusercontent.com/adilio/wiz-sizing/main/wiz-gcp.py "
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
