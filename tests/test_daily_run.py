"""Tests for the daily run: fetch_torrents.run() and the `__main__` wiring
around it.

RunTests call run() directly with everything external faked at its
boundary: HTTP (ft.requests.get/post), the Transmission client (a
client_factory returning helpers.FakeTransmission), the RPC readiness
check (wait_for_rpc), disk usage and the clock. State files live in a
per-test temp dir.

MainWiringTests runs the script via runpy exactly as the container does, to
check that `__main__` sets up logging, reads the config and calls run().

Run with: python -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import re
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
BOTH_UBUNTUS = ["ubuntu-23.10-desktop-amd64.iso", "ubuntu-24.04-desktop-amd64.iso"]
# The last line of a run in which the arch fetcher found nothing (unrouted).
ARCH_FAILED_SUMMARY = (
    "Run complete in 0.00 seconds. 0 added, 0 existing, 0 not found upstream, 1 failed."
)


def torrent(name, id_, ratio):
    return helpers.FakeTorrent(name, id_, ratio=ratio)


class FakeWorld:
    """The web (`http`, a helpers.FakeHttp), a Transmission daemon (its HTTP
    RPC is `rpc`) and a disk, all in memory. State files and torrents go to `state_dir` and
    `watch_dir`: fresh temp dirs unless given."""

    def __init__(self, testcase, state_dir=None, watch_dir=None):
        self.state_dir = state_dir or helpers.make_temp_dir(
            testcase, "daily_run_state_"
        )
        self.watch_dir = watch_dir or helpers.make_temp_dir(
            testcase, "daily_run_watch_"
        )
        self.http = helpers.FakeHttp()
        self.events = []
        self.transmission = helpers.FakeTransmission()
        self.rpc = helpers.FakeTransmissionRpc(self.transmission)
        self.rpc_up = True
        self.disk_used_percent = 10
        self.disk_paths = []

    def hold_current_and_superseded_ubuntu(self, superseded_ratio=2.0):
        """Transmission holds Ubuntu 24.04 (ratio 2.0) and the 23.10 it
        superseded."""
        self.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, superseded_ratio),
        ]

    def wait_for_rpc(self):
        return self.rpc_up

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

    def route_arch(self):
        self.http.routes.update(
            {
                ARCH_RELEASES: helpers.fake_response(ARCH_HTML),
                ARCH_TORRENT: helpers.fake_response(b"a1"),
            }
        )


class WaitForTransmissionRpcTests(unittest.TestCase):
    def setUp(self):
        self.clock = helpers.FakeClock()
        self.attempts = []

    def _connect_after(self, refusals):
        @contextlib.contextmanager
        def connect(address, timeout):
            self.attempts.append((address, timeout))
            if len(self.attempts) <= refusals:
                raise ConnectionRefusedError
            yield MagicMock()

        return connect

    def _wait(self, refusals, **kwargs):
        return ft.wait_for_transmission_rpc(
            connect=self._connect_after(refusals),
            clock=self.clock,
            sleep=self.clock.sleep,
            **kwargs,
        )

    def test_connects_on_the_first_try_without_sleeping(self):
        self.assertTrue(self._wait(refusals=0))

        self.assertEqual(self.attempts, [(("localhost", 9091), 3)])
        self.assertEqual(self.clock.sleeps, [])

    def test_retries_once_a_second_until_the_port_opens(self):
        self.assertTrue(self._wait(refusals=4))

        self.assertEqual(self.clock.sleeps, [1] * 4)
        self.assertEqual(len(self.attempts), 5)

    def test_gives_up_once_the_timeout_has_elapsed(self):
        self.assertFalse(self._wait(refusals=1000))

        # Attempts at t=0..29; at t=30 elapsed is no longer < 30.
        self.assertEqual(len(self.attempts), 30)
        self.assertEqual(self.clock.now, 30)

    def test_host_port_and_timeout_are_honoured(self):
        self.assertFalse(
            self._wait(refusals=1000, host="transmission", port=9999, timeout=2)
        )

        self.assertEqual(self.attempts, [(("transmission", 9999), 3)] * 2)

    def test_succeeds_on_the_last_attempt_before_the_timeout(self):
        self.assertTrue(self._wait(refusals=29))

        self.assertEqual(len(self.attempts), 30)


class RunTestCase(unittest.TestCase):
    """Base for tests of ft.run() inside a FakeWorld; defines no tests."""

    def setUp(self):
        self.world = FakeWorld(
            self,
            state_dir=helpers.use_state_files(self).dir,
            watch_dir=helpers.use_watch_dir(self),
        )
        for name, fake in (("get", self.world.http.get), ("post", self.world.rpc.post)):
            patcher = unittest.mock.patch.object(ft.requests, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(
        self,
        fetchers=ft.DEFAULT_FETCHERS,
        now=lambda: 1000.0,
        old_release_discovery=ft.OLD_RELEASE_DISCOVERY,
        **env,
    ):
        """Runs ft.run() with load_config(env); returns (summary, messages)."""
        with self.assertLogs(ft.logger, level="DEBUG") as logs:
            summary = ft.run(
                ft.load_config(env),
                client_factory=self.world.connect,
                today=date(2026, 9, 2),
                now=now,
                fetchers=fetchers,
                old_release_discovery=old_release_discovery,
                disk_usage=self.world.disk_usage,
                wait_for_rpc=self.world.wait_for_rpc,
            )
        return summary, [record.getMessage() for record in logs.records]

    def assertNothingRemoved(self):
        self.assertEqual(self.world.transmission.names, BOTH_UBUNTUS)
        self.assertEqual(self.world.transmission.removals, [])


class RunTests(RunTestCase):
    def test_counts_each_download_outcome(self):
        # Noble's five images, one per outcome (live-server is unrouted, so
        # a 404).
        downloaded = {
            UBUNTU + "ubuntu-24.04-desktop-amd64.iso.torrent": b"d1",
            XUBUNTU + "desktop/xubuntu-24.04-desktop-amd64.iso.torrent": b"x1",
        }
        broken = LUBUNTU + "lubuntu-24.04-desktop-amd64.iso.torrent"
        present = XUBUNTU + "minimal/xubuntu-24.04-minimal-amd64.iso.torrent"
        self.world.http.routes.update(
            {
                "https://changelogs.ubuntu.com/meta-release-lts": helpers.fake_response(
                    UBUNTU_META
                ),
                **{
                    url: helpers.fake_response(body) for url, body in downloaded.items()
                },
                broken: helpers.fake_response(status=500),
                present: helpers.fake_response(b"x2"),
            }
        )
        with open(
            os.path.join(
                self.world.watch_dir, "xubuntu-24.04-minimal-amd64.iso.torrent"
            ),
            "wb",
        ) as f:
            f.write(b"already here")

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
        self.world.route_arch()

        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertEqual(self.world.http.requested, [ARCH_RELEASES, ARCH_TORRENT])

    def test_low_previous_ratio_blocks_the_new_release(self):
        self.world.route_arch()
        self.world.write_ratio_log({"archlinux-2026.08.01": 0.4})

        _summary, messages = self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertNotIn(ARCH_TORRENT, self.world.http.requested)
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
        self.world.http.routes["https://changelogs.ubuntu.com/meta-release-lts"] = (
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
            wait_for_rpc=self.world.wait_for_rpc,
            fetchers=(("arch", lambda: {"archlinux-2026.10.01": ARCH_TORRENT}),),
        )

        self.assertEqual(self.world.http.requested, [ARCH_TORRENT])
        self.assertEqual(summary.not_found, 1)

    def test_keep_only_latest_selects_the_old_version_cleanup(self):
        self.world.hold_current_and_superseded_ubuntu()

        self._run(
            FETCH_TORRENTS_DISTROS="arch", CLEANUP_KEEP_ONLY_LATEST_VERSION="true"
        )

        self.assertEqual(
            self.world.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"]
        )

    def test_keep_only_latest_honors_min_ratio(self):
        self.world.hold_current_and_superseded_ubuntu()

        self._run(
            FETCH_TORRENTS_DISTROS="arch",
            CLEANUP_KEEP_ONLY_LATEST_VERSION="true",
            CLEANUP_MIN_RATIO="3",
        )

        self.assertNothingRemoved()

    def test_default_cleanup_is_stagnation_based(self):
        # No ratio history yet, so the stagnation cleanup can't judge the old
        # version and keeps it - unlike keep-only-latest, which removes it.
        self.world.hold_current_and_superseded_ubuntu()

        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertNothingRemoved()
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
        self.world.hold_current_and_superseded_ubuntu()

        _summary, messages = self._run(
            FETCH_TORRENTS_DISTROS="arch",
            CLEANUP_KEEP_ONLY_LATEST_VERSION="true",
            CLEANUP_MIN_RATIO="high",
        )

        self.assertNothingRemoved()
        self.assertRegex(
            "\n".join(messages),
            r"(?m)^Could not clean up old versions: CLEANUP_MIN_RATIO: ",
        )
        self.assertEqual(messages[-1], ARCH_FAILED_SUMMARY)

    def test_invalid_stagnation_setting_skips_cleanup_and_continues(self):
        self.world.hold_current_and_superseded_ubuntu()

        for env_var in (
            "CLEANUP_STAGNATION_WINDOW_DAYS",
            "CLEANUP_STAGNATION_MIN_RATIO_DELTA",
        ):
            with self.subTest(env_var=env_var):
                _summary, messages = self._run(
                    FETCH_TORRENTS_DISTROS="arch", **{env_var: "-"}
                )

                self.assertNothingRemoved()
                self.assertRegex(
                    "\n".join(messages),
                    f"(?m)^Could not clean up old versions: {env_var}: ",
                )
                self.assertEqual(messages[-1], ARCH_FAILED_SUMMARY)

    def test_default_fetchers_cover_every_distro_with_its_own_fetcher(self):
        self.assertEqual(
            dict(ft.DEFAULT_FETCHERS),
            {
                "ubuntu": ft.fetch_ubuntu_lts,
                "debian": ft.fetch_debian_stable,
                "kali": ft.fetch_kali_latest,
                "arch": ft.fetch_arch_latest,
                "mint": ft.fetch_linuxmint_cinnamon,
                "fedora": ft.fetch_fedora_workstation,
                "devuan": ft.fetch_devuan_latest,
            },
        )
        self.assertEqual(
            sorted(name for name, _fetch in ft.DEFAULT_FETCHERS),
            sorted(ft.ALL_DISTROS),
        )

    def test_old_releases_are_discovered_for_kali_and_fedora(self):
        self.assertEqual(
            ft.OLD_RELEASE_DISCOVERY,
            {
                "kali": ft.fetch_kali_old_versions,
                "fedora": ft.fetch_fedora_workstation_old_versions,
            },
        )

    def test_disk_usage_limit_runs_after_cleanup(self):
        self.world.hold_current_and_superseded_ubuntu(superseded_ratio=0.1)
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

        self.assertRegex(
            "\n".join(messages),
            r"(?m)^Could not enforce disk usage limit: "
            r"CLEANUP_DISK_USAGE_THRESHOLD_PERCENT: ",
        )
        self.assertEqual(messages[-1], ARCH_FAILED_SUMMARY)

    def test_rpc_unavailable_skips_ratio_logging_but_still_cleans_up(self):
        self.world.rpc_up = False
        self.world.hold_current_and_superseded_ubuntu()
        _summary, messages = self._run(
            FETCH_TORRENTS_DISTROS="arch", CLEANUP_KEEP_ONLY_LATEST_VERSION="true"
        )

        self.assertIn(
            "Transmission RPC not available on localhost:9091; skipping ratio logs.",
            messages,
        )
        self.assertEqual([m for m in messages if m.startswith("[ratio]")], [])
        self.assertEqual(
            self.world.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"]
        )

    def test_failing_ratio_query_is_logged_and_the_run_carries_on(self):
        self.world.rpc.error_status = 500
        self.world.hold_current_and_superseded_ubuntu()

        _summary, messages = self._run(
            FETCH_TORRENTS_DISTROS="arch", CLEANUP_KEEP_ONLY_LATEST_VERSION="true"
        )

        self.assertRegex(
            "\n".join(messages),
            r"(?m)^Could not query Transmission: 500 Server Error",
        )
        self.assertEqual([m for m in messages if m.startswith("[ratio]")], [])
        self.assertEqual(
            self.world.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"]
        )
        self.assertEqual(messages[-1], ARCH_FAILED_SUMMARY)

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
        self.world.rpc.credentials = ("alice", "hunter2")
        self._run(
            FETCH_TORRENTS_DISTROS="arch",
            TRANSMISSION_RPC_USERNAME="alice",
            TRANSMISSION_RPC_PASSWORD="hunter2",
        )

        self.assertEqual(self.world.rpc.auths, [("alice", "hunter2")])

    def test_ratio_logging_sends_no_credentials_when_none_are_configured(self):
        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertEqual(self.world.rpc.auths, [None])

    def test_every_download_outcome_is_counted_each_time(self):
        # Two of each outcome (four failures: two downloads, two fetchers
        # that found nothing), so no counter can get away with "= 1". The
        # first candidate is ratio-blocked via the removed history, and must
        # not stop the rest of its fetcher's candidates.
        def url(name):
            return f"https://mirror.example/{name}.torrent"

        for name in ("release-a.iso", "release-b.iso"):
            self.world.http.routes[url(name)] = helpers.fake_response(b"torrent")
        for name in ("broken-a.iso", "broken-b.iso"):
            self.world.http.routes[url(name)] = helpers.fake_response(status=500)
        for name in ("present-a.iso", "present-b.iso"):
            with open(os.path.join(self.world.watch_dir, f"{name}.torrent"), "wb") as f:
                f.write(b"already here")
        with open(
            self.world.state_path("fetch_torrents_removed_history.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(helpers.removed("archlinux-2026.08.01", 0.4), f)

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
        self.assertNotIn(url("archlinux-2026.09.01"), self.world.http.requested)
        self.assertIn(
            "Skipping archlinux-2026.09.01 due to low ratio on previous version.",
            messages,
        )

    def test_low_demand_images_are_skipped_by_default(self):
        netinst = "kali-linux-2026.3-installer-netinst-amd64.iso"
        fetchers = (("kali", lambda: {netinst: "https://mirror.example/n.torrent"}),)

        self._run(fetchers=fetchers, FETCH_TORRENTS_DISTROS="kali")

        self.assertEqual(self.world.http.requested, [])

    def test_include_low_demand_fetches_low_demand_images(self):
        netinst = "kali-linux-2026.3-installer-netinst-amd64.iso"
        fetchers = (("kali", lambda: {netinst: "https://mirror.example/n.torrent"}),)

        self._run(
            fetchers=fetchers,
            FETCH_TORRENTS_DISTROS="kali",
            FETCH_TORRENTS_INCLUDE_LOW_DEMAND="true",
        )

        self.assertEqual(
            self.world.http.requested, ["https://mirror.example/n.torrent"]
        )

    def test_elapsed_time_is_measured_from_start_to_finish(self):
        clock = iter([1000.0, 1012.5])

        summary, messages = self._run(
            fetchers=(), now=clock.__next__, FETCH_TORRENTS_DISTROS="arch"
        )

        self.assertEqual(summary.elapsed, 12.5)
        self.assertEqual(
            messages[-1],
            "Run complete in 12.50 seconds. 0 added, 0 existing, "
            "0 not found upstream, 0 failed.",
        )

    def test_reports_downloads_folder_usage_in_whole_gigabytes(self):
        self.world.disk_used_percent = 37

        _summary, messages = self._run(fetchers=(), FETCH_TORRENTS_DISTROS="arch")

        self.assertIn("Downloads folder usage: 37 GB used / 100 GB total", messages)
        self.assertEqual(set(self.world.disk_paths), {"/downloads"})

    def test_old_release_check_is_off_by_default(self):
        discovered = []

        summary, _ = self._run(
            FETCH_TORRENTS_DISTROS="kali",
            fetchers=(),
            old_release_discovery={"kali": lambda: discovered.append("kali") or {}},
        )

        self.assertEqual(discovered, [])
        self.assertEqual((summary.old_added, summary.old_skipped), (None, None))
        self.assertFalse(os.path.exists(ft.old_release_check_state_file))


class OldReleaseRunTests(RunTestCase):
    """The daily run's old-release check end to end: config thresholds, the
    saved check state and removed history all reach the real
    check_old_releases_for_demand(), with only the downloads and the tracker
    scrape faked (helpers.OldReleaseTracker)."""

    TODAY = "2026-09-02"

    def setUp(self):
        super().setUp()
        self.tracker = self.world.http = helpers.OldReleaseTracker()
        self.tracker.patch(self)

    def _candidate(self, version, variant, leechers, seeders):
        """Serves an old Kali image whose swarm has `leechers` and
        `seeders`; returns (name, url)."""
        name = f"kali-linux-2025.{version}-{variant}-amd64.iso"
        return name, self.tracker.candidate(name, helpers.swarm(leechers, seeders))

    def _write_state(self, filename, data):
        with open(self.world.state_path(filename), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _check(self, candidates, fetchers=(), **env):
        return self._run(
            fetchers=fetchers,
            old_release_discovery={"kali": lambda: dict(candidates)},
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
                self.assertRegex("\n".join(messages), "(?m)^" + re.escape(prefix))

    def _added(self):
        return sorted(os.listdir(self.world.watch_dir))

    # One test per setting _check() passes, each with a swarm that the
    # setting's default would decide the other way.

    def test_min_leechers_setting_is_applied(self):
        thin = self._candidate(2, "installer", 3, 1)
        wanted = self._candidate(3, "installer", 6, 10)  # under the default 10

        self._check([thin, wanted])

        self.assertEqual(self._added(), [f"{wanted[0]}.torrent"])

    def test_min_leecher_ratio_setting_is_applied(self):
        crowded = self._candidate(2, "live", 5, 20)  # over the default 0.1x
        wanted = self._candidate(3, "installer", 6, 10)

        self._check([crowded, wanted])

        self.assertEqual(self._added(), [f"{wanted[0]}.torrent"])

    def test_allow_zero_seeders_setting_is_applied(self):
        unseeded = self._candidate(3, "live", 5, 0)

        self._check([unseeded])

        self.assertEqual(self._added(), [f"{unseeded[0]}.torrent"])

    def test_recheck_days_setting_is_applied(self):
        recent = self._candidate(1, "installer", 50, 1)
        # Checked 8 days ago: due under the default 7-day interval, not 10.
        self._write_state(
            "fetch_torrents_old_release_check_state.json",
            {recent[0]: {"last_checked": "2026-08-25", "leechers": 0}},
        )

        self._check([recent])

        self.assertEqual(self.tracker.requested, [])

    def test_previously_removed_release_is_skipped_by_default(self):
        removed = self._candidate(1, "live", 50, 1)
        self._write_state(
            "fetch_torrents_removed_history.json", helpers.removed(removed[0])
        )

        self._check([removed])

        self.assertEqual(self.tracker.requested, [])

    def test_low_demand_old_releases_are_skipped_by_default(self):
        netinst = self._candidate(3, "installer-netinst", 50, 1)

        self._check([netinst])

        self.assertEqual(self.tracker.requested, [])

    def test_check_state_is_saved_for_the_next_run(self):
        recent = self._candidate(1, "installer", 50, 1)
        thin = self._candidate(2, "installer", 3, 1)
        self._write_state(
            "fetch_torrents_old_release_check_state.json",
            {recent[0]: {"last_checked": "2026-08-25", "leechers": 0}},
        )

        self._check([recent, thin])

        self.assertEqual(
            ft.load_old_release_check_state(ft.old_release_check_state_file),
            {
                recent[0]: {"last_checked": "2026-08-25", "leechers": 0},
                thin[0]: {"last_checked": self.TODAY, "leechers": 3},
            },
        )

    def test_thresholds_and_counts_are_logged(self):
        thin = self._candidate(2, "installer", 3, 1)
        wanted = self._candidate(3, "installer", 6, 10)

        _summary, messages = self._check([thin, wanted])

        self.assertIn(
            "Checking old releases for unmet demand (min leechers: 4, min "
            "leecher/seeder ratio: 0.5x, allow zero-seeder swarms: True, "
            "recheck interval: 10 days)...",
            messages,
        )
        self.assertEqual(
            messages[-1],
            "Run complete in 0.00 seconds. 0 added, 0 existing, 0 not found "
            "upstream, 0 failed. Old releases (FETCH_TORRENTS_CHECK_OLD_RELEASES): "
            "1 added, 1 skipped.",
        )

    def test_previously_removed_release_is_rechecked_when_skip_removed_is_off(self):
        removed = self._candidate(1, "live", 50, 1)
        self._write_state(
            "fetch_torrents_removed_history.json",
            helpers.removed(removed[0]),
        )

        summary, _ = self._check(
            [removed], FETCH_TORRENTS_OLD_RELEASE_SKIP_REMOVED="false"
        )

        self.assertEqual((summary.old_added, summary.old_skipped), (1, 0))
        self.assertEqual(os.listdir(self.world.watch_dir), [f"{removed[0]}.torrent"])

    def assertRunCarriedOn(self, messages):
        """Ratio logging and cleanup still ran after the old-release check."""
        self.assertIn("[ratio] RATIOS START", messages)
        self.assertEqual(
            self.world.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"]
        )

    def test_invalid_old_release_setting_skips_the_check_and_continues(self):
        self.world.hold_current_and_superseded_ubuntu()

        for env_var in (
            "FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHERS",
            "FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHER_RATIO",
            "FETCH_TORRENTS_OLD_RELEASE_RECHECK_DAYS",
        ):
            with self.subTest(env_var=env_var):
                summary, messages = self._run(
                    FETCH_TORRENTS_DISTROS="arch",
                    FETCH_TORRENTS_CHECK_OLD_RELEASES="true",
                    CLEANUP_KEEP_ONLY_LATEST_VERSION="true",
                    **{env_var: "weekly"},
                )

                self.assertRegex(
                    "\n".join(messages),
                    f"(?m)^Could not check old releases: {env_var}: ",
                )
                self.assertRunCarriedOn(messages)
                # Failed before producing counts: reported as "check not run".
                self.assertEqual((summary.old_added, summary.old_skipped), (None, None))
                self.assertEqual(messages[-1], ARCH_FAILED_SUMMARY)

    def test_failing_to_save_the_check_state_still_reports_the_counts(self):
        self.world.hold_current_and_superseded_ubuntu()
        wanted = self._candidate(3, "installer", 6, 10)
        # A directory where the state file's temp copy goes: the real open()
        # fails after the check has counted (and added) the release.
        os.mkdir(ft.old_release_check_state_file + ".tmp")

        summary, messages = self._check(
            [wanted], CLEANUP_KEEP_ONLY_LATEST_VERSION="true"
        )

        self.assertRegex("\n".join(messages), r"(?m)^Could not check old releases: ")
        self.assertFalse(os.path.exists(ft.old_release_check_state_file))
        self.assertRunCarriedOn(messages)
        self.assertEqual((summary.old_added, summary.old_skipped), (1, 0))
        self.assertEqual(
            messages[-1],
            "Run complete in 0.00 seconds. 0 added, 0 existing, 0 not found "
            "upstream, 0 failed. Old releases (FETCH_TORRENTS_CHECK_OLD_RELEASES): "
            "1 added, 0 skipped.",
        )


class MainWiringTests(unittest.TestCase):
    """`python fetch_torrents.py` must configure logging (so this run's ratio
    log is written for the next run to gate on), load the config from the
    environment and call run() with a real Transmission client factory."""

    def test_running_the_script_performs_a_daily_run(self):
        world = FakeWorld(self)
        world.hold_current_and_superseded_ubuntu()
        world.route_arch()

        @contextlib.contextmanager
        def rpc_port_open(*args, **kwargs):
            yield MagicMock()

        self.enterContext(
            helpers.isolated_env(
                FETCH_TORRENTS_LOG_DIR=world.state_dir,
                FETCH_TORRENTS_WATCH_DIR=world.watch_dir,
                FETCH_TORRENTS_DISTROS="arch",
                TRANSMISSION_RPC_USERNAME="alice",
                TRANSMISSION_RPC_PASSWORD="hunter2",
            )
        )
        self.enterContext(unittest.mock.patch("requests.get", world.http.get))
        self.enterContext(unittest.mock.patch("requests.post", world.rpc.post))
        client_cls = self.enterContext(
            unittest.mock.patch.object(
                sys.modules["transmission_rpc"],
                "Client",
                side_effect=lambda **kwargs: world.transmission,
            )
        )
        self.enterContext(
            unittest.mock.patch.object(socket, "create_connection", rpc_port_open)
        )
        self.enterContext(
            unittest.mock.patch.object(shutil, "disk_usage", world.disk_usage)
        )
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        logs = self.enterContext(self.assertLogs(ft.logger, level="DEBUG"))
        # Runs before assertLogs puts the logger's own handlers back: closes
        # the ones the script's configure_logging() added.
        self.addCleanup(ft.reset_logging)

        runpy.run_path(SCRIPT, run_name="__main__")

        messages = [record.getMessage() for record in logs.records]
        self.assertIn("Selected distros for this run: arch", messages)
        self.assertRegex(
            messages[-1],
            r"\ARun complete in \d+\.\d\d seconds\. 1 added, 0 existing, "
            r"0 not found upstream, 0 failed\.\Z",
        )
        self.assertEqual(os.listdir(world.watch_dir), ["archlinux-2026.09.01.torrent"])
        client_cls.assert_called_with(
            host="localhost", port=9091, username="alice", password="hunter2"
        )
        self.assertEqual(
            ft.get_previous_ratios(world.state_path("fetch_torrents_ratios.log")),
            {
                "ubuntu-24.04-desktop-amd64.iso": 2.0,
                "ubuntu-23.10-desktop-amd64.iso": 2.0,
            },
        )
        self.assertTrue(os.path.exists(world.state_path("fetch_torrents.log")))


if __name__ == "__main__":
    unittest.main()
