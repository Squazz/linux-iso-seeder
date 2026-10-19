"""Tests for the daily run's configuration and value types: load_config()
and Config, parse_bool(), make_client_factory(), RunSummary and
format_run_summary().

Run with: python -m unittest discover -s tests
"""

import dataclasses
import logging
import unittest
import unittest.mock

import helpers

import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


class FormatRunSummaryTests(unittest.TestCase):
    """format_run_summary() builds the single end-of-run log line - it must
    surface how many old-release torrents FETCH_TORRENTS_CHECK_OLD_RELEASES
    introduced, not just the counts from the normal latest-release fetch."""

    def test_without_old_release_check(self):
        summary = ft.format_run_summary(
            elapsed=12.5,
            success_count=3,
            existing_count=1,
            not_found_count=0,
            failure_count=0,
        )
        self.assertEqual(
            summary,
            "Run complete in 12.50 seconds. 3 added, 1 existing, 0 not found upstream, 0 failed.",
        )

    def test_with_old_release_check_appends_counts(self):
        summary = ft.format_run_summary(
            elapsed=12.5,
            success_count=3,
            existing_count=1,
            not_found_count=0,
            failure_count=0,
            old_added=2,
            old_skipped=6,
        )
        self.assertEqual(
            summary,
            "Run complete in 12.50 seconds. 3 added, 1 existing, 0 not found upstream, 0 failed. "
            "Old releases (FETCH_TORRENTS_CHECK_OLD_RELEASES): 2 added, 6 skipped.",
        )

    def test_is_let_through_by_the_always_log_filter(self):
        summary = ft.format_run_summary(
            elapsed=1.0,
            success_count=0,
            existing_count=0,
            not_found_count=0,
            failure_count=0,
            old_added=0,
            old_skipped=0,
        )
        record = logging.LogRecord(
            "fetch_torrents", logging.INFO, __file__, 0, summary, None, None
        )
        always_log = ft.ImportantMessageFilter(
            logging.ERROR, ft.get_always_log_prefixes()
        )

        self.assertIs(always_log.filter(record), True)


class LoadConfigTests(unittest.TestCase):
    """load_config() is the one place the daily run reads its environment:
    each env var must land on the right field, and a bad number must be
    deferred (recorded, then raised by require()) rather than crash the
    whole run up front."""

    def test_empty_env_gives_the_documented_defaults(self):
        self.assertEqual(ft.load_config({}), ft.Config())
        self.assertEqual(
            ft.Config(),
            ft.Config(
                distros=("ubuntu", "debian", "kali", "mint", "fedora"),
                include_low_demand=False,
                skip_ratio_check=False,
                check_old_releases=False,
                old_release_min_leechers=10,
                old_release_min_leecher_ratio=0.1,
                old_release_allow_zero_seeders=False,
                old_release_recheck_days=7,
                old_release_skip_removed=True,
                cleanup_keep_only_latest=False,
                cleanup_skip_ratio_check=False,
                cleanup_min_ratio=1.0,
                stagnation_window_days=30,
                stagnation_min_ratio_delta=0.02,
                disk_usage_threshold_percent=95.0,
                rpc_username=None,
                rpc_password=None,
                invalid={},
            ),
        )

    def test_each_env_var_sets_its_field(self):
        config = ft.load_config(
            {
                "FETCH_TORRENTS_DISTROS": "devuan, arch",
                "FETCH_TORRENTS_INCLUDE_LOW_DEMAND": "true",
                "SKIP_RATIO_CHECK": "yes",
                "FETCH_TORRENTS_CHECK_OLD_RELEASES": "1",
                "FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHERS": "3",
                "FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHER_RATIO": "0.5",
                "FETCH_TORRENTS_OLD_RELEASE_ALLOW_ZERO_SEEDERS": "true",
                "FETCH_TORRENTS_OLD_RELEASE_RECHECK_DAYS": "2",
                "FETCH_TORRENTS_OLD_RELEASE_SKIP_REMOVED": "false",
                "CLEANUP_KEEP_ONLY_LATEST_VERSION": "true",
                "CLEANUP_SKIP_RATIO_CHECK": "true",
                "CLEANUP_MIN_RATIO": "1.5",
                "CLEANUP_STAGNATION_WINDOW_DAYS": "14",
                "CLEANUP_STAGNATION_MIN_RATIO_DELTA": "0.1",
                "CLEANUP_DISK_USAGE_THRESHOLD_PERCENT": "80",
                "TRANSMISSION_RPC_USERNAME": " alice ",
                "TRANSMISSION_RPC_PASSWORD": "hunter2",
            }
        )

        self.assertEqual(
            config,
            ft.Config(
                # In the order the distros are known, not as listed.
                distros=("arch", "devuan"),
                include_low_demand=True,
                skip_ratio_check=True,
                check_old_releases=True,
                old_release_min_leechers=3,
                old_release_min_leecher_ratio=0.5,
                old_release_allow_zero_seeders=True,
                old_release_recheck_days=2,
                old_release_skip_removed=False,
                cleanup_keep_only_latest=True,
                cleanup_skip_ratio_check=True,
                cleanup_min_ratio=1.5,
                stagnation_window_days=14,
                stagnation_min_ratio_delta=0.1,
                disk_usage_threshold_percent=80.0,
                rpc_username="alice",
                rpc_password="hunter2",
            ),
        )

    def test_reads_only_the_env_it_is_given(self):
        with helpers.isolated_env(SKIP_RATIO_CHECK="true", CLEANUP_MIN_RATIO="9"):
            config = ft.load_config({})

        self.assertFalse(config.skip_ratio_check)
        self.assertEqual(config.cleanup_min_ratio, 1.0)

    def test_invalid_number_is_recorded_not_raised(self):
        config = ft.load_config(
            {"CLEANUP_MIN_RATIO": "high", "CLEANUP_STAGNATION_WINDOW_DAYS": "1.5"}
        )

        self.assertIsNone(config.cleanup_min_ratio)
        self.assertIsNone(config.stagnation_window_days)
        # Only the env var prefix is this project's; the rest is Python's
        # own float()/int() error text.
        self.assertEqual(
            sorted(config.invalid), ["cleanup_min_ratio", "stagnation_window_days"]
        )
        self.assertRegex(config.invalid["cleanup_min_ratio"], r"^CLEANUP_MIN_RATIO: ")
        self.assertRegex(
            config.invalid["stagnation_window_days"],
            r"^CLEANUP_STAGNATION_WINDOW_DAYS: ",
        )

    def test_require_raises_the_first_invalid_field_named(self):
        config = ft.load_config({"CLEANUP_MIN_RATIO": "high"})

        config.require("stagnation_window_days")  # valid: no error
        with self.assertRaisesRegex(ValueError, "^CLEANUP_MIN_RATIO: "):
            config.require("stagnation_window_days", "cleanup_min_ratio")

    def test_rpc_auth_needs_both_username_and_password(self):
        cases = (
            ({}, None),
            ({"TRANSMISSION_RPC_USERNAME": "alice"}, None),
            ({"TRANSMISSION_RPC_PASSWORD": "hunter2"}, None),
            (
                {
                    "TRANSMISSION_RPC_USERNAME": "alice",
                    "TRANSMISSION_RPC_PASSWORD": "  ",
                },
                None,
            ),
            (
                {
                    "TRANSMISSION_RPC_USERNAME": "alice",
                    "TRANSMISSION_RPC_PASSWORD": "hunter2",
                },
                ("alice", "hunter2"),
            ),
        )
        for env, expected in cases:
            with self.subTest(env=env):
                self.assertEqual(ft.load_config(env).rpc_auth, expected)


