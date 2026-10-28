"""Exercise fixture CLI namespaces without launching the product or relocation.

The CLI responses below only steer the real Python main() branches. These are
unit tests of argv/environment construction, not native-product pass evidence.
"""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import test_cli_non_ascii_arg as cli_arg
import test_non_ascii_path as non_ascii_path


class CliRuntimeIsolationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(
            tempfile.TemporaryDirectory(prefix="cbm-cli-runtime-unit-")))
        self.work = self.root / "work"
        self.work.mkdir()
        self.binary = self.root / "not-launched.exe"
        self.binary.write_bytes(b"unit fixture, not an executable\n")
        self.parent_env = {
            "CBM_CACHE_DIR": "synthetic-parent-cache",
            "CBM_RUNTIME_DIR": "synthetic-parent-runtime",
            "CBM_INDEX_SUPERVISOR": "0",
            "CBM_PROFILE": "synthetic-parent-profile-flag",
            "PATH": "synthetic-parent-path",
            "HOME": "synthetic-parent-home",
            "USERPROFILE": "synthetic-parent-profile",
            "APPDATA": "synthetic-parent-appdata",
            "LOCALAPPDATA": "synthetic-parent-localappdata",
            "TEMP": "synthetic-parent-temp",
            "TMP": "synthetic-parent-tmp",
            "SystemRoot": "synthetic-parent-systemroot",
            "CBM_TEST_MARKER": "synthetic-parent-marker",
        }
        self.original_parent_env = dict(self.parent_env)
        # Replace the entire mapping: never copy/read the operator environment.
        self.enterContext(patch.object(os, "environ", self.parent_env))
        self.enterContext(patch.object(sys, "argv", ["unit-test", str(self.binary)]))
        self.mkdtemp = self.enterContext(patch.object(
            tempfile, "mkdtemp", return_value=str(self.work)))
        self.cli_run = self.enterContext(patch.object(
            subprocess, "run", side_effect=AssertionError("unexpected subprocess.run")))
        self.popen = self.enterContext(patch.object(
            subprocess, "Popen", side_effect=AssertionError("process launch forbidden")))
        for owner, name in ((os, "system"), (os, "kill"),
                            (socket, "socket"), (socket, "create_connection"),
                            (socket, "getaddrinfo")):
            self.enterContext(patch.object(
                owner, name, side_effect=AssertionError("external action forbidden")))
        if os.name == "nt":
            import winreg
            for name, value in vars(winreg).items():
                if callable(value) and name[:1].isupper():
                    self.enterContext(patch.object(
                        winreg, name, side_effect=AssertionError("registry access forbidden")))
        self.relocation = self.enterContext(patch.object(
            non_ascii_path, "verify_relocated_runtime", return_value=None))
        self.index = self.enterContext(patch.object(
            non_ascii_path, "index_and_count",
            side_effect=AssertionError("unexpected index_and_count")))
        self.sleep = self.enterContext(patch.object(cli_arg.time, "sleep"))
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.calls = []

    def capture_cli(self, argv, **options):
        env = dict(options["env"])
        self.calls.append({
            "argv": list(argv),
            "options": {key: value for key, value in options.items() if key != "env"},
            "env": env,
            "runtime_exists_at_call": os.path.isdir(env.get("CBM_RUNTIME_DIR", "")),
        })
        return subprocess.CompletedProcess(argv, 0, stdout=b'{"nodes":7}', stderr=b"")

    def test_cjk_main_overrides_parent_runtime_before_cli(self):
        self.cli_run.side_effect = self.capture_cli
        self.assertEqual(cli_arg.main(), 0)
        self.assertEqual(self.cli_run.call_count, 3)
        self.mkdtemp.assert_called_once_with(prefix="cbm_win_cliarg_")
        expected_repos = ("ascii_repo", "caf\u00e9_\u65e5\u672c\u8a9e_repo", "\u96f7\u9054\u6e2c\u8a66")
        expected_caches = ("cache_ascii", "cache", "cache_cjk")
        for index, (call, repo_name, cache_name) in enumerate(zip(
                self.calls, expected_repos, expected_caches)):
            with self.subTest(cli_call=index):
                repo = str(self.work / repo_name)
                if index == 2:
                    self.assertEqual(call["argv"], [str(self.binary), "cli", "index_repository",
                                                   "--repo-path", repo, "--mode", "fast"])
                else:
                    self.assertEqual(call["argv"][:3], [str(self.binary), "cli", "index_repository"])
                    self.assertEqual(json.loads(call["argv"][3]), {"repo_path": repo})
                expected_env = dict(self.original_parent_env)
                expected_env["CBM_CACHE_DIR"] = str(self.work / cache_name)
                expected_env["CBM_RUNTIME_DIR"] = str(self.work / (cache_name + "_runtime"))
                if index:
                    expected_env.pop("CBM_INDEX_SUPERVISOR")
                self.assertEqual(call["env"], expected_env)
                self.assertTrue(call["runtime_exists_at_call"], "runtime must exist before CLI")
                self.assertEqual(call["options"], {"capture_output": True, "timeout": 120})
        self.assertEqual(self.parent_env, self.original_parent_env)
        self.assertEqual(len({call["env"]["CBM_RUNTIME_DIR"] for call in self.calls}), 3)
        self.popen.assert_not_called()
        self.relocation.assert_not_called()
        self.index.assert_not_called()
        self.sleep.assert_not_called()

    def test_failed_index_main_isolates_each_diagnostic_cli(self):
        baseline = {"name": "unit-baseline", "nodes": 7, "edges": 5,
                    "definition_nodes": 3, "go_definition_nodes": 2}
        ascii_repo = str(self.work / "ascii_repo")

        def index_result(binary, repo, cache):
            if repo == ascii_repo:
                return dict(baseline)
            return {"error": "unit-controlled indexing failure"}

        def diagnostic_result(argv, **options):
            self.capture_cli(argv, **options)
            return subprocess.CompletedProcess(
                argv, 1, stdout=b"", stderr=b"unit-controlled CLI diagnostic")

        self.index.side_effect = index_result
        self.cli_run.side_effect = diagnostic_result
        self.assertEqual(non_ascii_path.main(), 1)
        self.relocation.assert_called_once_with(str(self.binary), str(self.work))
        self.mkdtemp.assert_called_once_with(prefix="cbm_win_nonascii_")
        self.assertEqual(self.cli_run.call_count, len(non_ascii_path.NON_ASCII_SEGMENTS))
        expected_index_args = [(str(self.binary), ascii_repo, str(self.work / "c_ascii"))]
        for key, segment in non_ascii_path.NON_ASCII_SEGMENTS.items():
            repo = str(self.work / segment)
            expected_index_args.extend([
                (str(self.binary), repo, str(self.work / ("c_" + key))),
                (str(self.binary), repo, str(self.work / ("c2_" + key))),
            ])
        self.assertEqual([call.args for call in self.index.call_args_list], expected_index_args)
        for call, (key, segment) in zip(self.calls, non_ascii_path.NON_ASCII_SEGMENTS.items()):
            with self.subTest(diagnostic=key):
                self.assertEqual(call["argv"][:3], [str(self.binary), "cli", "index_repository"])
                self.assertEqual(json.loads(call["argv"][3]),
                                 {"repo_path": str(self.work / segment)})
                expected_env = dict(self.original_parent_env)
                expected_env["CBM_CACHE_DIR"] = str(self.work / ("c3_" + key))
                expected_env["CBM_RUNTIME_DIR"] = str(self.work / ("c3_" + key + "_runtime"))
                expected_env["CBM_PROFILE"] = "1"
                self.assertEqual(call["env"], expected_env)
                self.assertTrue(call["runtime_exists_at_call"], "runtime must exist before CLI")
                self.assertEqual(call["options"], {"capture_output": True, "timeout": 180})
        self.assertEqual(len({call["env"]["CBM_RUNTIME_DIR"] for call in self.calls}),
                         len(non_ascii_path.NON_ASCII_SEGMENTS))
        self.assertEqual(self.parent_env, self.original_parent_env)
        self.assertIn("unit-controlled indexing failure", self.output.getvalue())
        self.assertIn("unit-controlled CLI diagnostic", self.output.getvalue())
        self.assertIn("REGRESSION (red):", self.output.getvalue())
        self.popen.assert_not_called()
        self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
