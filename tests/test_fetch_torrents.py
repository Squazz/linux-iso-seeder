"""Tests for fetch_torrents.py, focused on the cleanup_old_versions() logic.

fetch_torrents.py is written to run inside the container: it imports
transmission_rpc (an apk-only package not available via pip) and opens log
files under /logs at import time. To make the module importable in a plain
test environment, this file stubs transmission_rpc and points
FETCH_TORRENTS_LOG_DIR at a temp directory before importing it.

Run with: python -m unittest discover -s tests
"""
import os
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import date, timedelta
from unittest.mock import MagicMock

if 'transmission_rpc' not in sys.modules:
    stub = types.ModuleType('transmission_rpc')
    stub.Client = MagicMock()
    sys.modules['transmission_rpc'] = stub

os.environ.setdefault('FETCH_TORRENTS_LOG_DIR', tempfile.mkdtemp(prefix='fetch_torrents_test_logs_'))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import fetch_torrents as ft


class FakeTorrent:
    def __init__(self, name, id_, ratio=0.0):
        self.name = name
        self.id = id_
        self.ratio = ratio

    def __repr__(self):
        return f"FakeTorrent({self.name!r}, ratio={self.ratio})"


def names_of(torrents):
    return sorted(t.name for t in torrents)


class PlanCleanupTests(unittest.TestCase):
    def test_selects_older_version_per_distro_and_type(self):
        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=2.0),
            FakeTorrent("ubuntu-24.04.1-live-server-amd64.iso", 3, ratio=2.0),
            FakeTorrent("ubuntu-22.04.1-live-server-amd64.iso", 4, ratio=2.0),
            FakeTorrent("debian-12.5.0-amd64-DVD-1.iso", 5, ratio=2.0),
            FakeTorrent("debian-12.4.0-amd64-DVD-1.iso", 6, ratio=2.0),
            FakeTorrent("kali-linux-2024.1-installer-amd64.iso", 7, ratio=2.0),
            FakeTorrent("kali-linux-2023.4-installer-amd64.iso", 8, ratio=2.0),
            FakeTorrent("archlinux-2024.05.01-x86_64.iso", 9, ratio=2.0),
            FakeTorrent("archlinux-2024.04.01-x86_64.iso", 10, ratio=2.0),
            FakeTorrent("linuxmint-22.3-cinnamon-64bit.iso", 11, ratio=2.0),
            FakeTorrent("linuxmint-22.2-cinnamon-64bit.iso", 12, ratio=2.0),
            FakeTorrent("Fedora-Workstation-Live-x86_64-44", 13, ratio=2.0),
            FakeTorrent("Fedora-Workstation-Live-x86_64-43", 14, ratio=2.0),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(
            names_of(to_remove),
            [
                "Fedora-Workstation-Live-x86_64-43",
                "archlinux-2024.04.01-x86_64.iso",
                "debian-12.4.0-amd64-DVD-1.iso",
                "kali-linux-2023.4-installer-amd64.iso",
                "linuxmint-22.2-cinnamon-64bit.iso",
                "ubuntu-22.04.1-live-server-amd64.iso",
                "ubuntu-23.10-desktop-amd64.iso",
            ],
        )
        self.assertEqual(to_keep_low_ratio, [])

        # The newest torrent in each (distro, type) group must never be
        # scheduled for removal.
        removed_names = set(names_of(to_remove))
        for newest in (
            "ubuntu-24.04-desktop-amd64.iso",
            "ubuntu-24.04.1-live-server-amd64.iso",
            "debian-12.5.0-amd64-DVD-1.iso",
            "kali-linux-2024.1-installer-amd64.iso",
            "archlinux-2024.05.01-x86_64.iso",
            "linuxmint-22.3-cinnamon-64bit.iso",
            "Fedora-Workstation-Live-x86_64-44",
        ):
            self.assertNotIn(newest, removed_names)

    def test_single_torrent_per_group_is_left_alone(self):
        torrents = [FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=0.0)]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep_low_ratio, [])

    def test_unrelated_torrents_are_ignored(self):
        torrents = [
            FakeTorrent("some-random-linux-distro-1.0.iso", 1, ratio=5.0),
            FakeTorrent("some-random-linux-distro-2.0.iso", 2, ratio=5.0),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep_low_ratio, [])

    def test_old_version_below_ratio_threshold_is_kept_not_removed(self):
        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.4),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents, min_ratio=1.0)

        self.assertEqual(to_remove, [])
        self.assertEqual(len(to_keep_low_ratio), 1)
        kept_torrent, kept_ratio = to_keep_low_ratio[0]
        self.assertEqual(kept_torrent.name, "ubuntu-23.10-desktop-amd64.iso")
        self.assertEqual(kept_ratio, 0.4)

    def test_skip_ratio_check_removes_regardless_of_ratio(self):
        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.0),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(
            torrents, skip_ratio_check=True, min_ratio=1.0
        )

        self.assertEqual(names_of(to_remove), ["ubuntu-23.10-desktop-amd64.iso"])
        self.assertEqual(to_keep_low_ratio, [])

    def test_different_types_within_same_distro_are_not_cross_removed(self):
        # desktop and live-server are different "type_" groups for ubuntu;
        # having only the desktop build twice must not affect live-server.
        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=2.0),
            FakeTorrent("ubuntu-24.04.1-live-server-amd64.iso", 3, ratio=2.0),
        ]

        to_remove, _ = ft.plan_cleanup(torrents)

        self.assertEqual(names_of(to_remove), ["ubuntu-23.10-desktop-amd64.iso"])

    def test_unparseable_name_for_matched_distro_is_skipped_not_raised(self):
        # "ubuntu-desktop" has no version segment at index 1 that parses as
        # a version; parse_version_type/version_to_tuple should fail and
        # plan_cleanup must skip it rather than raising.
        torrents = [
            FakeTorrent("ubuntu-desktop", 1, ratio=2.0),
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 2, ratio=2.0),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep_low_ratio, [])


