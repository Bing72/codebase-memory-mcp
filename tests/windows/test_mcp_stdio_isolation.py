"""A graph-cache fixture must not rendezvous with the operator's daemon."""
import os
import tempfile
import unittest
from unittest.mock import patch

from mcp_stdio import McpServer


class RuntimeIsolationTests(unittest.TestCase):
    def test_cache_fixture_overrides_inherited_runtime_namespace(self):
        with tempfile.TemporaryDirectory(prefix="cbm-runtime-isolation-") as cache:
            with patch("mcp_stdio.os.environ", {"CBM_RUNTIME_DIR": "synthetic-parent-runtime"}):
                server = McpServer("not-launched.exe", cache_dir=cache)
            self.assertEqual(server.env["CBM_CACHE_DIR"], cache)
            self.assertEqual(server.env.get("CBM_RUNTIME_DIR"), os.path.join(cache, "runtime"))
            self.assertTrue(os.path.isdir(server.env["CBM_RUNTIME_DIR"]))
            self.assertIsNone(server.proc)

    def test_cache_fixture_overrides_full_parent_extra_env(self):
        parent_env = {
            "CBM_CACHE_DIR": "synthetic-parent-cache",
            "CBM_RUNTIME_DIR": "synthetic-parent-runtime",
            "PATH": "synthetic-parent-path",
            "HOME": "synthetic-parent-home",
            "USERPROFILE": "synthetic-parent-profile",
            "TEMP": "synthetic-parent-temp",
            "TMP": "synthetic-parent-tmp",
            "SystemRoot": "synthetic-parent-systemroot",
            "CBM_TEST_MARKER": "synthetic-parent-marker",
        }
        with tempfile.TemporaryDirectory(prefix="cbm-runtime-isolation-") as cache:
            with patch("mcp_stdio.os.environ", parent_env):
                server = McpServer("not-launched.exe", cache_dir=cache,
                                   extra_env=parent_env.copy())
            expected_env = dict(parent_env)
            expected_env["CBM_CACHE_DIR"] = cache
            expected_env["CBM_RUNTIME_DIR"] = os.path.join(cache, "runtime")
            self.assertEqual(server.env, expected_env)
            self.assertTrue(os.path.isdir(server.env["CBM_RUNTIME_DIR"]))
            self.assertIsNone(server.proc)

    def test_explicit_namespace_without_cache_fixture_is_preserved(self):
        parent_env = {
            "CBM_CACHE_DIR": "synthetic-parent-cache",
            "CBM_RUNTIME_DIR": "synthetic-parent-runtime",
            "PATH": "synthetic-parent-path",
        }
        extra_env = {
            "CBM_CACHE_DIR": "synthetic-explicit-cache",
            "CBM_RUNTIME_DIR": "synthetic-explicit-runtime",
            "CBM_TEST_MARKER": "synthetic-explicit-marker",
        }
        with patch("mcp_stdio.os.environ", parent_env):
            server = McpServer("not-launched.exe", extra_env=extra_env)
        self.assertEqual(server.env, {**parent_env, **extra_env})
        self.assertIsNone(server.proc)


if __name__ == "__main__":
    unittest.main()
