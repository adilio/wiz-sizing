"""Scaffolding (engine) unit tests — argv building, idfiles, profiles, CLI.

Loads the generated wiz-azure.py as the representative engine carrier. Pure
stdlib; no cloud SDKs or credentials required.
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(stem):
    path = ROOT / ("wiz-%s.py" % stem)
    spec = importlib.util.spec_from_file_location("wiz_%s" % stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBuildArgv(unittest.TestCase):
    def setUp(self):
        self.m = load("azure")
        self.cloud = self.m.mode_by_id("azure-cloud")
        self.devops = self.m.mode_by_id("azure-devops")

    def test_toggle_and_default_output_dir(self):
        argv = self.m.build_argv(self.cloud, {"--all": True})
        self.assertIn("--all", argv)
        self.assertEqual(argv[argv.index("--output-dir") + 1], ".")

    def test_idfile_serializes_to_bare_flag(self):
        argv = self.m.build_argv(self.cloud, {"--subscriptions": "a, b c"})
        self.assertIn("--subscriptions", argv)
        # value goes into the sibling .txt file, not the argv
        self.assertNotIn("a", argv)
        plan = self.m.idfile_plan(self.cloud, {"--subscriptions": "a, b c"})
        self.assertEqual(plan, [("subscriptions.txt", ["a", "b", "c"])])

    def test_str_and_int_options(self):
        argv = self.m.build_argv(self.cloud, {"--id": "sub-1", "--max-workers": 8})
        self.assertEqual(argv[argv.index("--id") + 1], "sub-1")
        self.assertEqual(argv[argv.index("--max-workers") + 1], "8")

    def test_tokens_come_first(self):
        argv = self.m.build_argv(self.devops, {"--days": 30},
                                 tokens={"--org": "myorg", "--token": "secret"})
        self.assertEqual(argv[:4], ["--org", "myorg", "--token", "secret"])

    def test_preview_masks_secret_token(self):
        preview = self.m.preview_command(
            self.devops, {}, tokens={"--org": "myorg", "--token": "secret"})
        self.assertIn("myorg", preview)
        self.assertNotIn("secret", preview)
        self.assertIn("***", preview)


class TestParseSet(unittest.TestCase):
    def setUp(self):
        self.m = load("azure")
        self.cloud = self.m.mode_by_id("azure-cloud")

    def test_toggle_on_off_and_bare(self):
        v = self.m._parse_set_values(self.cloud,
                                     ["--all=on", "--data=off", "--graph"])
        self.assertIs(v["--all"], True)
        self.assertIs(v["--data"], False)
        self.assertIs(v["--graph"], True)

    def test_value_options(self):
        v = self.m._parse_set_values(self.cloud, ["--id=sub-9"])
        self.assertEqual(v["--id"], "sub-9")


class TestProfilesAndModes(unittest.TestCase):
    def test_every_profile_step_resolves(self):
        for stem in ("azure", "aws", "gcp"):
            m = load(stem)
            for profile in m.PROFILES:
                for step in profile["steps"]:
                    with self.subTest(stem=stem, mode=step["mode"]):
                        self.assertIsNotNone(m.mode_by_id(step["mode"]))
                for opt in profile.get("optins", []):
                    with self.subTest(stem=stem, optin=opt):
                        self.assertIsNotNone(m.mode_by_id(opt))

    def test_aws_defend_has_no_output_dir(self):
        m = load("aws")
        defend = m.mode_by_id("aws-defend")
        flags = [o["flag"] for o in defend["options"]]
        self.assertNotIn("--output-dir", flags)

    def test_every_python_mode_blob_exists(self):
        for stem in ("azure", "aws", "gcp", "code"):
            m = load(stem)
            for mode in m.MODES:
                if mode["runner"] != "python3":
                    continue
                with self.subTest(stem=stem, mode=mode["id"]):
                    self.assertIn(mode["blob"], m.BLOBS)


class TestCliEndToEnd(unittest.TestCase):
    """Drive the real files via subprocess on the no-exec paths."""

    def run_file(self, stem, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / ("wiz-%s.py" % stem)), *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def test_list(self):
        r = self.run_file("azure", "--list")
        self.assertEqual(r.returncode, 0)
        self.assertIn("azure-cloud", r.stdout)

    def test_dry_run_mode(self):
        r = self.run_file("azure", "--mode", "azure-cloud", "--dry-run",
                          "--set=--all=on")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--all", r.stdout)
        self.assertIn("[dry-run]", r.stdout)

    def test_dry_run_profile(self):
        r = self.run_file("aws", "--profile", "aws-recommended", "--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("aws-cloud", r.stdout)
        self.assertIn("aws-defend", r.stdout)

    def test_unknown_mode_errors(self):
        r = self.run_file("azure", "--mode", "nope", "--dry-run")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