class ShouldFetchTorrentRatioKeyTests(unittest.TestCase):
    """Candidate names must key into the same ratio-lookup bucket as the names Transmission
    actually reports (which include the arch suffix and .iso extension),
    for all supported distros."""

    def test_finds_previous_version_and_honors_low_ratio_ubuntu(self):
        ratios = {"ubuntu-23.10-desktop-amd64.iso": 0.5}
        self.assertFalse(ft.should_fetch_torrent("ubuntu-24.04-desktop-amd64.iso", ratios))

    def test_finds_previous_version_and_honors_low_ratio_debian(self):
        ratios = {"debian-12.4.0-amd64-DVD-1.iso": 0.5}
        self.assertFalse(ft.should_fetch_torrent("debian-12.5.0-amd64-DVD-1.iso", ratios))

    def test_finds_previous_version_and_honors_low_ratio_kali(self):
        ratios = {"kali-linux-2023.4-installer-amd64.iso": 0.3}
        self.assertFalse(ft.should_fetch_torrent("kali-linux-2024.1-installer-amd64.iso", ratios))

    def test_finds_previous_version_and_honors_low_ratio_arch(self):
        ratios = {"archlinux-2024.04.01-x86_64.iso": 0.2}
        self.assertFalse(ft.should_fetch_torrent("archlinux-2024.05.01-x86_64.iso", ratios))

    def test_finds_previous_version_and_allows_high_ratio_ubuntu(self):
        ratios = {"ubuntu-23.10-desktop-amd64.iso": 1.5}
        self.assertTrue(ft.should_fetch_torrent("ubuntu-24.04-desktop-amd64.iso", ratios))

    def test_finds_previous_version_and_allows_high_ratio_debian(self):
        ratios = {"debian-12.4.0-amd64-DVD-1.iso": 1.5}
        self.assertTrue(ft.should_fetch_torrent("debian-12.5.0-amd64-DVD-1.iso", ratios))

    def test_finds_previous_version_and_honors_low_ratio_mint(self):
        ratios = {"linuxmint-22.2-cinnamon-64bit.iso": 0.4}
        self.assertFalse(ft.should_fetch_torrent("linuxmint-22.3-cinnamon-64bit.iso", ratios))

    def test_finds_previous_version_and_allows_high_ratio_mint(self):
        ratios = {"linuxmint-22.2-cinnamon-64bit.iso": 1.5}
        self.assertTrue(ft.should_fetch_torrent("linuxmint-22.3-cinnamon-64bit.iso", ratios))

    def test_finds_previous_version_and_honors_low_ratio_fedora(self):
        ratios = {"Fedora-Workstation-Live-x86_64-43": 0.4}
        self.assertFalse(ft.should_fetch_torrent("Fedora-Workstation-Live-x86_64-44", ratios))

    def test_finds_previous_version_and_allows_high_ratio_fedora(self):
        ratios = {"Fedora-Workstation-Live-x86_64-43": 1.5}
        self.assertTrue(ft.should_fetch_torrent("Fedora-Workstation-Live-x86_64-44", ratios))


