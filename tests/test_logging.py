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
    testcase.addCleanup(ft.reset_logging)
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


class ResetLoggingTests(unittest.TestCase):
    """reset_logging() undoes configure_logging(), so a test (or anything
    else that configured logging in-process) can put the logger back the
    way importing the module left it."""

    def test_closes_the_handlers_and_leaves_the_logger_as_imported(self):
        log_dir = helpers.make_temp_dir(self, "fetch_torrents_reset_")
        self.addCleanup(ft.reset_logging)
        stream_handler, file_handler, ratio_handler = ft.configure_logging(
            log_dir, env={}
        )
        stream_handler.setStream(io.StringIO())
        ft.logger.info("[ratio] RATIOS START")

        ft.reset_logging()
        ft.logger.warning("after the reset")

        self.assertEqual([type(h) for h in ft.logger.handlers], [logging.NullHandler])
        self.assertEqual((ft.logger.level, ft.logger.propagate), (logging.NOTSET, True))
        self.assertIsNone(file_handler.stream)
        self.assertIsNone(ratio_handler.stream)
        with open(os.path.join(log_dir, "fetch_torrents.log"), encoding="utf-8") as f:
            self.assertNotIn("after the reset", f.read())

    def test_a_later_configure_logging_starts_from_scratch(self):
        log_dir = helpers.make_temp_dir(self, "fetch_torrents_reset_")
        self.addCleanup(ft.reset_logging)
        ft.configure_logging(log_dir, env={})
        ft.reset_logging()

        handlers = ft.configure_logging(log_dir, env={})

        self.assertEqual(ft.logger.handlers, list(handlers))


class LoggerNameTests(unittest.TestCase):
    def test_the_module_logs_under_the_fetch_torrents_name(self):
        # So logging can be configured by name from outside the module.
        self.assertIs(logging.getLogger("fetch_torrents"), ft.logger)


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
    stalled Transmission response, and must authenticate with exactly the
    auth its caller passes (the run's own credential handling is tested in
    test_daily_run.py)."""

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
                    "http://localhost:9091/transmission/rpc",
                    auth=("alice", "hunter2"),
                    timeout=15,
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

    def test_authenticates_against_a_daemon_that_requires_credentials(self):
        # The daemon answers 401, with no session id, to any request
        # without the right credentials, the handshake included.
        self.rpc.credentials = ("alice", "hunter2")
        self.transmission.torrents = [helpers.FakeTorrent("a.iso", 1, ratio=1.5)]
        with self.assertLogs(ft.logger, level="INFO") as logs:
            ft.log_seed_ratios_via_http(auth=("alice", "hunter2"))

        self.assertIn(f"[ratio] {'a.iso':<50} → 1.500", logs.output[-3])

    def test_a_login_the_daemon_requires_but_was_not_sent_says_how_to_fix_it(self):
        # A 401 carries no session id: report the login, not a KeyError.
        self.rpc.credentials = ("alice", "hunter2")

        with self.assertRaises(ft.RpcRefusedError) as raised:
            ft.log_seed_ratios_via_http(auth=None)

        self.assertEqual(
            str(raised.exception),
            "Transmission requires an RPC login and none was sent. Set both "
            "TRANSMISSION_RPC_USERNAME and TRANSMISSION_RPC_PASSWORD to the "
            "daemon's login (rpc-username/rpc-password in settings.json), or "
            "turn its rpc-authentication-required off.",
        )

    def test_a_rejected_login_names_the_user_but_not_the_password(self):
        self.rpc.credentials = ("alice", "hunter2")

        with self.assertRaises(ft.RpcRefusedError) as raised:
            ft.log_seed_ratios_via_http(auth=("alice", "wrong-password"))

        self.assertEqual(
            str(raised.exception),
            "Transmission rejected the RPC login for user 'alice'. "
            "TRANSMISSION_RPC_USERNAME/TRANSMISSION_RPC_PASSWORD must match the "
            "daemon's rpc-username/rpc-password in settings.json.",
        )
        self.assertEqual(len(self.rpc.calls), 1)

    def test_a_connection_off_the_whitelist_says_localhost_is_missing(self):
        # Transmission's rpc-whitelist replaces its localhost default, and
        # refuses anything off it with a 403 before checking the login.
        self.rpc.address_allowed = False

        with self.assertRaises(ft.RpcRefusedError) as raised:
            ft.log_seed_ratios_via_http(auth=None)

        self.assertEqual(
            str(raised.exception),
            "Transmission refused this script's RPC connection from localhost "
            "(403 Forbidden): rpc-whitelist in settings.json must include "
            "127.0.0.1. Setting TRANSMISSION_RPC_WHITELIST adds it on the next "
            "container start.",
        )
        self.assertEqual(len(self.rpc.calls), 1)

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

    def test_none_auth_sends_no_credentials_even_if_the_env_has_them(self):
        # The run passes config.rpc_auth, read once by load_config(); None
        # means "no auth", not "go back to os.environ".
        with unittest.mock.patch.dict(
            os.environ,
            {
                "TRANSMISSION_RPC_USERNAME": "alice",
                "TRANSMISSION_RPC_PASSWORD": "hunter2",
            },
        ):
            ft.log_seed_ratios_via_http(auth=None)

        self.assertEqual([c.kwargs["auth"] for c in self.rpc.calls], [None, None])


if __name__ == "__main__":
    unittest.main()
