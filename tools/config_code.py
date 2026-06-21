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