class RatioLogSurvivesRestartTests(unittest.TestCase):
    """Each container run is a fresh `python fetch_torrents.py` process: the
    ratio log from the *previous* run is what should_fetch_torrent() needs in
    order to gate a new version's download. Simulate a real restart (fresh
    interpreter, pre-existing ratio log on disk) rather than reusing the
    already-imported module, since the bug this guards against is specifically
    about what happens between import and the first get_previous_ratios() call."""

    def test_previous_ratios_are_readable_after_a_fresh_start(self):
        log_dir = tempfile.mkdtemp(prefix='fetch_torrents_ratio_restart_')
        ratio_log_path = os.path.join(log_dir, 'fetch_torrents_ratios.log')
        with open(ratio_log_path, 'w', encoding='utf-8') as f:
            f.write(
                "2026-08-01 00:00:00,000 INFO: [ratio] RATIOS START\n"
                "2026-08-01 00:00:00,000 INFO: [ratio] archlinux-2026.04.01-x86_64.iso            → 0.664\n"
                "2026-08-01 00:00:00,000 INFO: [ratio] RATIOS END\n"
            )

        script = (
            "import os, sys, types\n"
            "from unittest.mock import MagicMock\n"
            "stub = types.ModuleType('transmission_rpc')\n"
            "stub.Client = MagicMock()\n"
            "sys.modules['transmission_rpc'] = stub\n"
            f"sys.path.insert(0, {REPO_ROOT!r})\n"
            "import fetch_torrents as ft\n"
            "print(ft.get_previous_ratios(ft.ratio_log_file))\n"
        )
        env = dict(os.environ, FETCH_TORRENTS_LOG_DIR=log_dir)
        result = subprocess.run(
            [sys.executable, '-c', script],
            env=env, capture_output=True, text=True, timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "archlinux-2026.04.01-x86_64.iso", result.stdout,
            "get_previous_ratios() found nothing from the prior run's ratio "
            "log - it was likely wiped by the ratio FileHandler's mode='w' "
            "open at import time, before ever being read. That silently "
            "defeats the low-ratio fetch gate for every distro.",
        )


class FetchUbuntuLtsNamingTests(unittest.TestCase):
    """The names fetch_ubuntu_lts() uses as dict keys are also what gets
    passed to should_fetch_torrent() before download, so they must match the
    shape of the names Transmission later reports for those same torrents
    (real arch suffix + .iso extension) — see
    tasks/02-ratio-key-mismatch-ubuntu-debian.md."""

    def test_candidate_names_include_arch_and_iso_suffix(self):
        meta_release = (
            "Dist: noble\n"
            "Version: 24.04\n"
            "Supported: 1\n"
        )

        class FakeResponse:
            text = meta_release

        with unittest.mock.patch.object(ft.requests, "get", return_value=FakeResponse()):
            results = ft.fetch_ubuntu_lts()

        self.assertTrue(results)
        self.assertIn("ubuntu-24.04-desktop-amd64.iso", results)
        self.assertIn("ubuntu-24.04-live-server-amd64.iso", results)


class FetchDebianStableNamingTests(unittest.TestCase):
    """Mirrors FetchUbuntuLtsNamingTests for Debian: the dict key must keep
    the .iso extension so it matches Transmission's reported torrent name."""

    def test_candidate_name_keeps_iso_suffix(self):
        html = '<html><body><a href="debian-12.5.0-amd64-DVD-1.iso.torrent">link</a></body></html>'

        class FakeResponse:
            text = html

            def raise_for_status(self):
                pass

        with unittest.mock.patch.object(ft.requests, "get", return_value=FakeResponse()):
            results = ft.fetch_debian_stable()

        self.assertIn("debian-12.5.0-amd64-DVD-1.iso", results)


