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

import helpers

import fetch_torrents as ft

SCRIPT = os.path.join(helpers.REPO_ROOT, "fetch_torrents.py")


def setUpModule():
    helpers.isolate_module()


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
        self.rpc_auths = []
        self.disk_used_percent = 10
        self.disk_paths = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        route = self.routes.get(url)
        if route is None:
            return helpers.fake_response(status=404)
        if isinstance(route, Exception):
            raise route
        return route

    def post(self, url, **kwargs):
        """Transmission's RPC: a request without the session id is refused
        with a 409 carrying it; a torrent-get with it records its auth and
        lists what `transmission` holds."""
        headers = kwargs.get("headers") or {}
        if headers.get("X-Transmission-Session-Id") != "sid":
            return helpers.fake_response(
                status=409, headers={"X-Transmission-Session-Id": "sid"}
            )
        self.rpc_auths.append(kwargs.get("auth"))
        torrents = [
            {"name": t.name, "uploadRatio": t.ratio} for t in self.transmission.torrents
        ]
        return helpers.fake_response(json.dumps({"arguments": {"torrents": torrents}}))

    def connect(self):
        self.events.append("connect")
        return self.transmission

    def disk_usage(self, path):
        self.events.append("disk_usage")
        self.disk_paths.append(path)
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


class RunTestCase(unittest.TestCase):
    """Base for tests of ft.run() inside a FakeWorld; defines no tests."""

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

    def _run(self, fetchers=ft.DEFAULT_FETCHERS, now=lambda: 1000.0, **env):
        """Runs ft.run() with load_config(env); returns (summary, messages)."""
        with self.assertLogs(ft.logger, level="DEBUG") as logs:
            summary = ft.run(
                ft.load_config(env),
                client_factory=self.world.connect,
                today=date(2026, 9, 2),
                now=now,
                fetchers=fetchers,
                disk_usage=self.world.disk_usage,
            )
        return summary, [record.getMessage() for record in logs.records]


