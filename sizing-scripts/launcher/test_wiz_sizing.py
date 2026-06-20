#!/usr/bin/env python3
"""Unit tests for the Wiz Sizing launcher's command building.

These run anywhere (no CloudShell needed). They cover representative
*non-default* option combinations so B1-class regressions — where a scope flag
is serialized with an inline value the script rejects — cannot pass silently.

Run:  python3 test_wiz_sizing.py
"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "wiz_sizing", Path(__file__).resolve().parent / "wiz-sizing.py")
wz = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wz)


def argv(leaf_id, values):
    return wz.build_command(wz.leaf_by_id(leaf_id), values)


class ScopeFlagTests(unittest.TestCase):
    """B1: scope flags are bare toggles whose IDs live in a sibling .txt."""

    def test_regions_is_a_bare_toggle_not_a_valued_flag(self):
        cmd = argv("aws-cloud", {"--regions": "us-east-1,us-west-2"})
        self.assertIn("--regions", cmd)
        # the bug was emitting the ID list as the flag's value
        self.assertNotIn("us-east-1,us-west-2", cmd)
        # nothing after --regions is its value (next is another flag, or end)
        i = cmd.index("--regions")
        self.assertTrue(i == len(cmd) - 1 or cmd[i + 1].startswith("-"))

    def test_empty_scope_omits_flag(self):
        cmd = argv("aws-cloud", {"--regions": ""})
        self.assertNotIn("--regions", cmd)

    def test_idfile_plan_collects_all_idfiles(self):
        leaf = wz.leaf_by_id("gcp-cloud")
        plan = dict(wz.idfile_plan(leaf, {"--projects": "p1 p2",
                                          "--exclude": "f1,f2"}))
        self.assertEqual(plan["projects.txt"], ["p1", "p2"])
        self.assertEqual(plan["excluded-folders.txt"], ["f1", "f2"])

    def test_materialize_writes_one_id_per_line(self):
        leaf = wz.leaf_by_id("azure-cloud")
        with tempfile.TemporaryDirectory() as d:
            written = wz.materialize_idfiles(
                leaf, {"--subscriptions": "sub-a, sub-b sub-c"}, d)
            self.assertEqual(len(written), 1)
            content = Path(d, "subscriptions.txt").read_text().split()
            self.assertEqual(content, ["sub-a", "sub-b", "sub-c"])

    def test_parse_id_list_handles_mixed_separators(self):
        self.assertEqual(wz.parse_id_list("a, b\nc  d,,e"),
                         ["a", "b", "c", "d", "e"])


class OutputFlagTests(unittest.TestCase):
    def test_aws_defend_has_no_output_dir_flag(self):
        # the AWS Defend script writes its CSV to cwd and rejects --output-dir
        leaf = wz.leaf_by_id("aws-defend")
        flags = {o["flag"] for o in leaf["options"]}
        self.assertNotIn("--output-dir", flags)
        self.assertNotIn("--output-dir", argv("aws-defend", {}))


class SingleTargetTests(unittest.TestCase):
    def test_id_is_valued(self):
        cmd = argv("aws-cloud", {"--id": "123456789012"})
        i = cmd.index("--id")
        self.assertEqual(cmd[i + 1], "123456789012")


class AdoEnvTests(unittest.TestCase):
    def test_ado_token_uses_ADO_TOKEN_env(self):
        ado = wz.leaf_by_id("ado")
        envs = {t["flag"]: t.get("env") for t in ado["token_args"]}
        self.assertEqual(envs["--token"], "ADO_TOKEN")

    def test_ado_org_has_detector(self):
        ado = wz.leaf_by_id("ado")
        org = next(t for t in ado["token_args"] if t["flag"] == "--org")
        self.assertEqual(org["detect"], "ado_org")


class ProfileTests(unittest.TestCase):
    def test_every_csp_has_a_profile(self):
        self.assertEqual(set(wz.PROFILES), {"aws", "azure", "gcp"})

    def test_profile_steps_reference_real_leaves(self):
        for prof in wz.PROFILES.values():
            for step in prof["steps"]:
                self.assertIsNotNone(wz.leaf_by_id(step["leaf"]), step["leaf"])

    def test_azure_profile_is_org_wide(self):
        prof = wz.PROFILES["azure"]
        cloud = next(s for s in prof["steps"] if s["leaf"] == "azure-cloud")
        defend = next(s for s in prof["steps"] if s["leaf"] == "azure-defend")
        self.assertTrue(cloud["values"]["--all"])
        self.assertTrue(defend["values"]["--all-subscriptions"])
        cmd = argv("azure-defend", defend["values"])
        self.assertIn("--all-subscriptions", cmd)

    def test_gcp_profile_org_aggregate_needs_detected_org(self):
        defend = next(s for s in wz.PROFILES["gcp"]["steps"]
                      if s["leaf"] == "gcp-defend")
        self.assertEqual(defend["detect"], {"gcp_org": "--organization-id"})
        # simulate detection result
        vals = dict(defend["values"])
        vals["--organization-id"] = "111111111111"
        cmd = argv("gcp-defend", vals)
        self.assertIn("--org-aggregate", cmd)
        self.assertEqual(cmd[cmd.index("--organization-id") + 1], "111111111111")


class SetParserTests(unittest.TestCase):
    def test_set_parses_toggles_and_values(self):
        leaf = wz.leaf_by_id("aws-cloud")
        vals = wz._parse_set_values(leaf, ["--all", "--regions=us-east-1",
                                           "--max-workers=8"])
        self.assertIs(vals["--all"], True)
        self.assertEqual(vals["--regions"], "us-east-1")
        self.assertEqual(vals["--max-workers"], "8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
