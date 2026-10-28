"""Pure section-level regressions: UI probe failures must never become SKIP.

All process, socket, database, filesystem and kill boundaries are mocked. No
product binary or daemon is launched by these tests.
"""
import io
import itertools
import unittest
from contextlib import ExitStack, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_daemon_stability as stability


NON_UI_WARNING = ("warning: this binary was built without UI support; "
                  "--port/--open have no effect\n")
HANDSHAKE_WARNING = (
    "warning: the daemon started but did not accept the UI configuration; "
    "the UI is unavailable until the next `daemon start`\n")
HANDSHAKE_ERROR = (
    "error: the daemon did not accept the UI configuration; browser was not opened\n")
STARTED = "daemon: started (permanent, pid 4101)\n"
UI_READY = "  ui: http://127.0.0.1:43123\n"


def result(text, returncode=0):
    return SimpleNamespace(returncode=returncode, stdout=text.encode(), stderr=b"")


class UiCapabilityDetectionTests(unittest.TestCase):
    def setUp(self):
        self.boundaries = ExitStack()
        self.addCleanup(self.boundaries.close)
        self.output = io.StringIO()
        self.boundaries.enter_context(redirect_stdout(self.output))

        def mock_boundary(name, **kwargs):
            return self.boundaries.enter_context(patch.object(stability, name, **kwargs))

        mock_boundary("section_dirs", return_value="synthetic-work/cache-writer")
        mock_boundary("cli_env", return_value={"CBM_RUNTIME_DIR": "synthetic-runtime"})
        self.kill_pid = mock_boundary("kill_pid")
        self.wait_stopped = mock_boundary("wait_status_not_running", return_value=True)
        self.log_contains = mock_boundary("daemon_log_contains", return_value=True)
        self.boundaries.enter_context(patch.object(
            stability, "open", create=True,
            side_effect=AssertionError("unexpected real filesystem access")))
        self.boundaries.enter_context(patch.object(
            stability.subprocess, "run",
            side_effect=AssertionError("unexpected real subprocess execution")))
        self.socket = self.boundaries.enter_context(patch.object(stability.socket, "socket"))
        self.socket.return_value.getsockname.return_value = ("127.0.0.1", 43123)
        self.connect = self.boundaries.enter_context(patch.object(stability.sqlite3, "connect"))
        self.client = MagicMock()
        self.client.poll.return_value = None
        self.client.returncode = 0
        self.client.communicate.return_value = ((STARTED + UI_READY).encode(), None)
        self.popen = self.boundaries.enter_context(
            patch.object(stability.subprocess, "Popen", return_value=self.client))
        self.boundaries.enter_context(patch.object(
            stability.time, "monotonic", side_effect=itertools.count(step=0.5)))
        self.sleep = self.boundaries.enter_context(patch.object(stability.time, "sleep"))
        self.warm = result(STARTED + UI_READY)
        self.stop = result("daemon: stopped\n")
        self.run_cli = mock_boundary("run_cli", side_effect=self._run_cli)

    def _run_cli(self, binary, cache, args, **kwargs):
        if args[:2] == ["daemon", "start"]:
            return self.warm
        if args == ["daemon", "stop"]:
            return self.stop
        self.fail("unexpected CLI invocation: %r" % args)

    def _run_section(self):
        try:
            return stability.section_start_port_waits_for_settings_writer(
                "not-launched.exe", "synthetic-work")
        except stability.SetupFailure as exc:
            self.fail("UI probe failure must be a regression, not SetupFailure: %s" % exc)

    def test_failed_or_unknown_ui_probe_is_regression(self):
        cases = [
            ("handshake warning", result(STARTED + HANDSHAKE_WARNING)),
            ("handshake error without pid", result(HANDSHAKE_ERROR, 1)),
            ("unknown successful output", result(STARTED)),
            ("missing output", result("")),
        ]
        for name, warm in cases:
            with self.subTest(name=name):
                self.warm = warm
                self.output.seek(0)
                self.output.truncate()
                self.connect.reset_mock()
                self.popen.reset_mock()
                self.run_cli.reset_mock()
                self.assertIs(self._run_section(), False,
                              "failed/unknown UI capability must fail closed")
                self.assertIn("RED:", self.output.getvalue())
                self.assertNotIn("SKIP:", self.output.getvalue())
                self.assertNotIn("PASS:", self.output.getvalue())
                self.connect.assert_not_called()
                self.popen.assert_not_called()
                self.assertTrue(any(call.args[2] == ["daemon", "stop"]
                                    for call in self.run_cli.call_args_list),
                                "warm daemon cleanup must run even without a reported pid")


    def test_explicit_non_ui_evidence_skips_after_private_warm_cleanup(self):
        self.warm = result(STARTED + NON_UI_WARNING)
        self.assertIs(self._run_section(), True)
        self.assertIn("SKIP: non-UI binary", self.output.getvalue())
        self.assertNotIn("PASS:", self.output.getvalue())
        self.connect.assert_not_called()
        self.popen.assert_not_called()
        self.assertEqual([call.args[2] for call in self.run_cli.call_args_list], [
            ["daemon", "start", "--port=43123"], ["daemon", "stop"]])
        self.wait_stopped.assert_called_once_with(
            "not-launched.exe", "synthetic-work/cache-writer", 45)
        self.kill_pid.assert_called_once_with(0)
        self.socket.return_value.close.assert_called_once_with()

    def test_incomplete_or_conflicting_non_ui_evidence_fails_closed(self):
        cases = [
            ("truncated warning", result(STARTED + "warning: this binary was built without UI support\n")),
            ("missing pid", result(NON_UI_WARNING)),
            ("failed start", result(STARTED + NON_UI_WARNING, 1)),
            ("conflicting UI marker", result(STARTED + NON_UI_WARNING + UI_READY)),
            ("handshake warning", result(STARTED + NON_UI_WARNING + HANDSHAKE_WARNING)),
        ]
        for name, warm in cases:
            with self.subTest(name=name):
                self.warm = warm
                self.output.seek(0)
                self.output.truncate()
                self.assertIs(self._run_section(), False)
                self.assertIn("RED:", self.output.getvalue())
                self.assertNotIn("SKIP:", self.output.getvalue())
                self.connect.assert_not_called()
                self.popen.assert_not_called()

    def test_ui_marker_does_not_hide_a_handshake_warning(self):
        self.warm = result(STARTED + UI_READY + HANDSHAKE_WARNING)
        self.assertIs(self._run_section(), False)
        self.assertNotIn("SKIP:", self.output.getvalue())
        self.connect.assert_not_called()
        self.popen.assert_not_called()

    def test_unrecognized_ui_marker_is_inconclusive(self):
        self.warm = result(STARTED + "  ui: unavailable\n")
        self.assertIs(self._run_section(), False)
        self.assertIn("RED:", self.output.getvalue())
        self.assertNotIn("SKIP:", self.output.getvalue())
        self.connect.assert_not_called()
        self.popen.assert_not_called()

    def test_healthy_ui_runs_the_original_held_writer_check(self):
        self.warm = result(
            STARTED + "  ui: warming asynchronously on configured port 43123\n")
        holder = self.connect.return_value

        def communicate(**kwargs):
            holder.close.assert_called_once_with()
            return (STARTED + UI_READY).encode(), None

        self.client.communicate.side_effect = communicate
        self.assertIs(self._run_section(), True)
        self.connect.assert_called_once_with(
            stability.os.path.join("synthetic-work/cache-writer", "_config.db"),
            isolation_level=None, timeout=0)
        holder.execute.assert_called_once_with("BEGIN IMMEDIATE")
        self.popen.assert_called_once_with(
            ["not-launched.exe", "daemon", "start", "--port=43123"],
            env={"CBM_RUNTIME_DIR": "synthetic-runtime"},
            stdout=stability.subprocess.PIPE, stderr=stability.subprocess.STDOUT)
        self.log_contains.assert_called_with(
            "synthetic-work/cache-writer", b"config_db.busy_wait")
        self.sleep.assert_called_with(0.05)
        self.client.communicate.assert_called_once_with(timeout=90)
        self.client.kill.assert_not_called()
        self.assertEqual([call.args[2] for call in self.run_cli.call_args_list], [
            ["daemon", "start", "--port=43123"],
            ["daemon", "stop"], ["daemon", "stop"]])
        self.assertIn("PASS:", self.output.getvalue())
        self.assertNotIn("SKIP:", self.output.getvalue())

    def test_healthy_ui_does_not_hide_a_client_exiting_under_the_write_lock(self):
        self.client.poll.return_value = 0
        self.assertIs(self._run_section(), False)
        self.connect.return_value.execute.assert_called_once_with("BEGIN IMMEDIATE")
        self.assertIn("exited_under_lock=True", self.output.getvalue())
        self.assertNotIn("SKIP:", self.output.getvalue())
        self.assertNotIn("PASS:", self.output.getvalue())

    def test_healthy_ui_does_not_hide_held_writer_handshake_failure(self):
        self.client.returncode = 1
        self.client.communicate.return_value = (HANDSHAKE_ERROR.encode(), None)
        self.assertIs(self._run_section(), False)
        self.assertIn("must wait for a settings writer", self.output.getvalue())
        self.assertNotIn("SKIP:", self.output.getvalue())
        self.client.kill.assert_called_once_with()
        self.client.wait.assert_called_once_with()

    def test_warm_stop_failure_is_not_a_skip_and_uses_pid_backstop(self):
        self.warm = result(STARTED + NON_UI_WARNING)
        self.stop = result("error: stop failed\n", 1)
        self.assertIs(self._run_section(), False)
        self.assertNotIn("SKIP:", self.output.getvalue())
        self.assertEqual(sum(call.args[2] == ["daemon", "stop"]
                             for call in self.run_cli.call_args_list), 2)
        self.kill_pid.assert_called_once_with(4101)
        self.connect.assert_not_called()

    def test_warm_status_failure_is_not_a_skip_and_uses_pid_backstop(self):
        self.warm = result(STARTED + NON_UI_WARNING)
        self.wait_stopped.return_value = False
        self.assertIs(self._run_section(), False)
        self.assertNotIn("SKIP:", self.output.getvalue())
        self.kill_pid.assert_called_once_with(4101)
        self.connect.assert_not_called()

    def test_warm_start_timeout_still_stops_the_private_namespace(self):
        timeout = stability.subprocess.TimeoutExpired(["not-launched.exe"], 60)
        self.run_cli.side_effect = [timeout, self.stop]
        with self.assertRaises(stability.subprocess.TimeoutExpired):
            self._run_section()
        self.run_cli.assert_called_with(
            "not-launched.exe", "synthetic-work/cache-writer", ["daemon", "stop"], timeout=60)
        self.kill_pid.assert_called_once_with(0)
        self.connect.assert_not_called()
        self.popen.assert_not_called()

    def test_failed_warm_cleanup_cannot_bypass_a_known_pid_backstop(self):
        self.warm = result(STARTED + HANDSHAKE_ERROR, 1)
        timeout = stability.subprocess.TimeoutExpired(["not-launched.exe"], 60)
        self.run_cli.side_effect = [self.warm, timeout]
        with self.assertRaises(stability.subprocess.TimeoutExpired):
            self._run_section()
        self.kill_pid.assert_called_once_with(4101)
        self.assertNotIn("SKIP:", self.output.getvalue())

    def test_probe_bind_failure_closes_socket_without_starting_a_daemon(self):
        self.socket.return_value.bind.side_effect = OSError("synthetic bind failure")
        with self.assertRaisesRegex(OSError, "synthetic bind failure"):
            self._run_section()
        self.socket.return_value.close.assert_called_once_with()
        self.run_cli.assert_not_called()
        self.kill_pid.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
