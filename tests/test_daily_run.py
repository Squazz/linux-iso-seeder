"""Tests for the daily run: fetch_torrents.run() and the `__main__` wiring
around it.

RunTests call run() directly with everything external faked at its
boundary: HTTP (ft.requests.get/post), the Transmission client (a
client_factory returning helpers.FakeTransmission), the RPC port check
(socket.create_connection), disk usage and the clock. State files live in a
per-test temp dir.

MainWiringTests runs the script via runpy exactly as the container does, to
check that `__main__` sets up logging, reads the config and calls run().

Run with: python -m unittest discover -s tests
"""

import contextlib
import io
import json
import logging
import os
import runpy
import shutil
import socket
import sys
import unittest
import unittest.mock
from datetime import date
from unittest.mock import MagicMock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "fetch_torrents.py")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import helpers

import fetch_torrents as ft


def setUpModule():
    unittest.addModuleCleanup(helpers.block_network())


UBUNTU_META = (
    "Dist: jammy\nName: Jammy Jellyfish\nVersion: 22.04 LTS\nSupported: 0\n\n"
    "Dist: noble\nName: Noble Numbat\nVersion: 24.04 LTS\nSupported: 1\n"
)
UBUNTU = "https://releases.ubuntu.com/noble/"
LUBUNTU = "https://cdimage.ubuntu.com/lubuntu/releases/noble/release/"
XUBUNTU = "https://torrent.ubuntu.com/xubuntu/releases/noble/release/"
ARCH_RELEASES = "https://archlinux.org/releng/releases/"
ARCH_HTML = (
    "<html><body><table id='release-table'>"
    "<tr><td class='available-yes'></td>"
    "<td><a href='/releng/releases/2026.09.01/torrent/'>t</a></td></tr>"
    "</table></body></html>"
)
ARCH_TORRENT = "https://archlinux.org/releng/releases/2026.09.01/torrent/"


def torrent(name, id_, ratio):
    return helpers.FakeTorrent(name, id_, ratio=ratio)


class FakeWorld:
    """HTTP routes, a Transmission daemon and a disk, all in memory."""

    def __init__(self, testcase):
        self.state_dir = helpers.make_temp_dir(testcase, "daily_run_state_")
        self.watch_dir = helpers.make_temp_dir(testcase, "daily_run_watch_")
        self.routes = {}
        self.requested = []
        self.events = []
        self.transmission = helpers.FakeTransmission()
        self.disk_used_percent = 10

    def get(self, url, timeout=None):
        self.requested.append(url)
        route = self.routes.get(url)
        if route is None:
            return helpers.fake_response(status=404)
        if isinstance(route, Exception):
            raise route
        return route

    def post(self, url, **kwargs):
        if kwargs.get("json") is None:  # the session-id handshake
            return helpers.fake_response(headers={"X-Transmission-Session-Id": "sid"})
        torrents = [
            {"name": t.name, "uploadRatio": t.ratio} for t in self.transmission.torrents
        ]
        return helpers.fake_response(json.dumps({"arguments": {"torrents": torrents}}))

    def connect(self):
        self.events.append("connect")
        return self.transmission

    def disk_usage(self, path):
        self.events.append("disk_usage")
        total = 100 * 2**30
        used = total * self.disk_used_percent // 100
        return (total, used, total - used)

    def state_path(self, name):
        return os.path.join(self.state_dir, name)

    def write_ratio_log(self, ratios):
        with open(
            self.state_path("fetch_torrents_ratios.log"), "w", encoding="utf-8"
        ) as f:
            f.write("2026-08-01 00:00:00,000 INFO: [ratio] RATIOS START\n")
            f.writelines(
                f"2026-08-01 00:00:00,000 INFO: [ratio] {name} → {ratio:.3f}\n"
                for name, ratio in ratios.items()
            )
            f.write("2026-08-01 00:00:00,000 INFO: [ratio] RATIOS END\n")

    def route_ubuntu(self):
        self.routes.update(
            {
                "https://changelogs.ubuntu.com/meta-release-lts": helpers.fake_response(
                    UBUNTU_META
                ),
                UBUNTU
                + "ubuntu-24.04-desktop-amd64.iso.torrent": helpers.fake_response(
                    b"d1"
                ),
                # live-server: not routed -> 404
                LUBUNTU
                + "lubuntu-24.04-desktop-amd64.iso.torrent": helpers.fake_response(
                    status=500
                ),
                XUBUNTU
                + "desktop/xubuntu-24.04-desktop-amd64.iso.torrent": helpers.fake_response(
                    b"x1"
                ),
                XUBUNTU
                + "minimal/xubuntu-24.04-minimal-amd64.iso.torrent": helpers.fake_response(
                    b"x2"
                ),
            }
        )
        with open(
            os.path.join(self.watch_dir, "xubuntu-24.04-minimal-amd64.iso.torrent"),
            "wb",
        ) as f:
            f.write(b"already here")

    def route_arch(self):
        self.routes.update(
            {
                ARCH_RELEASES: helpers.fake_response(ARCH_HTML),
                ARCH_TORRENT: helpers.fake_response(b"a1"),
            }
        )