class FetchLinuxMintCinnamonNamingTests(unittest.TestCase):
    """The dict key fetch_linuxmint_cinnamon() uses must match the 'name'
    field embedded in the actual .torrent file (verified against a real
    download from linuxmint.com: linuxmint-22.3-cinnamon-64bit.iso), so it
    lines up with what Transmission later reports as torrent.name."""

    def test_candidate_name_matches_torrent_internal_name(self):
        html = "<title>Download Linux Mint 22.3 - Linux Mint</title>"

        class FakeResponse:
            text = html

        with unittest.mock.patch.object(ft.requests, "get", return_value=FakeResponse()):
            results = ft.fetch_linuxmint_cinnamon()

        self.assertIn("linuxmint-22.3-cinnamon-64bit.iso", results)
        self.assertEqual(
            results["linuxmint-22.3-cinnamon-64bit.iso"],
            "https://www.linuxmint.com/torrents/linuxmint-22.3-cinnamon-64bit.iso.torrent",
        )


class FetchFedoraWorkstationNamingTests(unittest.TestCase):
    """The dict key fetch_fedora_workstation() uses must match the 'name'
    field embedded in the actual .torrent file (verified against a real
    download from torrent.fedoraproject.org: Fedora-Workstation-Live-x86_64-44,
    which has no .iso extension), so it lines up with what Transmission later
    reports as torrent.name."""

    def test_picks_highest_version_per_arch(self):
        html = (
            "<html><body>"
            '<a href="Fedora-Workstation-Live-x86_64-43.torrent">a</a>'
            '<a href="Fedora-Workstation-Live-x86_64-44.torrent">b</a>'
            '<a href="Fedora-Workstation-Live-aarch64-43.torrent">c</a>'
            '<a href="Fedora-Workstation-Live-aarch64-44.torrent">d</a>'
            "</body></html>"
        )

        class FakeResponse:
            text = html

            def raise_for_status(self):
                pass

        with unittest.mock.patch.object(ft.requests, "get", return_value=FakeResponse()):
            results = ft.fetch_fedora_workstation()

        self.assertEqual(
            results,
            {
                "Fedora-Workstation-Live-x86_64-44":
                    "https://torrent.fedoraproject.org/torrents/Fedora-Workstation-Live-x86_64-44.torrent",
                "Fedora-Workstation-Live-aarch64-44":
                    "https://torrent.fedoraproject.org/torrents/Fedora-Workstation-Live-aarch64-44.torrent",
            },
        )


