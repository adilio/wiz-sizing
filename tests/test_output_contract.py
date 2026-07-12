"""§3 HARD CONSTRAINT — the CSV output contract.

Each consolidated mode runs its legacy script's source verbatim and in-process,
so the CSV format is preserved by construction. These tests enforce that:

  1. the embedded source decodes byte-for-byte to the legacy script, and
  2. the exact default filename(s) and column header(s) from §3 still appear in
     the embedded source for every mode.

Pure stdlib; no cloud SDKs or credentials required.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The transient legacy checkout path of the old blob-embedding design. NOTE:
# this is intentionally NOT reference/ — reference/ is the wiz-tools tree
# moved verbatim as the *bash* parity oracle (PLAN.md §3), while the embedded
# blobs legitimately evolved past it (e.g. azure scanner 2.9.0 vs 2.8.4), so
# they are not byte-comparable. Blob integrity is enforced at build time by
# tools/build_wiz.py --check instead.
LEGACY = ROOT / "sizing-scripts"


def load(stem):
    path = ROOT / ("wiz-%s.py" % stem)
    spec = importlib.util.spec_from_file_location("wiz_%s" % stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# (file stem, blob key, legacy path, [required substrings: filenames + headers])
CASES = [
    ("azure", "AZURE_CLOUD", "cloud/azure/resource-count-azure-v2.py", [
        "'azure-resources.csv'", "'azure-resources-log.csv'",
        "['Resource Type', 'Resource Count']",
        "['Resource Type', 'Resource Count', 'Subscription']",
    ]),
    ("azure", "AZURE_DEFEND", "defend/azure/log-volume-estimation-azure.py", [
        "azure-defend-log-volume-",
        "Log Source Type", "Billable Category", "Specific Metric",
        "Resource/Scope Details",
        "Estimated 30-Day Uncompressed Volume (GB)",
    ]),
    ("azure", "AZURE_DEVOPS", "code/azure-devops/active-developer-count-ado.py", [
        "['Organization', 'Project', 'Repository', "
        "f\"Developers (Last {number_of_days} Days)\", "
        "'Commits Scanned', 'Status', 'Error']",
    ]),
    ("aws", "AWS_CLOUD", "cloud/aws/resource-count-aws-v2.py", [
        "'aws-resources.csv'", "'aws-resources-log.csv'",
        "['Resource Type', 'Resource Count']",
        "['Resource Type', 'Resource Count', 'Account', 'Region']",
    ]),
    ("aws", "AWS_DEFEND", "defend/aws/log-volume-estimation-aws.py", [
        "'aws-defend-log-volume.csv'",
        "'Log Source Type', 'Billable Category', 'Specific Metric', "
        "'Bucket/Prefix Details', 'Estimated 30-Day Uncompressed Volume (GB)'",
    ]),
    ("gcp", "GCP_CLOUD", "cloud/gcp/resource-count-gcp-v2.py", [
        "'gcp-resources.csv'", "'gcp-resources-log.csv'",
        "['Resource Type', 'Resource Count']",
        "['Resource Type', 'Resource Count', 'Project', 'Region']",
    ]),
    ("gcp", "GCP_DEFEND", "defend/gcp/log-volume-estimation-gcp.py", [
        "gcp-defend-log-volume-",
        "Resource/Scope Details",
        "Estimated 30-Day Uncompressed Volume (GB)",
    ]),
    ("code", "GITHUB", "code/github/active-developer-count-github.py", [
        "['Organization', 'Repository', f\"Developers (Last {number_of_days} Days)\"]",
    ]),
    ("code", "GITLAB", "code/gitlab/active-developer-count-gitlab.py", [
        "['Group', 'Project', f\"Developers (Last {number_of_days} Days)\"]",
    ]),
]


class TestOutputContract(unittest.TestCase):
    def test_blobs_decode_and_compile(self):
        for stem, key, _, _ in CASES:
            with self.subTest(blob=key):
                module = load(stem)
                src = module.decode_blob(key)
                compile(src, "<%s>" % key, "exec")  # embedded source must parse

    def test_blobs_round_trip_byte_exact(self):
        # The byte-exact guarantee is enforced at build time; this re-checks it
        # against the legacy tree when it is still present (it lives in git
        # history after teardown).
        for stem, key, rel, _ in CASES:
            legacy_path = LEGACY / rel
            if not legacy_path.is_file():
                self.skipTest("legacy source removed (see git history): %s" % rel)
            with self.subTest(blob=key):
                module = load(stem)
                self.assertEqual(module.decode_blob(key),
                                 legacy_path.read_text(encoding="utf-8"),
                                 "%s does not decode to legacy source" % key)

    def test_csv_headers_and_filenames_present(self):
        for stem, key, _, required in CASES:
            module = load(stem)
            src = module.decode_blob(key)
            for needle in required:
                with self.subTest(blob=key, needle=needle):
                    self.assertIn(needle, src,
                                  "missing CSV contract token in %s" % key)


if __name__ == "__main__":
    unittest.main()