class RunTests(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld(self)
        patches = [
            unittest.mock.patch.object(ft.requests, "get", self.world.get),
            unittest.mock.patch.object(ft.requests, "post", self.world.post),
            unittest.mock.patch.object(
                ft.socket, "create_connection", self._rpc_port_open
            ),
            unittest.mock.patch.object(ft, "watch_dir", self.world.watch_dir),
        ]
        for attr, filename in (
            ("ratio_log_file", "fetch_torrents_ratios.log"),
            ("ratio_history_file", "fetch_torrents_ratio_history.json"),
            ("removed_history_file", "fetch_torrents_removed_history.json"),
            (
                "old_release_check_state_file",
                "fetch_torrents_old_release_check_state.json",
            ),
        ):
            patches.append(
                unittest.mock.patch.object(ft, attr, self.world.state_path(filename))
            )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    @contextlib.contextmanager
    def _rpc_port_open(*args, **kwargs):
        yield MagicMock()

    def _run(self, **env):
        """Runs ft.run() with load_config(env); returns (summary, messages)."""
        with self.assertLogs(ft.logger, level="DEBUG") as logs:
            summary = ft.run(
                ft.load_config(env),
                client_factory=self.world.connect,
                today=date(2026, 9, 2),
                now=lambda: 1000.0,
                disk_usage=self.world.disk_usage,
            )
        return summary, [record.getMessage() for record in logs.records]

    def test_counts_each_download_outcome(self):
        self.world.route_ubuntu()

        summary, messages = self._run(FETCH_TORRENTS_DISTROS="ubuntu")

        self.assertEqual(
            sorted(os.listdir(self.world.watch_dir)),
            [
                "ubuntu-24.04-desktop-amd64.iso.torrent",
                "xubuntu-24.04-desktop-amd64.iso.torrent",
                "xubuntu-24.04-minimal-amd64.iso.torrent",
            ],
        )
        self.assertEqual(
            summary,
            ft.RunSummary(elapsed=0.0, added=2, existing=1, not_found=1, failed=1),
        )
        self.assertEqual(
            messages[-1],
            "Run complete in 0.00 seconds. 2 added, 1 existing, "
            "1 not found upstream, 1 failed.",
        )

    def test_distros_not_selected_are_never_fetched(self):
        self.world.route_ubuntu()
        self.world.route_arch()

        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertEqual(self.world.requested, [ARCH_RELEASES, ARCH_TORRENT])

    def test_low_previous_ratio_blocks_the_new_release(self):
        self.world.route_arch()
        self.world.write_ratio_log({"archlinux-2026.08.01": 0.4})

        _summary, messages = self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertNotIn(ARCH_TORRENT, self.world.requested)
        self.assertIn(
            "Skipping archlinux-2026.09.01 due to low ratio on previous version.",
            messages,
        )
        self.assertEqual(os.listdir(self.world.watch_dir), [])

    def test_previous_ratio_at_the_floor_allows_the_new_release(self):
        self.world.route_arch()
        self.world.write_ratio_log({"archlinux-2026.08.01": 1.0})

        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertEqual(
            os.listdir(self.world.watch_dir), ["archlinux-2026.09.01.torrent"]
        )

    def test_skip_ratio_check_fetches_despite_a_low_previous_ratio(self):
        self.world.route_arch()
        self.world.write_ratio_log({"archlinux-2026.08.01": 0.4})

        self._run(FETCH_TORRENTS_DISTROS="arch", SKIP_RATIO_CHECK="true")

        self.assertEqual(
            os.listdir(self.world.watch_dir), ["archlinux-2026.09.01.torrent"]
        )

    def test_a_failing_distro_does_not_stop_the_others(self):
        self.world.route_arch()
        self.world.routes["https://changelogs.ubuntu.com/meta-release-lts"] = (
            ConnectionError("down")
        )

        summary, _messages = self._run(FETCH_TORRENTS_DISTROS="ubuntu,arch")

        self.assertEqual(
            os.listdir(self.world.watch_dir), ["archlinux-2026.09.01.torrent"]
        )
        self.assertEqual((summary.added, summary.failed), (1, 1))

    def test_custom_fetchers_replace_the_default_set(self):
        summary = ft.run(
            ft.load_config({"FETCH_TORRENTS_DISTROS": "arch"}),
            client_factory=self.world.connect,
            today=date(2026, 9, 2),
            now=lambda: 1000.0,
            disk_usage=self.world.disk_usage,
            fetchers=(("arch", lambda: {"archlinux-2026.10.01": ARCH_TORRENT}),),
        )

        self.assertEqual(self.world.requested, [ARCH_TORRENT])
        self.assertEqual(summary.not_found, 1)

    def test_keep_only_latest_selects_the_old_version_cleanup(self):
        self.world.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 2.0),
        ]

        self._run(
            FETCH_TORRENTS_DISTROS="arch", CLEANUP_KEEP_ONLY_LATEST_VERSION="true"
        )

        self.assertEqual(
            self.world.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"]
        )

    def test_keep_only_latest_honors_min_ratio(self):
        self.world.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 2.0),
        ]

        self._run(
            FETCH_TORRENTS_DISTROS="arch",
            CLEANUP_KEEP_ONLY_LATEST_VERSION="true",
            CLEANUP_MIN_RATIO="3",
        )

        self.assertEqual(len(self.world.transmission.torrents), 2)

    def test_default_cleanup_is_stagnation_based(self):
        # No ratio history yet, so the stagnation cleanup can't judge the old
        # version and keeps it - unlike keep-only-latest, which removes it.
        self.world.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 2.0),
        ]

        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertEqual(len(self.world.transmission.torrents), 2)
        self.assertEqual(
            ft.load_ratio_history(ft.ratio_history_file),
            {
                "ubuntu-24.04-desktop-amd64.iso": [
                    {"date": "2026-09-02", "ratio": 2.0}
                ],
                "ubuntu-23.10-desktop-amd64.iso": [
                    {"date": "2026-09-02", "ratio": 2.0}
                ],
            },
        )

    def test_invalid_cleanup_setting_skips_cleanup_and_continues(self):
        self.world.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 2.0),
        ]

        _summary, messages = self._run(
            FETCH_TORRENTS_DISTROS="arch",
            CLEANUP_KEEP_ONLY_LATEST_VERSION="true",
            CLEANUP_MIN_RATIO="high",
        )

        self.assertEqual(len(self.world.transmission.torrents), 2)
        self.assertIn(
            "Could not clean up old versions: CLEANUP_MIN_RATIO: could not "
            "convert string to float: 'high'",
            messages,
        )
        self.assertTrue(messages[-1].startswith("Run complete in"))

    def test_disk_usage_limit_runs_after_cleanup(self):
        self.world.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 0.1),
        ]
        self.world.disk_used_percent = 99

        self._run(
            FETCH_TORRENTS_DISTROS="arch", CLEANUP_DISK_USAGE_THRESHOLD_PERCENT="95"
        )

        events = self.world.events
        cleanup_connect = events.index("connect")
        first_disk_check = events.index("disk_usage")
        self.assertLess(cleanup_connect, first_disk_check)
        self.assertEqual(
            self.world.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"]
        )

    def test_disk_usage_limit_error_is_logged_not_raised(self):
        _summary, messages = self._run(
            FETCH_TORRENTS_DISTROS="arch", CLEANUP_DISK_USAGE_THRESHOLD_PERCENT="lots"
        )

        self.assertIn(
            "Could not enforce disk usage limit: "
            "CLEANUP_DISK_USAGE_THRESHOLD_PERCENT: could not convert string to "
            "float: 'lots'",
            messages,
        )
        self.assertTrue(messages[-1].startswith("Run complete in"))

    def test_rpc_unavailable_skips_ratio_logging_but_still_cleans_up(self):
        def refuse(*args, **kwargs):
            raise ConnectionRefusedError

        self.world.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 2.0),
        ]
        with (
            unittest.mock.patch.object(
                ft, "wait_for_transmission_rpc", return_value=False
            ),
            unittest.mock.patch.object(ft.socket, "create_connection", refuse),
        ):
            _summary, messages = self._run(
                FETCH_TORRENTS_DISTROS="arch", CLEANUP_KEEP_ONLY_LATEST_VERSION="true"
            )

        self.assertIn(
            "Transmission RPC not available on localhost:9091; skipping ratio logs.",
            messages,
        )
        self.assertFalse(any(m.startswith("[ratio]") for m in messages))
        self.assertEqual(
            self.world.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"]
        )

    def test_seed_ratios_are_logged_for_the_next_run(self):
        self.world.transmission.torrents = [torrent("archlinux-2026.08.01", 1, 0.664)]

        _summary, messages = self._run(FETCH_TORRENTS_DISTROS="arch")

        start = messages.index("[ratio] RATIOS START")
        self.assertEqual(
            messages[start : start + 3],
            [
                "[ratio] RATIOS START",
                f"[ratio] {'archlinux-2026.08.01':<50} → 0.664",
                "[ratio] RATIOS END",
            ],
        )

    def test_rpc_credentials_from_config_are_used_for_ratio_logging(self):
        with unittest.mock.patch.object(ft, "log_seed_ratios_via_http") as log_ratios:
            self._run(
                FETCH_TORRENTS_DISTROS="arch",
                TRANSMISSION_RPC_USERNAME="alice",
                TRANSMISSION_RPC_PASSWORD="hunter2",
            )

        log_ratios.assert_called_once_with(auth=("alice", "hunter2"))

    def test_old_release_check_runs_only_when_enabled(self):
        with unittest.mock.patch.object(
            ft, "check_old_releases_for_demand", return_value=(2, 3, {"x": "y"})
        ) as check:
            disabled, _ = self._run(FETCH_TORRENTS_DISTROS="arch")
            check.assert_not_called()

            enabled, messages = self._run(
                FETCH_TORRENTS_DISTROS="arch",
                FETCH_TORRENTS_CHECK_OLD_RELEASES="true",
                FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHERS="4",
            )

        self.assertEqual((disabled.old_added, disabled.old_skipped), (None, None))
        self.assertEqual((enabled.old_added, enabled.old_skipped), (2, 3))
        self.assertEqual(check.call_args.args[2], 4)
        self.assertEqual(check.call_args.args[7], date(2026, 9, 2))
        self.assertEqual(
            ft.load_old_release_check_state(ft.old_release_check_state_file),
            {"x": "y"},
        )
        self.assertTrue(
            messages[-1].endswith(
                "Old releases (FETCH_TORRENTS_CHECK_OLD_RELEASES): 2 added, 3 skipped."
            )
        )

    def test_invalid_old_release_setting_aborts_the_run(self):
        # Unlike cleanup and the disk limit, the old-release check has never
        # been guarded - a bad value fails the run at that point.
        with self.assertRaisesRegex(
            ValueError, "FETCH_TORRENTS_OLD_RELEASE_RECHECK_DAYS"
        ):
            self._run(
                FETCH_TORRENTS_DISTROS="arch",
                FETCH_TORRENTS_CHECK_OLD_RELEASES="true",
                FETCH_TORRENTS_OLD_RELEASE_RECHECK_DAYS="weekly",
            )