class LowDemandVariantTests(unittest.TestCase):
    """cloud-genericcloud images and Kali's netinst installer are
    chronically low-ratio in fetch_torrents_ratios.log regardless of
    architecture or how recent the release is — these are the 'image
    families' FETCH_TORRENTS_INCLUDE_LOW_DEMAND gates.

    arm64/aarch64/armhf/armel builds are deliberately NOT low-demand: current-
    version arm64/armhf builds (e.g. kali-linux-2026.2-raspberry-pi-armhf-img-xz
    at 2.351, debian-13.6.0-arm64-netinst.iso at 1.571) have solid ratios in
    the log — the low arm64/armhf numbers there are almost all older,
    superseded versions, already handled by should_fetch_torrent()."""

    def test_cloud_images_are_low_demand_regardless_of_arch(self):
        for name in (
            "kali-linux-2026.2-cloud-genericcloud-amd64-tar-xz",
            "kali-linux-2026.1-cloud-genericcloud-arm64-tar-xz",
        ):
            self.assertTrue(ft.is_low_demand_variant(name), name)

    def test_kali_netinst_is_low_demand_regardless_of_arch(self):
        for name in (
            "kali-linux-2026.1-installer-netinst-amd64.iso",
            "kali-linux-2025.2-installer-netinst-arm64.iso",
        ):
            self.assertTrue(ft.is_low_demand_variant(name), name)

    def test_debian_netinst_is_not_low_demand(self):
        # Debian's netinst is the highest-ratio image in the whole log —
        # only Kali's netinst installer is excluded, not the substring.
        for name in (
            "debian-13.6.0-amd64-netinst.iso",
            "debian-13.6.0-arm64-netinst.iso",
        ):
            self.assertFalse(ft.is_low_demand_variant(name), name)

    def test_current_arm64_and_armhf_builds_are_not_low_demand(self):
        for name in (
            "debian-13.6.0-arm64-DVD-1.iso",
            "kali-linux-2026.2-installer-arm64.iso",
            "Fedora-Workstation-Live-aarch64-44",
            "kali-linux-2026.2-raspberry-pi-armhf-img-xz",
            "kali-linux-2025.2-raspberry-pi-zero-w-armel-img-xz",
        ):
            self.assertFalse(ft.is_low_demand_variant(name), name)

    def test_mainstream_amd64_variants_are_not_low_demand(self):
        for name in (
            "ubuntu-24.04.4-desktop-amd64.iso",
            "kali-linux-2026.2-installer-everything-amd64.iso",
            "kali-linux-2026.2-installer-purple-amd64.iso",
            "kali-linux-2026.2-installer-amd64.iso",
            "archlinux-2026.04.01-x86_64.iso",
            "Fedora-Workstation-Live-x86_64-44",
        ):
            self.assertFalse(ft.is_low_demand_variant(name), name)

    def test_filter_low_demand_excludes_by_default(self):
        torrents = {
            "kali-linux-2026.2-installer-amd64.iso": "http://x/a",
            "kali-linux-2026.2-installer-netinst-amd64.iso": "http://x/b",
        }

        filtered = ft.filter_low_demand(torrents, include_low_demand=False)

        self.assertEqual(
            filtered, {"kali-linux-2026.2-installer-amd64.iso": "http://x/a"}
        )

    def test_filter_low_demand_includes_when_enabled(self):
        torrents = {
            "kali-linux-2026.2-installer-amd64.iso": "http://x/a",
            "kali-linux-2026.2-installer-netinst-amd64.iso": "http://x/b",
        }

        filtered = ft.filter_low_demand(torrents, include_low_demand=True)

        self.assertEqual(filtered, torrents)