class MakeClientFactoryTests(unittest.TestCase):
    """The daily run's own Transmission connections (cleanup, disk-usage
    limit) must authenticate the same way configure_transmission.py
    configured the daemon. Without this, a user who sets
    TRANSMISSION_RPC_USERNAME/PASSWORD (as the README requires once
    TRANSMISSION_RPC_WHITELIST is widened beyond localhost) finds cleanup
    silently stops working forever: every RPC call fails with 401 and the
    failure is only logged, never surfaced."""

    def _connect(self, env):
        config = ft.load_config(env)
        with unittest.mock.patch.object(ft, "Client", autospec=True) as client_cls:
            client = ft.make_client_factory(config)()
        return client_cls, client

    def test_passes_configured_credentials(self):
        client_cls, client = self._connect(
            {
                "TRANSMISSION_RPC_USERNAME": "alice",
                "TRANSMISSION_RPC_PASSWORD": "hunter2",
            }
        )

        client_cls.assert_called_once_with(
            host="localhost", port=9091, username="alice", password="hunter2"
        )
        self.assertIs(client, client_cls.return_value)

    def test_passes_no_credentials_when_unset(self):
        client_cls, _client = self._connect({})

        client_cls.assert_called_once_with(
            host="localhost", port=9091, username=None, password=None
        )

    def test_blank_credentials_count_as_unset(self):
        client_cls, _client = self._connect(
            {"TRANSMISSION_RPC_USERNAME": "  ", "TRANSMISSION_RPC_PASSWORD": ""}
        )

        client_cls.assert_called_once_with(
            host="localhost", port=9091, username=None, password=None
        )

    def test_factory_connects_only_when_called(self):
        with unittest.mock.patch.object(ft, "Client", autospec=True) as client_cls:
            factory = ft.make_client_factory(ft.load_config({}))

        client_cls.assert_not_called()
        self.assertTrue(callable(factory))


class ParseBoolTests(unittest.TestCase):
    def test_unset_is_false_by_default(self):
        self.assertIs(ft.parse_bool("X", env={}), False)

    def test_unset_or_blank_uses_the_given_default(self):
        for value in ({}, {"X": "  "}):
            with self.subTest(env=value):
                self.assertIs(ft.parse_bool("X", default=True, env=value), True)

    def test_truthy_and_falsy_spellings(self):
        for value in ("1", "true", "YES", " On "):
            with self.subTest(value=value):
                self.assertIs(ft.parse_bool("X", env={"X": value}), True)
        for value in ("0", "false", "no", "off", "maybe"):
            with self.subTest(value=value):
                self.assertIs(ft.parse_bool("X", default=True, env={"X": value}), False)


class RunValueTypesTests(unittest.TestCase):
    def test_run_summary_starts_at_zero_with_no_old_release_counts(self):
        self.assertEqual(
            ft.RunSummary(),
            ft.RunSummary(
                elapsed=0.0,
                added=0,
                existing=0,
                not_found=0,
                failed=0,
                old_added=None,
                old_skipped=None,
            ),
        )

    def test_config_is_immutable(self):
        # run() and its steps share one Config; none may change it for the
        # steps after it.
        config = ft.Config()

        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.skip_ratio_check = True  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