class MainWiringTests(unittest.TestCase):
    """`python fetch_torrents.py` must configure logging (so this run's ratio
    log is written for the next run to gate on), load the config from the
    environment and call run() with a real Transmission client factory."""

    def test_running_the_script_performs_a_daily_run(self):
        world = FakeWorld(self)
        world.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 2.0),
        ]
        log_dir = helpers.make_temp_dir(self, "daily_run_main_logs_")
        logger = logging.getLogger("fetch_torrents")
        handlers_before = list(logger.handlers)

        @contextlib.contextmanager
        def rpc_port_open(*args, **kwargs):
            yield MagicMock()

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                helpers.isolated_env(
                    FETCH_TORRENTS_LOG_DIR=log_dir,
                    FETCH_TORRENTS_DISTROS="arch",
                    CLEANUP_KEEP_ONLY_LATEST_VERSION="true",
                    TRANSMISSION_RPC_USERNAME="alice",
                    TRANSMISSION_RPC_PASSWORD="hunter2",
                )
            )
            stack.enter_context(unittest.mock.patch("requests.get", world.get))
            stack.enter_context(unittest.mock.patch("requests.post", world.post))
            client_cls = stack.enter_context(
                unittest.mock.patch.object(
                    sys.modules["transmission_rpc"],
                    "Client",
                    side_effect=lambda **kwargs: world.transmission,
                )
            )
            stack.enter_context(
                unittest.mock.patch.object(socket, "create_connection", rpc_port_open)
            )
            stack.enter_context(
                unittest.mock.patch.object(shutil, "disk_usage", world.disk_usage)
            )
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            logs = stack.enter_context(self.assertLogs(logger, level="DEBUG"))
            try:
                runpy.run_path(SCRIPT, run_name="__main__")
            finally:
                # assertLogs puts the logger's original handlers back on exit,
                # dropping the ones configure_logging() added - close them.
                for handler in logger.handlers:
                    if isinstance(handler, logging.FileHandler):
                        handler.close()
        self.assertEqual(logger.handlers, handlers_before)

        messages = [record.getMessage() for record in logs.records]
        self.assertIn("Selected distros for this run: arch", messages)
        self.assertTrue(messages[-1].startswith("Run complete in"))
        client_cls.assert_called_with(
            host="localhost", port=9091, username="alice", password="hunter2"
        )
        self.assertEqual(world.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])
        self.assertEqual(
            ft.get_previous_ratios(os.path.join(log_dir, "fetch_torrents_ratios.log")),
            {
                "ubuntu-24.04-desktop-amd64.iso": 2.0,
                "ubuntu-23.10-desktop-amd64.iso": 2.0,
            },
        )
        self.assertTrue(os.path.exists(os.path.join(log_dir, "fetch_torrents.log")))


if __name__ == "__main__":
    unittest.main()
