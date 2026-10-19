"""Tests for logging: configure_logging(), importing without touching
files, and the seed-ratio log written over the Transmission RPC for the
next run's ratio gate.

Run with: python -m unittest discover -s tests
"""

import logging
import logging.handlers
import os
import subprocess
import sys
import unittest
import unittest.mock

import helpers
import transmission_rpc.constants

import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


def configure_logging_for_test(testcase, log_dir, **env):
    """ft.configure_logging() with only `env`, undone when the test ends."""
    saved = (
        list(ft.logger.handlers),
        list(ft._configured_handlers),
        ft.logger.level,
        ft.logger.propagate,
    )

    def restore():
        for handler in ft._configured_handlers:
            handler.close()
        ft.logger.handlers[:] = saved[0]
        ft._configured_handlers[:] = saved[1]
        ft.logger.setLevel(saved[2])
        ft.logger.propagate = saved[3]

    testcase.addCleanup(restore)
    return ft.configure_logging(log_dir, env=env)


class RatioLogSurvivesConfigureLoggingTests(unittest.TestCase):
    """Each container run is a fresh process: the ratio log from the
    *previous* run is what should_fetch_torrent() needs in order to gate a
    new version's download. configure_logging() opens that same file with
    mode="w" for this run's ratios, so it must not truncate it before
    get_previous_ratios() has read it - otherwise the low-ratio fetch gate
    is silently defeated for every distro."""

    def setUp(self):
        self.log_dir = helpers.make_temp_dir(self, "fetch_torrents_ratio_restart_")
        self.path = os.path.join(self.log_dir, "fetch_torrents_ratios.log")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(
                "2026-08-01 00:00:00,000 INFO: [ratio] RATIOS START\n"
                "2026-08-01 00:00:00,000 INFO: [ratio] archlinux-2026.04.01-x86_64.iso            → 0.664\n"
                "2026-08-01 00:00:00,000 INFO: [ratio] RATIOS END\n"
            )

    def test_previous_ratios_are_readable_after_configure_logging(self):
        configure_logging_for_test(self, self.log_dir)

        self.assertEqual(
            ft.get_previous_ratios(self.path),
            {"archlinux-2026.04.01-x86_64.iso": 0.664},
        )

    def test_first_ratio_line_of_the_run_replaces_the_previous_log(self):
        _stream, _file, ratio_handler = configure_logging_for_test(self, self.log_dir)

        ft.logger.info("[ratio] %-50s → %.3f", "new.iso", 1.0)
        ratio_handler.flush()

        self.assertEqual(ft.get_previous_ratios(self.path), {"new.iso": 1.0})


