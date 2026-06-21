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