class RunTests(RunTestCase):
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
        self._run(
            FETCH_TORRENTS_DISTROS="arch",
            TRANSMISSION_RPC_USERNAME="alice",
            TRANSMISSION_RPC_PASSWORD="hunter2",
        )

        self.assertEqual(self.world.rpc_auths, [("alice", "hunter2")])

    def test_ratio_logging_sends_no_credentials_when_none_are_configured(self):
        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertEqual(self.world.rpc_auths, [None])

    def test_every_download_outcome_is_counted_each_time(self):
        # Two of each outcome (four failures: two downloads, two fetchers
        # that found nothing), so no counter can get away with "= 1". The
        # first candidate is ratio-blocked via the removed history, and must
        # not stop the rest of its fetcher's candidates.
        def url(name):
            return f"https://mirror.example/{name}.torrent"

        for name in ("release-a.iso", "release-b.iso"):
            self.world.routes[url(name)] = helpers.fake_response(b"torrent")
        for name in ("broken-a.iso", "broken-b.iso"):
            self.world.routes[url(name)] = helpers.fake_response(status=500)
        for name in ("present-a.iso", "present-b.iso"):
            with open(os.path.join(self.world.watch_dir, f"{name}.torrent"), "wb") as f:
                f.write(b"already here")
        with open(
            self.world.state_path("fetch_torrents_removed_history.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "archlinux-2026.08.01": {
                        "removed_date": "2026-08-20",
                        "reason": "stagnant",
                        "ratio": 0.4,
                    }
                },
                f,
            )

        def found(*names):
            return lambda: {name: url(name) for name in names}

        summary, messages = self._run(
            fetchers=(
                (
                    "arch",
                    found(
                        "archlinux-2026.09.01",
                        "release-a.iso",
                        "present-a.iso",
                        "missing-a.iso",
                        "broken-a.iso",
                    ),
                ),
                ("arch", dict),
                (
                    "arch",
                    found(
                        "release-b.iso",
                        "present-b.iso",
                        "missing-b.iso",
                        "broken-b.iso",
                    ),
                ),
                ("arch", lambda: False),
            ),
            FETCH_TORRENTS_DISTROS="arch",
        )

        self.assertEqual(
            summary,
            ft.RunSummary(elapsed=0.0, added=2, existing=2, not_found=2, failed=4),
        )
        self.assertNotIn(url("archlinux-2026.09.01"), self.world.requested)
        self.assertIn(
            "Skipping archlinux-2026.09.01 due to low ratio on previous version.",
            messages,
        )

    def test_low_demand_images_are_skipped_by_default(self):
        netinst = "kali-linux-2026.3-installer-netinst-amd64.iso"
        fetchers = (("kali", lambda: {netinst: "https://mirror.example/n.torrent"}),)

        self._run(fetchers=fetchers, FETCH_TORRENTS_DISTROS="kali")

        self.assertEqual(self.world.requested, [])

    def test_include_low_demand_fetches_low_demand_images(self):
        netinst = "kali-linux-2026.3-installer-netinst-amd64.iso"
        fetchers = (("kali", lambda: {netinst: "https://mirror.example/n.torrent"}),)

        self._run(
            fetchers=fetchers,
            FETCH_TORRENTS_DISTROS="kali",
            FETCH_TORRENTS_INCLUDE_LOW_DEMAND="true",
        )

        self.assertEqual(self.world.requested, ["https://mirror.example/n.torrent"])

    def test_elapsed_time_is_measured_from_start_to_finish(self):
        clock = iter([1000.0, 1012.5])

        summary, messages = self._run(
            fetchers=(), now=clock.__next__, FETCH_TORRENTS_DISTROS="arch"
        )

        self.assertEqual(summary.elapsed, 12.5)
        self.assertTrue(
            messages[-1].startswith("Run complete in 12.50 seconds."), messages[-1]
        )

    def test_reports_downloads_folder_usage_in_whole_gigabytes(self):
        self.world.disk_used_percent = 37

        _summary, messages = self._run(fetchers=(), FETCH_TORRENTS_DISTROS="arch")

        self.assertIn("Downloads folder usage: 37 GB used / 100 GB total", messages)
        self.assertEqual(set(self.world.disk_paths), {"/downloads"})

    def test_old_release_check_is_off_by_default(self):
        discovered = []
        with unittest.mock.patch.dict(
            ft.OLD_RELEASE_DISCOVERY,
            {"kali": lambda: discovered.append("kali") or {}},
            clear=True,
        ):
            summary, _ = self._run(FETCH_TORRENTS_DISTROS="kali", fetchers=())

        self.assertEqual(discovered, [])
        self.assertEqual((summary.old_added, summary.old_skipped), (None, None))
        self.assertFalse(os.path.exists(ft.old_release_check_state_file))


