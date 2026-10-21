"""Tests for logging: configure_logging(), importing without touching
files, and the seed-ratio log written over the Transmission RPC for the
next run's ratio gate.

Run with: python -m unittest discover -s tests
"""

import io
import logging
import logging.handlers
import os
import subprocess
import sys
import unittest
import unittest.mock

import helpers

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
            # -W ignore: a dependency warning at import must not fail the
            # stderr check below.
            [sys.executable, "-W", "ignore", "-c", script],
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
        self.assertEqual([h for h in first if h in ft.logger.handlers], [])


class ParseLogLevelTests(unittest.TestCase):
    def test_values(self):
        for value, expected in (
            (None, logging.WARNING),  # unset
            ("", logging.WARNING),
            ("   ", logging.WARNING),
            ("10", 10),
            ("debug", logging.DEBUG),
            (" Error ", logging.ERROR),
            ("bogus", logging.WARNING),
            ("²", logging.WARNING),  # isdigit(), but not an int
        ):
            env = {} if value is None else {"LEVEL": value}
            with self.subTest(value=value):
                self.assertEqual(
                    ft.parse_log_level("LEVEL", logging.WARNING, env=env), expected
                )


class LogRoutingTests(unittest.TestCase):
    """Where configure_logging() sends each record: "[ratio]" lines only to
    the ratio log; everything else to stderr and fetch_torrents.log at the
    configured level, except that with FETCH_TORRENTS_ALWAYS_LOG (on by
    default) progress lines starting with an always-log prefix get through
    whatever the level."""

    def _route(self, **env):
        """Configures logging with env, emits one record of each kind and
        returns (stderr lines, fetch_torrents.log lines, ratio log lines),
        each without the timestamp prefix."""
        log_dir = helpers.make_temp_dir(self, "fetch_torrents_routing_")
        stream_handler, file_handler, ratio_handler = configure_logging_for_test(
            self, log_dir, **env
        )
        stderr = io.StringIO()
        stream_handler.setStream(stderr)

        ft.logger.debug("plain debug")
        ft.logger.info("plain info")
        ft.logger.warning("plain warning")
        ft.logger.info("Fetching latest arch torrents...")
        ft.logger.info("[ratio] RATIOS START")
        ft.logger.debug("[ratio] debug ratio")
        for handler in (stream_handler, file_handler, ratio_handler):
            handler.flush()

        def lines(text):
            return [line.split(" ", 2)[2] for line in text.splitlines()]

        with open(os.path.join(log_dir, "fetch_torrents.log"), encoding="utf-8") as f:
            main_log = lines(f.read())
        with open(
            os.path.join(log_dir, "fetch_torrents_ratios.log"), encoding="utf-8"
        ) as f:
            ratio_log = lines(f.read())
        return lines(stderr.getvalue()), main_log, ratio_log

    def test_defaults_log_info_and_up_plus_always_log_lines(self):
        stderr, main_log, ratio_log = self._route()

        expected = [
            "INFO: plain info",
            "WARNING: plain warning",
            "INFO: Fetching latest arch torrents...",
        ]
        self.assertEqual(stderr, expected)
        self.assertEqual(main_log, expected)
        self.assertEqual(ratio_log, ["INFO: [ratio] RATIOS START"])

    def test_always_log_lines_get_through_a_higher_level(self):
        stderr, main_log, _ = self._route(FETCH_TORRENTS_LOG_LEVEL="WARNING")

        expected = ["WARNING: plain warning", "INFO: Fetching latest arch torrents..."]
        self.assertEqual(stderr, expected)
        self.assertEqual(main_log, expected)

    def test_always_log_off_applies_the_level_to_everything(self):
        stderr, main_log, _ = self._route(
            LOG_LEVEL="WARNING", FETCH_TORRENTS_ALWAYS_LOG="false"
        )

        self.assertEqual(stderr, ["WARNING: plain warning"])
        self.assertEqual(main_log, ["WARNING: plain warning"])

    def test_fetch_torrents_log_level_takes_precedence_over_log_level(self):
        _, main_log, _ = self._route(
            FETCH_TORRENTS_LOG_LEVEL="DEBUG", LOG_LEVEL="ERROR"
        )

        self.assertEqual(main_log[0], "DEBUG: plain debug")

    def test_lines_carry_a_timestamp_and_the_logger_does_not_propagate(self):
        log_dir = helpers.make_temp_dir(self, "fetch_torrents_routing_")
        stream_handler, file_handler, _ = configure_logging_for_test(self, log_dir)
        stream_handler.setStream(io.StringIO())

        ft.logger.warning("plain warning")
        file_handler.flush()

        with open(os.path.join(log_dir, "fetch_torrents.log"), encoding="utf-8") as f:
            self.assertRegex(
                f.read(),
                r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} WARNING: plain warning\n$",
            )
        self.assertFalse(ft.logger.propagate)