class ImportOpensNoFilesTests(unittest.TestCase):
    """Importing fetch_torrents (tests, other scripts) must not create or
    truncate anything under FETCH_TORRENTS_LOG_DIR - only
    configure_logging() does. Needs a fresh interpreter, since this process
    imported the module long ago."""

    def test_import_leaves_the_log_dir_untouched(self):
        log_dir = helpers.make_temp_dir(self, "fetch_torrents_import_")
        script = (
            "import sys\n"
            f"sys.path.insert(0, {helpers.REPO_ROOT!r})\n"
            "import fetch_torrents as ft\n"
            "ft.logger.warning('logged before configure_logging()')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            env=dict(os.environ, FETCH_TORRENTS_LOG_DIR=log_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.listdir(log_dir), [])
        self.assertEqual(result.stderr, "")


class ConfigureLoggingTests(unittest.TestCase):
    """fetch_torrents.log must be bounded (RotatingFileHandler), not a plain
    FileHandler appending forever for the life of a 'deploy and forget'
    container."""

    def _configure(self, **env):
        log_dir = helpers.make_temp_dir(self, "fetch_torrents_log_rotation_")
        return configure_logging_for_test(self, log_dir, **env)

    def test_defaults_to_a_bounded_rotating_handler(self):
        _stream, file_handler, _ratio = self._configure()
        self.assertIsInstance(file_handler, logging.handlers.RotatingFileHandler)
        self.assertEqual(file_handler.maxBytes, 5 * 1024 * 1024)
        self.assertEqual(file_handler.backupCount, 3)

    def test_env_vars_override_rotation_settings(self):
        _stream, file_handler, _ratio = self._configure(
            FETCH_TORRENTS_LOG_MAX_BYTES="1000", FETCH_TORRENTS_LOG_BACKUP_COUNT="1"
        )
        self.assertEqual(file_handler.maxBytes, 1000)
        self.assertEqual(file_handler.backupCount, 1)

    def test_invalid_env_vars_fall_back_to_defaults(self):
        _stream, file_handler, _ratio = self._configure(
            FETCH_TORRENTS_LOG_MAX_BYTES="not-a-number",
            FETCH_TORRENTS_LOG_BACKUP_COUNT="also-bad",
        )
        self.assertEqual(file_handler.maxBytes, 5 * 1024 * 1024)
        self.assertEqual(file_handler.backupCount, 3)

    def test_calling_again_replaces_its_own_handlers_only(self):
        other = logging.NullHandler()
        ft.logger.addHandler(other)
        self.addCleanup(ft.logger.removeHandler, other)

        first = self._configure()
        second = self._configure()

        self.assertEqual(
            [h for h in ft.logger.handlers if h is not other], list(second)
        )
        self.assertIn(other, ft.logger.handlers)
        self.assertTrue(all(h not in ft.logger.handlers for h in first))


class LogSeedRatiosViaHttpTests(unittest.TestCase):
    """log_seed_ratios_via_http() must not hang the daily run forever on a
    stalled Transmission response, and must authenticate with whatever
    credentials configure_transmission.py configured the daemon with when
    the caller doesn't explicitly override auth."""

    class FakeSessionIdResponse:
        def __init__(self):
            self.headers = {"X-Transmission-Session-Id": "abc"}

    class FakeTorrentGetResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"arguments": {"torrents": []}}

    def test_requests_follow_the_transmission_rpc_protocol(self):
        # The pinned transmission_rpc's own tables of methods and torrent-get
        # fields stand in for the RPC spec, so a renamed field fails here.
        with unittest.mock.patch.object(
            ft.requests,
            "post",
            side_effect=[self.FakeSessionIdResponse(), self.FakeTorrentGetResponse()],
        ) as mock_post:
            ft.log_seed_ratios_via_http(auth=("alice", "hunter2"))

        session_call, get_call = mock_post.call_args_list
        self.assertEqual(
            session_call,
            unittest.mock.call("http://localhost:9091/transmission/rpc", timeout=15),
        )
        self.assertEqual(
            get_call,
            unittest.mock.call(
                "http://localhost:9091/transmission/rpc",
                json={
                    "method": "torrent-get",
                    "arguments": {"fields": ["name", "uploadRatio"]},
                },
                headers={"X-Transmission-Session-Id": "abc"},
                auth=("alice", "hunter2"),
                timeout=15,
            ),
        )
        payload = get_call.kwargs["json"]
        self.assertEqual(
            payload["method"], transmission_rpc.constants.RpcMethod.TorrentGet.value
        )
        self.assertLessEqual(
            set(payload["arguments"]["fields"]),
            set(transmission_rpc.constants.TORRENT_GET_ARGS),
        )

    def test_logs_ratios_highest_first_with_none_as_zero(self):
        response = self.FakeTorrentGetResponse()
        response.json = lambda: {
            "arguments": {
                "torrents": [
                    {"name": "low.iso", "uploadRatio": 0.5},
                    {"name": "unset.iso", "uploadRatio": None},
                    {"name": "high.iso", "uploadRatio": 2.25},
                ]
            }
        }
        with (
            unittest.mock.patch.object(
                ft.requests,
                "post",
                side_effect=[self.FakeSessionIdResponse(), response],
            ),
            self.assertLogs(ft.logger, level="INFO") as logs,
        ):
            ft.log_seed_ratios_via_http(auth=None)

        ratio_lines = [
            r.getMessage() for r in logs.records if r.getMessage().startswith("[ratio]")
        ]
        self.assertEqual(
            ratio_lines,
            [
                "[ratio] RATIOS START",
                f"[ratio] {'high.iso':<50} → 2.250",
                f"[ratio] {'low.iso':<50} → 0.500",
                f"[ratio] {'unset.iso':<50} → 0.000",
                "[ratio] RATIOS END",
            ],
        )

    def test_session_id_request_has_a_timeout(self):
        with unittest.mock.patch.object(
            ft.requests,
            "post",
            side_effect=[self.FakeSessionIdResponse(), self.FakeTorrentGetResponse()],
        ) as mock_post:
            ft.log_seed_ratios_via_http()

        first_call_kwargs = mock_post.call_args_list[0].kwargs
        self.assertIn("timeout", first_call_kwargs)

    def test_uses_configured_credentials_when_auth_not_explicitly_passed(self):
        with (
            unittest.mock.patch.dict(
                os.environ,
                {
                    "TRANSMISSION_RPC_USERNAME": "alice",
                    "TRANSMISSION_RPC_PASSWORD": "hunter2",
                },
            ),
            unittest.mock.patch.object(
                ft.requests,
                "post",
                side_effect=[
                    self.FakeSessionIdResponse(),
                    self.FakeTorrentGetResponse(),
                ],
            ) as mock_post,
        ):
            ft.log_seed_ratios_via_http()

        second_call_kwargs = mock_post.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get("auth"), ("alice", "hunter2"))

    def test_no_auth_when_credentials_unset(self):
        with (
            helpers.isolated_env(),
            unittest.mock.patch.object(
                ft.requests,
                "post",
                side_effect=[
                    self.FakeSessionIdResponse(),
                    self.FakeTorrentGetResponse(),
                ],
            ) as mock_post,
        ):
            ft.log_seed_ratios_via_http()

        second_call_kwargs = mock_post.call_args_list[1].kwargs
        self.assertIsNone(second_call_kwargs.get("auth"))

    def test_explicit_auth_argument_still_wins(self):
        with (
            unittest.mock.patch.dict(
                os.environ,
                {
                    "TRANSMISSION_RPC_USERNAME": "alice",
                    "TRANSMISSION_RPC_PASSWORD": "hunter2",
                },
            ),
            unittest.mock.patch.object(
                ft.requests,
                "post",
                side_effect=[
                    self.FakeSessionIdResponse(),
                    self.FakeTorrentGetResponse(),
                ],
            ) as mock_post,
        ):
            ft.log_seed_ratios_via_http(auth=("bob", "other"))

        second_call_kwargs = mock_post.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get("auth"), ("bob", "other"))


if __name__ == "__main__":
    unittest.main()