class OldReleaseRunTests(RunTestCase):
    """The daily run's old-release check end to end: config thresholds, the
    saved check state and removed history all reach the real
    check_old_releases_for_demand(), with only the downloads (FakeWorld
    routes) and the tracker scrape faked."""

    TODAY = "2026-09-02"

    def setUp(self):
        super().setUp()
        self.swarms = {}
        patcher = unittest.mock.patch.object(
            ft.torrent_scrape, "scrape_torrent", side_effect=self._scrape
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _scrape(self, path, timeout=15):
        with open(path, "rb") as f:
            return self.swarms[f.read()]

    def _candidate(self, version, variant, leechers, seeders):
        name = f"kali-linux-2025.{version}-{variant}-amd64.iso"
        url = f"https://cdimage.kali.org/{name}.torrent"
        body = f"{name} metadata".encode()
        self.world.routes[url] = helpers.fake_response(body)
        self.swarms[body] = {
            "tracker": "udp://tracker.example:6969",
            "seeders": seeders,
            "leechers": leechers,
            "completed": 0,
        }
        return name, url

    def _write_state(self, filename, data):
        with open(self.world.state_path(filename), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _check(self, candidates, fetchers=(), **env):
        with unittest.mock.patch.dict(
            ft.OLD_RELEASE_DISCOVERY, {"kali": lambda: dict(candidates)}, clear=True
        ):
            return self._run(
                fetchers=fetchers,
                FETCH_TORRENTS_DISTROS="kali",
                FETCH_TORRENTS_CHECK_OLD_RELEASES="true",
                FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHERS="4",
                FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHER_RATIO="0.5",
                FETCH_TORRENTS_OLD_RELEASE_ALLOW_ZERO_SEEDERS="true",
                FETCH_TORRENTS_OLD_RELEASE_RECHECK_DAYS="10",
                **env,
            )

    def test_every_always_log_prefix_matches_a_message_the_run_emits(self):
        # FETCH_TORRENTS_ALWAYS_LOG lets lines through by prefix, so a
        # reworded message would silently stop showing at the default level.
        # This run hits every prefixed message: a distro skipped and one
        # fetched, an old release added, and the ratio query.
        wanted = self._candidate(3, "installer", 6, 10)

        _summary, messages = self._check(
            [wanted], fetchers=(("arch", dict), ("kali", dict))
        )

        for prefix in ft.get_always_log_prefixes():
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    any(m.startswith(prefix) for m in messages),
                    f"no message starts with {prefix!r}",
                )

    def test_config_and_saved_state_drive_the_check(self):
        recent = self._candidate(1, "installer", 50, 1)
        removed = self._candidate(1, "live", 50, 1)
        thin = self._candidate(2, "installer", 3, 1)  # under the 4-leecher floor
        crowded = self._candidate(2, "live", 5, 20)  # under 0.5x the seeders
        wanted = self._candidate(3, "installer", 6, 10)
        unseeded = self._candidate(3, "live", 5, 0)  # zero seeders allowed
        netinst = self._candidate(3, "installer-netinst", 50, 1)  # low demand
        # Checked 8 days ago: due under the default 7-day interval, not 10.
        self._write_state(
            "fetch_torrents_old_release_check_state.json",
            {recent[0]: {"last_checked": "2026-08-25", "leechers": 0}},
        )
        self._write_state(
            "fetch_torrents_removed_history.json",
            {removed[0]: {"removed_date": "2026-08-01", "reason": "stagnant"}},
        )

        summary, messages = self._check(
            [recent, removed, thin, crowded, wanted, unseeded, netinst]
        )

        self.assertEqual((summary.old_added, summary.old_skipped), (2, 4))
        self.assertEqual(
            sorted(os.listdir(self.world.watch_dir)),
            [f"{wanted[0]}.torrent", f"{unseeded[0]}.torrent"],
        )
        self.assertEqual(
            self.world.requested, [thin[1], crowded[1], wanted[1], unseeded[1]]
        )
        self.assertEqual(
            ft.load_old_release_check_state(ft.old_release_check_state_file),
            {
                recent[0]: {"last_checked": "2026-08-25", "leechers": 0},
                thin[0]: {"last_checked": self.TODAY, "leechers": 3},
                crowded[0]: {"last_checked": self.TODAY, "leechers": 5},
                wanted[0]: {"last_checked": self.TODAY, "leechers": 6},
                unseeded[0]: {"last_checked": self.TODAY, "leechers": 5},
            },
        )
        self.assertIn(
            "Checking old releases for unmet demand (min leechers: 4, min "
            "leecher/seeder ratio: 0.5x, allow zero-seeder swarms: True, "
            "recheck interval: 10 days)...",
            messages,
        )
        self.assertTrue(
            messages[-1].endswith(
                "Old releases (FETCH_TORRENTS_CHECK_OLD_RELEASES): 2 added, 4 skipped."
            ),
            messages[-1],
        )

    def test_previously_removed_release_is_rechecked_when_skip_removed_is_off(self):
        removed = self._candidate(1, "live", 50, 1)
        self._write_state(
            "fetch_torrents_removed_history.json",
            {removed[0]: {"removed_date": "2026-08-01", "reason": "stagnant"}},
        )

        summary, _ = self._check(
            [removed], FETCH_TORRENTS_OLD_RELEASE_SKIP_REMOVED="false"
        )

        self.assertEqual((summary.old_added, summary.old_skipped), (1, 0))
        self.assertEqual(os.listdir(self.world.watch_dir), [f"{removed[0]}.torrent"])

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
                distros=ft.DEFAULT_DISTROS,
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
                distros=tuple(d for d in ft.ALL_DISTROS if d in {"arch", "devuan"}),
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
        self.assertEqual(
            config.invalid,
            {
                "cleanup_min_ratio": (
                    "CLEANUP_MIN_RATIO: could not convert string to float: 'high'"
                ),
                "stagnation_window_days": (
                    "CLEANUP_STAGNATION_WINDOW_DAYS: invalid literal for int() "
                    "with base 10: '1.5'"
                ),
            },
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


if __name__ == "__main__":
    unittest.main()