class DownloadTorrent404Tests(unittest.TestCase):
    """Torrent URLs for releases no longer hosted upstream (e.g. old Ubuntu
    LTS releases that changelogs.ubuntu.com still marks 'Supported: 1' for
    ESM purposes, long after their installer media was pulled) 404. That's
    an expected, non-actionable outcome and shouldn't be logged/counted the
    same way as a genuine download failure."""

    def setUp(self):
        self.tmp_watch_dir = tempfile.mkdtemp(prefix='fetch_torrents_test_watch_')
        patcher = unittest.mock.patch.object(ft, 'watch_dir', self.tmp_watch_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_404_response_is_not_found_not_failed(self):
        class FakeResponse:
            status_code = 404

        with unittest.mock.patch.object(ft.requests, 'get', return_value=FakeResponse()):
            status = ft.download_torrent(
                'ubuntu-14.04.6-live-server-amd64.iso', 'https://example.invalid/x.torrent'
            )

        self.assertEqual(status, 'not_found')
        dest = os.path.join(self.tmp_watch_dir, 'ubuntu-14.04.6-live-server-amd64.iso.torrent')
        self.assertFalse(os.path.exists(dest))

    def test_other_http_error_is_still_failed(self):
        class FakeResponse:
            status_code = 500

            def raise_for_status(self):
                raise Exception("500 Server Error")

        with unittest.mock.patch.object(ft.requests, 'get', return_value=FakeResponse()):
            status = ft.download_torrent(
                'ubuntu-24.04-desktop-amd64.iso', 'https://example.invalid/x.torrent'
            )

        self.assertEqual(status, 'failed')

    def test_successful_download_is_still_added(self):
        class FakeResponse:
            status_code = 200
            content = b'fake torrent bytes'

            def raise_for_status(self):
                pass

        with unittest.mock.patch.object(ft.requests, 'get', return_value=FakeResponse()):
            status = ft.download_torrent(
                'ubuntu-24.04-desktop-amd64.iso', 'https://example.invalid/x.torrent'
            )

        self.assertEqual(status, 'added')
        dest = os.path.join(self.tmp_watch_dir, 'ubuntu-24.04-desktop-amd64.iso.torrent')
        with open(dest, 'rb') as f:
            self.assertEqual(f.read(), b'fake torrent bytes')


class UpdateRatioHistoryTests(unittest.TestCase):
    """update_ratio_history() must keep the on-disk history bounded: drop
    torrents that are no longer seeding, only add a new sample once per
    sample_interval_days, and prune samples once they're older than
    window_days + sample_interval_days - so it stays a fixed handful of
    samples per torrent forever, not one entry per run."""

    def test_new_torrent_gets_a_first_sample(self):
        today = date(2026, 8, 29)
        history = ft.update_ratio_history({}, {"archlinux-2026.08.01-x86_64.iso": 1.2}, today)

        self.assertEqual(
            history,
            {"archlinux-2026.08.01-x86_64.iso": [{"date": "2026-08-29", "ratio": 1.2}]},
        )

    def test_recent_sample_is_not_duplicated(self):
        today = date(2026, 8, 29)
        history = {
            "archlinux-2026.08.01-x86_64.iso": [{"date": "2026-08-25", "ratio": 1.0}],
        }

        updated = ft.update_ratio_history(history, {"archlinux-2026.08.01-x86_64.iso": 1.1}, today)

        # Only 4 days since the last sample (< the 7-day interval) - no new
        # sample yet, and the ratio value on the existing sample is untouched.
        self.assertEqual(
            updated,
            {"archlinux-2026.08.01-x86_64.iso": [{"date": "2026-08-25", "ratio": 1.0}]},
        )

    def test_new_sample_added_once_interval_elapses(self):
        today = date(2026, 8, 29)
        history = {
            "archlinux-2026.08.01-x86_64.iso": [{"date": "2026-08-20", "ratio": 1.0}],
        }

        updated = ft.update_ratio_history(history, {"archlinux-2026.08.01-x86_64.iso": 1.3}, today)

        self.assertEqual(
            updated,
            {
                "archlinux-2026.08.01-x86_64.iso": [
                    {"date": "2026-08-20", "ratio": 1.0},
                    {"date": "2026-08-29", "ratio": 1.3},
                ]
            },
        )

    def test_samples_older_than_window_plus_interval_are_pruned(self):
        today = date(2026, 8, 29)
        history = {
            "archlinux-2026.08.01-x86_64.iso": [
                {"date": "2026-06-01", "ratio": 0.5},  # ~89 days old - long stale
                {"date": "2026-08-10", "ratio": 1.0},  # ~19 days old - kept
            ],
        }

        updated = ft.update_ratio_history(
            history, {"archlinux-2026.08.01-x86_64.iso": 1.0}, today, window_days=30
        )

        dates = [s["date"] for s in updated["archlinux-2026.08.01-x86_64.iso"]]
        self.assertNotIn("2026-06-01", dates)
        self.assertIn("2026-08-10", dates)

    def test_torrent_no_longer_seeding_is_dropped(self):
        today = date(2026, 8, 29)
        history = {
            "archlinux-2026.07.01-x86_64.iso": [{"date": "2026-08-20", "ratio": 1.0}],
        }

        updated = ft.update_ratio_history(history, {}, today)

        self.assertEqual(updated, {})


class PlanStagnationCleanupTests(unittest.TestCase):
    """plan_stagnation_cleanup() removes only superseded (non-latest)
    versions within a (distro, type) group once their ratio has stopped
    growing - the newest/only version of a group is never a candidate,
    since removing it would just get it re-fetched and re-downloaded the
    next run (should_fetch_torrent() only skips a fetch when a *previous*
    version's ratio is on record)."""

    def test_latest_or_only_version_is_never_removed_even_if_flat(self):
        today = date(2026, 8, 29)
        torrents = [FakeTorrent("archlinux-2026.08.01-x86_64.iso", 1, ratio=1.0)]
        # 60 days of a perfectly flat ratio - as stagnant as it gets.
        history = {
            "archlinux-2026.08.01-x86_64.iso": [{"date": "2026-06-30", "ratio": 1.0}],
        }

        to_remove, to_keep = ft.plan_stagnation_cleanup(torrents, history, today, window_days=30, min_ratio_delta=0.02)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep, [])

    def test_old_version_with_no_ratio_growth_is_removed(self):
        today = date(2026, 8, 29)
        torrents = [
            FakeTorrent("ubuntu-24.04.1-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.500),
        ]
        history = {
            "ubuntu-23.10-desktop-amd64.iso": [{"date": "2026-07-20", "ratio": 1.495}],
        }

        to_remove, to_keep = ft.plan_stagnation_cleanup(torrents, history, today, window_days=30, min_ratio_delta=0.02)

        self.assertEqual(names_of(to_remove), ["ubuntu-23.10-desktop-amd64.iso"])
        self.assertEqual(to_keep, [])

    def test_old_version_still_growing_is_kept(self):
        today = date(2026, 8, 29)
        torrents = [
            FakeTorrent("ubuntu-24.04.1-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.8),
        ]
        history = {
            "ubuntu-23.10-desktop-amd64.iso": [{"date": "2026-07-20", "ratio": 1.2}],
        }

        to_remove, to_keep = ft.plan_stagnation_cleanup(torrents, history, today, window_days=30, min_ratio_delta=0.02)

        self.assertEqual(to_remove, [])
        self.assertEqual(len(to_keep), 1)
        kept_torrent, delta = to_keep[0]
        self.assertEqual(kept_torrent.name, "ubuntu-23.10-desktop-amd64.iso")
        self.assertAlmostEqual(delta, 0.6)

    def test_old_version_without_enough_history_is_kept(self):
        today = date(2026, 8, 29)
        torrents = [
            FakeTorrent("ubuntu-24.04.1-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.1),
        ]
        # Only 5 days of history - too young to judge either way.
        history = {
            "ubuntu-23.10-desktop-amd64.iso": [{"date": "2026-08-24", "ratio": 0.1}],
        }

        to_remove, to_keep = ft.plan_stagnation_cleanup(torrents, history, today, window_days=30, min_ratio_delta=0.02)

        self.assertEqual(to_remove, [])
        self.assertEqual(len(to_keep), 1)
        kept_torrent, delta = to_keep[0]
        self.assertEqual(kept_torrent.name, "ubuntu-23.10-desktop-amd64.iso")
        self.assertIsNone(delta)

    def test_old_version_with_no_history_at_all_is_kept(self):
        today = date(2026, 8, 29)
        torrents = [
            FakeTorrent("ubuntu-24.04.1-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.1),
        ]

        to_remove, to_keep = ft.plan_stagnation_cleanup(torrents, {}, today, window_days=30, min_ratio_delta=0.02)

        self.assertEqual(to_remove, [])
        self.assertEqual(len(to_keep), 1)

    def test_unrelated_single_torrent_groups_are_ignored(self):
        today = date(2026, 8, 29)
        torrents = [FakeTorrent("some-random-linux-distro-1.0.iso", 1, ratio=5.0)]

        to_remove, to_keep = ft.plan_stagnation_cleanup(torrents, {}, today, window_days=30, min_ratio_delta=0.02)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep, [])


class RatioHistoryPersistenceTests(unittest.TestCase):
    """load_ratio_history()/save_ratio_history() must round-trip cleanly and
    tolerate a missing or corrupt file rather than crashing a run."""

    def test_round_trips_through_disk(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_ratio_history_')
        path = os.path.join(tmp_dir, 'fetch_torrents_ratio_history.json')
        history = {"archlinux-2026.08.01-x86_64.iso": [{"date": "2026-08-29", "ratio": 1.2}]}

        ft.save_ratio_history(path, history)
        loaded = ft.load_ratio_history(path)

        self.assertEqual(loaded, history)

    def test_missing_file_returns_empty_history(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_ratio_history_')
        path = os.path.join(tmp_dir, 'does-not-exist.json')

        self.assertEqual(ft.load_ratio_history(path), {})

    def test_corrupt_file_returns_empty_history_instead_of_raising(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_ratio_history_')
        path = os.path.join(tmp_dir, 'fetch_torrents_ratio_history.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{not valid json')

        self.assertEqual(ft.load_ratio_history(path), {})


if __name__ == "__main__":
    unittest.main()
