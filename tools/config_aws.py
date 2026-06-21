#!/usr/bin/env python3
"""Wiz Sizing — AWS (self-contained, curl-able).

Bundles the AWS sizing modes into one file you can drop into AWS CloudShell:

  * AWS Cloud    — resource count
  * AWS Defend   — log-volume estimation

One-line bootstrap (AWS CloudShell):
  curl -fsSL https://downloads.wiz.io/sizing/wiz-aws.py -o wiz-aws.py && python3 wiz-aws.py

Run with no arguments for the interactive menu, or:
  python3 wiz-aws.py --list
  python3 wiz-aws.py --mode aws-cloud --dry-run
  python3 wiz-aws.py --profile aws-recommended

The cloud scanning logic is the original standalone sizing scripts, embedded
verbatim and run in-process, so the CSV output is byte-identical to those.
"""

FILE_TITLE = "Wiz Sizing — AWS"
FILE_BASENAME = "wiz-aws.py"
ONELINER = ("curl -fsSL https://downloads.wiz.io/sizing/wiz-aws.py "
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