class LogSeedRatiosViaHttpTests(unittest.TestCase):
    """log_seed_ratios_via_http() must not hang the daily run forever on a
    stalled Transmission response, and must authenticate with whatever
    credentials configure_transmission.py configured the daemon with when
    the caller doesn't explicitly override auth."""

    def setUp(self):
        self.transmission = helpers.FakeTransmission()
        self.rpc = helpers.FakeTransmissionRpc(self.transmission)
        patcher = unittest.mock.patch.object(ft.requests, "post", self.rpc.post)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_requests_follow_the_transmission_rpc_protocol(self):
        # FakeTransmissionRpc checks the method and torrent-get fields
        # against the pinned transmission_rpc's own tables, which stand in
        # for the RPC spec, so a renamed field fails here.
        ft.log_seed_ratios_via_http(auth=("alice", "hunter2"))

        self.assertEqual(
            self.rpc.calls,
            [
                unittest.mock.call(
                    "http://localhost:9091/transmission/rpc", timeout=15
                ),
                unittest.mock.call(
                    "http://localhost:9091/transmission/rpc",
                    json={
                        "method": "torrent-get",
                        "arguments": {"fields": ["name", "uploadRatio"]},
                    },
                    headers={"X-Transmission-Session-Id": "sid"},
                    auth=("alice", "hunter2"),
                    timeout=15,
                ),
            ],
        )

    def test_logs_ratios_highest_first_with_none_as_zero(self):
        self.transmission.torrents = [
            helpers.FakeTorrent("low.iso", 1, ratio=0.5),
            helpers.FakeTorrent("unset.iso", 2, ratio=None),
            helpers.FakeTorrent("high.iso", 3, ratio=2.25),
        ]
        with self.assertLogs(ft.logger, level="INFO") as logs:
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

    def test_uses_configured_credentials_when_auth_not_explicitly_passed(self):
        with unittest.mock.patch.dict(
            os.environ,
            {
                "TRANSMISSION_RPC_USERNAME": "alice",
                "TRANSMISSION_RPC_PASSWORD": "hunter2",
            },
        ):
            ft.log_seed_ratios_via_http()

        self.assertEqual(self.rpc.auths, [("alice", "hunter2")])

    def test_no_auth_when_credentials_unset(self):
        with helpers.isolated_env():
            ft.log_seed_ratios_via_http()

        self.assertEqual(self.rpc.auths, [None])

    def test_explicit_auth_argument_still_wins(self):
        with unittest.mock.patch.dict(
            os.environ,
            {
                "TRANSMISSION_RPC_USERNAME": "alice",
                "TRANSMISSION_RPC_PASSWORD": "hunter2",
            },
        ):
            ft.log_seed_ratios_via_http(auth=("bob", "other"))

        self.assertEqual(self.rpc.auths, [("bob", "other")])


class RpcCredentialFallbackTests(unittest.TestCase):
    """Without an explicit auth, log_seed_ratios_via_http() authenticates
    only when both TRANSMISSION_RPC_USERNAME and _PASSWORD are set."""

    def _auth_sent(self, **env):
        rpc = helpers.FakeTransmissionRpc(helpers.FakeTransmission())
        with (
            helpers.isolated_env(**env),
            unittest.mock.patch.object(ft.requests, "post", rpc.post),
        ):
            ft.log_seed_ratios_via_http()
        (auth,) = rpc.auths
        return auth

    def test_username_without_password_sends_no_auth(self):
        self.assertIsNone(self._auth_sent(TRANSMISSION_RPC_USERNAME="alice"))

    def test_password_without_username_sends_no_auth(self):
        self.assertIsNone(self._auth_sent(TRANSMISSION_RPC_PASSWORD="hunter2"))


if __name__ == "__main__":
    unittest.main()
