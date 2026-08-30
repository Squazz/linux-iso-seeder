"""Tests for fetch_torrents.py, focused on the cleanup_old_versions() logic.

fetch_torrents.py is written to run inside the container: it imports
transmission_rpc (an apk-only package not available via pip) and opens log
files under /logs at import time. To make the module importable in a plain
test environment, this file stubs transmission_rpc and points
FETCH_TORRENTS_LOG_DIR at a temp directory before importing it.

Run with: python -m unittest discover -s tests
"""
import json
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


class LogFileRotationTests(unittest.TestCase):
    """fetch_torrents.log must be bounded (RotatingFileHandler), not a plain
    FileHandler appending forever for the life of a 'deploy and forget'
    container. Import-time behavior driven by env vars, so this uses a fresh
    subprocess like RatioLogSurvivesRestartTests, rather than the
    already-imported module (whose handler was built once, at whatever env
    was in effect during test collection)."""

    def _run(self, extra_env=None):
        log_dir = tempfile.mkdtemp(prefix='fetch_torrents_log_rotation_')
        script = (
            "import os, sys, types\n"
            "from unittest.mock import MagicMock\n"
            "stub = types.ModuleType('transmission_rpc')\n"
            "stub.Client = MagicMock()\n"
            "sys.modules['transmission_rpc'] = stub\n"
            f"sys.path.insert(0, {REPO_ROOT!r})\n"
            "import fetch_torrents as ft\n"
            "print(type(ft.file_handler).__name__)\n"
            "print(ft.file_handler.maxBytes)\n"
            "print(ft.file_handler.backupCount)\n"
        )
        env = dict(os.environ, FETCH_TORRENTS_LOG_DIR=log_dir, **(extra_env or {}))
        result = subprocess.run(
            [sys.executable, '-c', script],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        return lines[0], int(lines[1]), int(lines[2])

    def test_defaults_to_a_bounded_rotating_handler(self):
        handler_type, max_bytes, backup_count = self._run()
        self.assertEqual(handler_type, 'RotatingFileHandler')
        self.assertEqual(max_bytes, 5 * 1024 * 1024)
        self.assertEqual(backup_count, 3)

    def test_env_vars_override_rotation_settings(self):
        _handler_type, max_bytes, backup_count = self._run({
            'FETCH_TORRENTS_LOG_MAX_BYTES': '1000', 'FETCH_TORRENTS_LOG_BACKUP_COUNT': '1',
        })
        self.assertEqual(max_bytes, 1000)
        self.assertEqual(backup_count, 1)

    def test_invalid_env_vars_fall_back_to_defaults(self):
        _handler_type, max_bytes, backup_count = self._run({
            'FETCH_TORRENTS_LOG_MAX_BYTES': 'not-a-number', 'FETCH_TORRENTS_LOG_BACKUP_COUNT': 'also-bad',
        })
        self.assertEqual(max_bytes, 5 * 1024 * 1024)
        self.assertEqual(backup_count, 3)


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


class SafeWatchPathTests(unittest.TestCase):
    """_safe_watch_path() is the shared guard download_torrent(),
    _remove_watch_file(), and check_old_releases_for_demand() all rely on to
    keep a torrent name confined to a single file directly under watch_dir -
    defense in depth against a future fetch_*() parser turning scraped
    upstream content into a path escape."""

    def setUp(self):
        patcher = unittest.mock.patch.object(ft, 'watch_dir', '/watch')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_normal_name_resolves_under_watch_dir(self):
        self.assertEqual(
            ft._safe_watch_path('ubuntu-24.04-desktop-amd64.iso'),
            os.path.join('/watch', 'ubuntu-24.04-desktop-amd64.iso.torrent'),
        )

    def test_rejects_path_separators(self):
        self.assertIsNone(ft._safe_watch_path('archlinux-../../../etc/cron.d/evil'))
        self.assertIsNone(ft._safe_watch_path('foo/bar'))
        self.assertIsNone(ft._safe_watch_path('foo\\bar'))

    def test_rejects_empty_or_dot_names(self):
        self.assertIsNone(ft._safe_watch_path(''))
        self.assertIsNone(ft._safe_watch_path(None))
        self.assertIsNone(ft._safe_watch_path('.'))
        self.assertIsNone(ft._safe_watch_path('..'))


class DownloadTorrentUnsafeNameTests(unittest.TestCase):
    def setUp(self):
        self.tmp_watch_dir = tempfile.mkdtemp(prefix='fetch_torrents_test_watch_')
        patcher = unittest.mock.patch.object(ft, 'watch_dir', self.tmp_watch_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_download_torrent_refuses_unsafe_name_without_any_request(self):
        with unittest.mock.patch.object(ft.requests, 'get') as mock_get:
            status = ft.download_torrent('../evil', 'https://example.invalid/x.torrent')

        mock_get.assert_not_called()
        self.assertEqual(status, 'failed')
        self.assertEqual(os.listdir(self.tmp_watch_dir), [])

    def test_remove_watch_file_refuses_unsafe_name_without_touching_disk(self):
        with unittest.mock.patch.object(ft.os, 'remove') as mock_remove:
            ft._remove_watch_file('../evil')

        mock_remove.assert_not_called()


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


class FetchKaliOldVersionsTests(unittest.TestCase):
    """fetch_kali_old_versions() discovers the prior release(s) still listed
    on cdimage.kali.org (a 'current/' symlink plus a small number of
    'kali-X.Y/' folders), for FETCH_TORRENTS_CHECK_OLD_RELEASES. Only ever
    used when that flag is enabled - see CheckOldReleasesForDemandTests."""

    def test_returns_only_the_non_newest_versions(self):
        html = (
            "<html><body>"
            '<a href="current/">current</a>'
            '<a href="kali-2026.1/">kali-2026.1</a>'
            '<a href="kali-2026.2/">kali-2026.2</a>'
            "</body></html>"
        )

        class FakeResponse:
            text = html

        with unittest.mock.patch.object(ft.requests, "get", return_value=FakeResponse()):
            results = ft.fetch_kali_old_versions()

        self.assertTrue(results)
        self.assertTrue(any("2026.1" in name for name in results))
        self.assertFalse(any("2026.2" in name for name in results))

    def test_single_version_folder_returns_nothing(self):
        html = '<html><body><a href="current/">current</a><a href="kali-2026.2/">kali-2026.2</a></body></html>'

        class FakeResponse:
            text = html

        with unittest.mock.patch.object(ft.requests, "get", return_value=FakeResponse()):
            results = ft.fetch_kali_old_versions()

        self.assertEqual(results, {})


class FetchFedoraWorkstationOldVersionsTests(unittest.TestCase):
    """Mirrors FetchFedoraWorkstationNamingTests, but for the versions
    fetch_fedora_workstation() discards as not-latest."""

    def test_returns_non_latest_versions_per_arch(self):
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
            results = ft.fetch_fedora_workstation_old_versions()

        self.assertEqual(
            results,
            {
                "Fedora-Workstation-Live-x86_64-43":
                    "https://torrent.fedoraproject.org/torrents/Fedora-Workstation-Live-x86_64-43.torrent",
                "Fedora-Workstation-Live-aarch64-43":
                    "https://torrent.fedoraproject.org/torrents/Fedora-Workstation-Live-aarch64-43.torrent",
            },
        )

    def test_single_version_per_arch_returns_nothing(self):
        html = '<html><body><a href="Fedora-Workstation-Live-x86_64-44.torrent">a</a></body></html>'

        class FakeResponse:
            text = html

            def raise_for_status(self):
                pass

        with unittest.mock.patch.object(ft.requests, "get", return_value=FakeResponse()):
            results = ft.fetch_fedora_workstation_old_versions()

        self.assertEqual(results, {})


class HasUnmetDemandTests(unittest.TestCase):
    """Demand requires an absolute floor (enough leechers to be worth the
    disk/bandwidth), a relative one (leechers reach some fraction of the
    seeder count - i.e. the swarm isn't already vastly over-served), and by
    default a real, currently-seeded copy to exist at all. A single leecher
    on a 1000-seeder swarm must never pass just because leechers>0, and a
    swarm with plenty of leechers but even more seeders (already well
    served) shouldn't either."""

    def test_none_scrape_result_is_no_demand(self):
        self.assertFalse(
            ft.has_unmet_demand(None, min_leechers=1, min_leecher_ratio=1.2, allow_zero_seeders=False)
        )

    def test_below_absolute_threshold_is_no_demand(self):
        self.assertFalse(
            ft.has_unmet_demand(
                {'leechers': 0, 'seeders': 0}, min_leechers=1, min_leecher_ratio=1.2, allow_zero_seeders=False
            )
        )

    def test_single_leecher_on_huge_swarm_is_no_demand(self):
        self.assertFalse(
            ft.has_unmet_demand(
                {'leechers': 1, 'seeders': 1000}, min_leechers=1, min_leecher_ratio=1.2, allow_zero_seeders=False
            )
        )

    def test_meets_absolute_but_not_ratio_is_no_demand(self):
        # 11 leechers clears a min_leechers=10 floor, but 11 < 1.2x the 10 seeders.
        self.assertFalse(
            ft.has_unmet_demand(
                {'leechers': 11, 'seeders': 10}, min_leechers=10, min_leecher_ratio=1.2, allow_zero_seeders=False
            )
        )

    def test_meets_both_absolute_and_ratio_thresholds_is_demand(self):
        self.assertTrue(
            ft.has_unmet_demand(
                {'leechers': 25, 'seeders': 10}, min_leechers=10, min_leecher_ratio=1.2, allow_zero_seeders=False
            )
        )

    def test_exactly_at_ratio_threshold_is_demand(self):
        self.assertTrue(
            ft.has_unmet_demand(
                {'leechers': 12, 'seeders': 10}, min_leechers=10, min_leecher_ratio=1.2, allow_zero_seeders=False
            )
        )

    def test_zero_seeders_is_excluded_by_default(self):
        # A scrape can't tell us whether the leechers collectively hold every
        # piece - with zero seeders there's no verified-complete copy in the
        # swarm at all, so we could end up leeching something we can never
        # finish and therefore never seed back. Excluded unless the operator
        # opts into the gamble via allow_zero_seeders.
        self.assertFalse(
            ft.has_unmet_demand(
                {'leechers': 10, 'seeders': 0}, min_leechers=10, min_leecher_ratio=1.2, allow_zero_seeders=False
            )
        )

    def test_zero_seeders_counts_as_demand_when_explicitly_allowed(self):
        self.assertTrue(
            ft.has_unmet_demand(
                {'leechers': 10, 'seeders': 0}, min_leechers=10, min_leecher_ratio=1.2, allow_zero_seeders=True
            )
        )

    def test_zero_seeders_still_needs_the_absolute_floor_when_allowed(self):
        self.assertFalse(
            ft.has_unmet_demand(
                {'leechers': 5, 'seeders': 0}, min_leechers=10, min_leecher_ratio=1.2, allow_zero_seeders=True
            )
        )

    def test_lopsided_but_substantial_swarms_still_count_as_demand_at_default_ratio(self):
        # FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHER_RATIO defaults to 0.1: we
        # have no way of knowing whether existing seeders have spare upload
        # capacity or are bandwidth-limited, so leechers don't need to
        # approach or outnumber seeders to represent real demand - 10:100
        # and 100:1000 both clearly indicate room for another seeder.
        self.assertTrue(
            ft.has_unmet_demand(
                {'leechers': 10, 'seeders': 100}, min_leechers=1, min_leecher_ratio=0.1, allow_zero_seeders=False
            )
        )
        self.assertTrue(
            ft.has_unmet_demand(
                {'leechers': 100, 'seeders': 1000}, min_leechers=1, min_leecher_ratio=0.1, allow_zero_seeders=False
            )
        )

    def test_extreme_oversupply_still_fails_at_default_ratio(self):
        # 3 leechers on 673 seeders (an actual old Kali release scraped
        # during development) is still not demand, even at the more
        # permissive 0.1 default - it needs at least 67.3 leechers.
        self.assertFalse(
            ft.has_unmet_demand(
                {'leechers': 3, 'seeders': 673}, min_leechers=1, min_leecher_ratio=0.1, allow_zero_seeders=False
            )
        )


class EvaluateOldReleaseDemandTests(unittest.TestCase):
    def test_404_is_not_kept_and_not_scraped(self):
        class FakeResponse:
            status_code = 404

        with unittest.mock.patch.object(ft.requests, 'get', return_value=FakeResponse()), \
                unittest.mock.patch.object(ft.torrent_scrape, 'scrape_torrent') as mock_scrape:
            keep, torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                'ubuntu-14.04.6-desktop-amd64.iso', 'https://example.invalid/x.torrent',
                min_leechers=1, min_leecher_ratio=1.2, allow_zero_seeders=False,
            )

        mock_scrape.assert_not_called()
        self.assertFalse(keep)
        self.assertIsNone(torrent_bytes)
        self.assertIsNone(scrape_result)

    def test_download_failure_is_not_kept(self):
        with unittest.mock.patch.object(ft.requests, 'get', side_effect=ConnectionError("nope")):
            keep, torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                'ubuntu-14.04.6-desktop-amd64.iso', 'https://example.invalid/x.torrent',
                min_leechers=1, min_leecher_ratio=1.2, allow_zero_seeders=False,
            )

        self.assertFalse(keep)
        self.assertIsNone(torrent_bytes)
        self.assertIsNone(scrape_result)

    def test_scrape_below_threshold_is_not_kept(self):
        class FakeResponse:
            status_code = 200
            content = b'fake torrent bytes'

            def raise_for_status(self):
                pass

        with unittest.mock.patch.object(ft.requests, 'get', return_value=FakeResponse()), \
                unittest.mock.patch.object(
                    ft.torrent_scrape, 'scrape_torrent',
                    return_value={'tracker': 'http://t.example/scrape', 'seeders': 10, 'leechers': 0, 'completed': 0},
                ):
            keep, torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                'ubuntu-14.04.6-desktop-amd64.iso', 'https://example.invalid/x.torrent',
                min_leechers=1, min_leecher_ratio=1.2, allow_zero_seeders=False,
            )

        self.assertFalse(keep)
        self.assertEqual(torrent_bytes, b'fake torrent bytes')
        self.assertEqual(scrape_result['leechers'], 0)

    def test_scrape_meeting_threshold_is_kept(self):
        class FakeResponse:
            status_code = 200
            content = b'fake torrent bytes'

            def raise_for_status(self):
                pass

        with unittest.mock.patch.object(ft.requests, 'get', return_value=FakeResponse()), \
                unittest.mock.patch.object(
                    ft.torrent_scrape, 'scrape_torrent',
                    return_value={'tracker': 'http://t.example/scrape', 'seeders': 10, 'leechers': 30, 'completed': 0},
                ):
            keep, torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                'ubuntu-14.04.6-desktop-amd64.iso', 'https://example.invalid/x.torrent',
                min_leechers=1, min_leecher_ratio=1.2, allow_zero_seeders=False,
            )

        self.assertTrue(keep)
        self.assertEqual(torrent_bytes, b'fake torrent bytes')
        self.assertEqual(scrape_result['leechers'], 30)

    def test_meets_absolute_floor_but_already_well_seeded_is_not_kept(self):
        class FakeResponse:
            status_code = 200
            content = b'fake torrent bytes'

            def raise_for_status(self):
                pass

        # 1 leecher clears a min_leechers=1 floor, but 1000 seeders already
        # cover it - not unmet demand.
        with unittest.mock.patch.object(ft.requests, 'get', return_value=FakeResponse()), \
                unittest.mock.patch.object(
                    ft.torrent_scrape, 'scrape_torrent',
                    return_value={'tracker': 'http://t.example/scrape', 'seeders': 1000, 'leechers': 1, 'completed': 0},
                ):
            keep, torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                'ubuntu-14.04.6-desktop-amd64.iso', 'https://example.invalid/x.torrent',
                min_leechers=1, min_leecher_ratio=1.2, allow_zero_seeders=False,
            )

        self.assertFalse(keep)
        self.assertEqual(scrape_result['leechers'], 1)


class CheckOldReleasesForDemandTests(unittest.TestCase):
    def setUp(self):
        self.tmp_watch_dir = tempfile.mkdtemp(prefix='fetch_torrents_test_watch_')
        patcher = unittest.mock.patch.object(ft, 'watch_dir', self.tmp_watch_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_adds_only_torrents_with_unmet_demand(self):
        # Neither name matches LOW_DEMAND_PATTERN - that filtering is
        # covered separately by test_low_demand_variant_is_filtered_before_evaluation.
        candidates = {
            'kali-linux-2026.1-installer-purple-amd64.iso': 'https://example.invalid/dead.torrent',
            'kali-linux-2026.1-installer-amd64.iso': 'https://example.invalid/alive.torrent',
        }

        def fake_evaluate(name, url, min_leechers, min_leecher_ratio, allow_zero_seeders, timeout=15):
            if 'purple' in name:
                return False, b'dead bytes', {'tracker': 't', 'seeders': 5, 'leechers': 0, 'completed': 0}
            return True, b'alive bytes', {'tracker': 't', 'seeders': 5, 'leechers': 30, 'completed': 0}

        with unittest.mock.patch.dict(ft.OLD_RELEASE_DISCOVERY, {'kali': lambda: candidates}, clear=True), \
                unittest.mock.patch.object(ft, 'evaluate_old_release_demand', side_effect=fake_evaluate):
            added, skipped, _ = ft.check_old_releases_for_demand(['kali'], include_low_demand=False, min_leechers=1, min_leecher_ratio=0.0, allow_zero_seeders=False)

        self.assertEqual(added, 1)
        self.assertEqual(skipped, 1)
        alive_path = os.path.join(self.tmp_watch_dir, 'kali-linux-2026.1-installer-amd64.iso.torrent')
        dead_path = os.path.join(self.tmp_watch_dir, 'kali-linux-2026.1-installer-purple-amd64.iso.torrent')
        with open(alive_path, 'rb') as f:
            self.assertEqual(f.read(), b'alive bytes')
        self.assertFalse(os.path.exists(dead_path))

    def test_skips_distros_without_old_release_discovery(self):
        with unittest.mock.patch.dict(ft.OLD_RELEASE_DISCOVERY, {}, clear=True):
            added, skipped, _ = ft.check_old_releases_for_demand(['ubuntu'], include_low_demand=False, min_leechers=1, min_leecher_ratio=0.0, allow_zero_seeders=False)

        self.assertEqual((added, skipped), (0, 0))

    def test_already_present_torrent_is_not_re_evaluated(self):
        name = 'kali-linux-2026.1-installer-amd64.iso'
        existing_path = os.path.join(self.tmp_watch_dir, f'{name}.torrent')
        with open(existing_path, 'wb') as f:
            f.write(b'already here')

        with unittest.mock.patch.dict(
                    ft.OLD_RELEASE_DISCOVERY,
                    {'kali': lambda: {name: 'https://example.invalid/x.torrent'}}, clear=True,
                ), \
                unittest.mock.patch.object(ft, 'evaluate_old_release_demand') as mock_evaluate:
            added, skipped, _ = ft.check_old_releases_for_demand(['kali'], include_low_demand=False, min_leechers=1, min_leecher_ratio=0.0, allow_zero_seeders=False)

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 0))

    def test_unsafe_candidate_name_is_skipped_without_evaluation(self):
        name = 'kali-linux-2026.1-installer-../../etc/cron.d/evil'

        with unittest.mock.patch.dict(
                    ft.OLD_RELEASE_DISCOVERY,
                    {'kali': lambda: {name: 'https://example.invalid/x.torrent'}}, clear=True,
                ), \
                unittest.mock.patch.object(ft, 'evaluate_old_release_demand') as mock_evaluate:
            added, skipped, _ = ft.check_old_releases_for_demand(['kali'], include_low_demand=False, min_leechers=1, min_leecher_ratio=0.0, allow_zero_seeders=False)

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 1))

    def test_low_demand_variant_is_filtered_before_evaluation(self):
        name = 'kali-linux-2026.1-installer-netinst-amd64.iso'

        with unittest.mock.patch.dict(
                    ft.OLD_RELEASE_DISCOVERY,
                    {'kali': lambda: {name: 'https://example.invalid/x.torrent'}}, clear=True,
                ), \
                unittest.mock.patch.object(ft, 'evaluate_old_release_demand') as mock_evaluate:
            added, skipped, _ = ft.check_old_releases_for_demand(['kali'], include_low_demand=False, min_leechers=1, min_leecher_ratio=0.0, allow_zero_seeders=False)

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 0))


class FormatRunSummaryTests(unittest.TestCase):
    """format_run_summary() builds the single end-of-run log line - it must
    surface how many old-release torrents FETCH_TORRENTS_CHECK_OLD_RELEASES
    introduced, not just the counts from the normal latest-release fetch."""

    def test_without_old_release_check(self):
        summary = ft.format_run_summary(
            elapsed=12.5, success_count=3, existing_count=1, not_found_count=0, failure_count=0,
        )
        self.assertEqual(
            summary,
            "Run complete in 12.50 seconds. 3 added, 1 existing, 0 not found upstream, 0 failed.",
        )

    def test_with_old_release_check_appends_counts(self):
        summary = ft.format_run_summary(
            elapsed=12.5, success_count=3, existing_count=1, not_found_count=0, failure_count=0,
            old_added=2, old_skipped=6,
        )
        self.assertEqual(
            summary,
            "Run complete in 12.50 seconds. 3 added, 1 existing, 0 not found upstream, 0 failed. "
            "Old releases (FETCH_TORRENTS_CHECK_OLD_RELEASES): 2 added, 6 skipped.",
        )

    def test_still_starts_with_run_complete_for_always_log_filter(self):
        summary = ft.format_run_summary(
            elapsed=1.0, success_count=0, existing_count=0, not_found_count=0, failure_count=0,
            old_added=0, old_skipped=0,
        )
        self.assertTrue(summary.startswith("Run complete in"))


class ShouldRecheckOldReleaseTests(unittest.TestCase):
    """Without this gate, check_old_releases_for_demand() would re-download
    and re-scrape every not-yet-wanted candidate on every daily run
    forever - this is what lets a recent "no demand" result be trusted for
    a while instead."""

    def test_never_checked_is_due(self):
        self.assertTrue(ft.should_recheck_old_release('x', {}, date(2026, 1, 8), recheck_interval_days=7))

    def test_checked_recently_is_not_due(self):
        state = {'x': {'last_checked': '2026-01-05', 'leechers': 0}}
        self.assertFalse(ft.should_recheck_old_release('x', state, date(2026, 1, 8), recheck_interval_days=7))

    def test_checked_exactly_at_interval_is_due(self):
        state = {'x': {'last_checked': '2026-01-01', 'leechers': 0}}
        self.assertTrue(ft.should_recheck_old_release('x', state, date(2026, 1, 8), recheck_interval_days=7))

    def test_checked_past_interval_is_due(self):
        state = {'x': {'last_checked': '2025-12-01', 'leechers': 0}}
        self.assertTrue(ft.should_recheck_old_release('x', state, date(2026, 1, 8), recheck_interval_days=7))


class OldReleaseCheckStatePersistenceTests(unittest.TestCase):
    def test_round_trips_through_disk(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_old_release_state_')
        path = os.path.join(tmp_dir, 'fetch_torrents_old_release_check_state.json')
        state = {'x': {'last_checked': '2026-01-08', 'leechers': 0}}

        ft.save_old_release_check_state(path, state)
        loaded = ft.load_old_release_check_state(path)

        self.assertEqual(loaded, state)

    def test_missing_file_returns_empty_state(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_old_release_state_')
        path = os.path.join(tmp_dir, 'does-not-exist.json')

        self.assertEqual(ft.load_old_release_check_state(path), {})

    def test_corrupt_file_returns_empty_state_instead_of_raising(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_old_release_state_')
        path = os.path.join(tmp_dir, 'fetch_torrents_old_release_check_state.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{not valid json')

        self.assertEqual(ft.load_old_release_check_state(path), {})


class RecordRemovalTests(unittest.TestCase):
    def test_adds_entry_without_mutating_input(self):
        history = {}
        updated = ft.record_removal(history, 'kali-linux-2026.1-installer-amd64.iso', date(2026, 2, 1), 'stagnant')

        self.assertEqual(history, {})  # input untouched
        self.assertEqual(
            updated['kali-linux-2026.1-installer-amd64.iso'],
            {'removed_date': '2026-02-01', 'reason': 'stagnant'},
        )


class RemovedHistoryPersistenceTests(unittest.TestCase):
    def test_round_trips_through_disk(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_removed_history_')
        path = os.path.join(tmp_dir, 'fetch_torrents_removed_history.json')
        history = {'x': {'removed_date': '2026-02-01', 'reason': 'stagnant'}}

        ft.save_removed_history(path, history)
        loaded = ft.load_removed_history(path)

        self.assertEqual(loaded, history)

    def test_missing_file_returns_empty_history(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_removed_history_')
        path = os.path.join(tmp_dir, 'does-not-exist.json')

        self.assertEqual(ft.load_removed_history(path), {})

    def test_corrupt_file_returns_empty_history_instead_of_raising(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_removed_history_')
        path = os.path.join(tmp_dir, 'fetch_torrents_removed_history.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{not valid json')

        self.assertEqual(ft.load_removed_history(path), {})


class CheckOldReleasesForDemandStateTests(unittest.TestCase):
    """check_old_releases_for_demand() must consult both the recheck-state
    (skip candidates checked too recently) and the removed-history (skip
    candidates cleanup has already given up on) before ever hitting the
    network, and must record a fresh check for anything it does evaluate."""

    def setUp(self):
        self.tmp_watch_dir = tempfile.mkdtemp(prefix='fetch_torrents_test_watch_')
        patcher = unittest.mock.patch.object(ft, 'watch_dir', self.tmp_watch_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_recently_checked_candidate_is_skipped_without_network_call(self):
        name = 'kali-linux-2026.1-installer-amd64.iso'
        candidates = {name: 'https://example.invalid/x.torrent'}
        check_state = {name: {'last_checked': '2026-01-05', 'leechers': 0}}

        with unittest.mock.patch.dict(ft.OLD_RELEASE_DISCOVERY, {'kali': lambda: candidates}, clear=True), \
                unittest.mock.patch.object(ft, 'evaluate_old_release_demand') as mock_evaluate:
            added, skipped, new_state = ft.check_old_releases_for_demand(
                ['kali'], include_low_demand=False, min_leechers=1, min_leecher_ratio=0.0, allow_zero_seeders=False,
                check_state=check_state, removed_history={}, today=date(2026, 1, 8), recheck_interval_days=7,
            )

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(new_state, check_state)

    def test_previously_removed_candidate_is_skipped_without_network_call(self):
        name = 'kali-linux-2026.1-installer-amd64.iso'
        candidates = {name: 'https://example.invalid/x.torrent'}
        removed_history = {name: {'removed_date': '2026-01-01', 'reason': 'stagnant'}}

        with unittest.mock.patch.dict(ft.OLD_RELEASE_DISCOVERY, {'kali': lambda: candidates}, clear=True), \
                unittest.mock.patch.object(ft, 'evaluate_old_release_demand') as mock_evaluate:
            added, skipped, new_state = ft.check_old_releases_for_demand(
                ['kali'], include_low_demand=False, min_leechers=1, min_leecher_ratio=0.0, allow_zero_seeders=False,
                check_state={}, removed_history=removed_history, today=date(2026, 1, 8), recheck_interval_days=7,
            )

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 1))

    def test_due_candidate_is_evaluated_and_recorded(self):
        name = 'kali-linux-2026.1-installer-amd64.iso'
        candidates = {name: 'https://example.invalid/x.torrent'}

        with unittest.mock.patch.dict(ft.OLD_RELEASE_DISCOVERY, {'kali': lambda: candidates}, clear=True), \
                unittest.mock.patch.object(
                    ft, 'evaluate_old_release_demand',
                    return_value=(True, b'bytes', {'tracker': 't', 'seeders': 1, 'leechers': 30, 'completed': 0}),
                ):
            added, skipped, new_state = ft.check_old_releases_for_demand(
                ['kali'], include_low_demand=False, min_leechers=1, min_leecher_ratio=0.0, allow_zero_seeders=False,
                check_state={}, removed_history={}, today=date(2026, 1, 8), recheck_interval_days=7,
            )

        self.assertEqual((added, skipped), (1, 0))
        self.assertEqual(new_state[name], {'last_checked': '2026-01-08', 'leechers': 30})

    def test_no_demand_result_is_still_recorded_for_future_recheck_gating(self):
        name = 'kali-linux-2026.1-installer-arm64.iso'
        candidates = {name: 'https://example.invalid/x.torrent'}

        with unittest.mock.patch.dict(ft.OLD_RELEASE_DISCOVERY, {'kali': lambda: candidates}, clear=True), \
                unittest.mock.patch.object(
                    ft, 'evaluate_old_release_demand',
                    return_value=(False, b'bytes', {'tracker': 't', 'seeders': 1, 'leechers': 0, 'completed': 0}),
                ):
            added, skipped, new_state = ft.check_old_releases_for_demand(
                ['kali'], include_low_demand=False, min_leechers=1, min_leecher_ratio=0.0, allow_zero_seeders=False,
                check_state={}, removed_history={}, today=date(2026, 1, 8), recheck_interval_days=7,
            )

        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(new_state[name], {'last_checked': '2026-01-08', 'leechers': 0})


class CleanupRpcAuthTests(unittest.TestCase):
    """cleanup_old_versions()/cleanup_stagnant_torrents() must authenticate
    their own Transmission RPC connection the same way
    configure_transmission.py configured the daemon. Without this, a user
    who sets TRANSMISSION_RPC_USERNAME/PASSWORD (as the README requires once
    TRANSMISSION_RPC_WHITELIST is widened beyond localhost) finds cleanup
    silently stops working forever: every RPC call fails with 401 and the
    failure is only logged, never surfaced."""

    def setUp(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_cleanup_auth_')
        for attr, filename in (
            ('removed_history_file', 'removed_history.json'),
            ('ratio_history_file', 'ratio_history.json'),
        ):
            patcher = unittest.mock.patch.object(ft, attr, os.path.join(tmp_dir, filename))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _mock_client(self):
        client = MagicMock()
        client.get_torrents.return_value = []
        return client

    def test_cleanup_old_versions_passes_configured_credentials(self):
        with unittest.mock.patch.dict(os.environ, {
            'TRANSMISSION_RPC_USERNAME': 'alice', 'TRANSMISSION_RPC_PASSWORD': 'hunter2',
        }), unittest.mock.patch.object(ft, 'Client', return_value=self._mock_client()) as mock_client_cls:
            ft.cleanup_old_versions()

        mock_client_cls.assert_called_once_with(host='localhost', port=9091, username='alice', password='hunter2')

    def test_cleanup_old_versions_passes_no_credentials_when_unset(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TRANSMISSION_RPC_USERNAME', None)
            os.environ.pop('TRANSMISSION_RPC_PASSWORD', None)
            with unittest.mock.patch.object(ft, 'Client', return_value=self._mock_client()) as mock_client_cls:
                ft.cleanup_old_versions()

        mock_client_cls.assert_called_once_with(host='localhost', port=9091, username=None, password=None)

    def test_cleanup_stagnant_torrents_passes_configured_credentials(self):
        with unittest.mock.patch.dict(os.environ, {
            'TRANSMISSION_RPC_USERNAME': 'alice', 'TRANSMISSION_RPC_PASSWORD': 'hunter2',
        }), unittest.mock.patch.object(ft, 'Client', return_value=self._mock_client()) as mock_client_cls:
            ft.cleanup_stagnant_torrents()

        mock_client_cls.assert_called_once_with(host='localhost', port=9091, username='alice', password='hunter2')


class LogSeedRatiosViaHttpTests(unittest.TestCase):
    """log_seed_ratios_via_http() must not hang the daily run forever on a
    stalled Transmission response, and must authenticate with whatever
    credentials configure_transmission.py configured the daemon with when
    the caller doesn't explicitly override auth."""

    class FakeSessionIdResponse:
        headers = {"X-Transmission-Session-Id": "abc"}

    class FakeTorrentGetResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"arguments": {"torrents": []}}

    def test_session_id_request_has_a_timeout(self):
        with unittest.mock.patch.object(
            ft.requests, 'post',
            side_effect=[self.FakeSessionIdResponse(), self.FakeTorrentGetResponse()],
        ) as mock_post:
            ft.log_seed_ratios_via_http()

        first_call_kwargs = mock_post.call_args_list[0].kwargs
        self.assertIn('timeout', first_call_kwargs)

    def test_uses_configured_credentials_when_auth_not_explicitly_passed(self):
        with unittest.mock.patch.dict(os.environ, {
            'TRANSMISSION_RPC_USERNAME': 'alice', 'TRANSMISSION_RPC_PASSWORD': 'hunter2',
        }), unittest.mock.patch.object(
            ft.requests, 'post',
            side_effect=[self.FakeSessionIdResponse(), self.FakeTorrentGetResponse()],
        ) as mock_post:
            ft.log_seed_ratios_via_http()

        second_call_kwargs = mock_post.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get('auth'), ('alice', 'hunter2'))

    def test_no_auth_when_credentials_unset(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TRANSMISSION_RPC_USERNAME', None)
            os.environ.pop('TRANSMISSION_RPC_PASSWORD', None)
            with unittest.mock.patch.object(
                ft.requests, 'post',
                side_effect=[self.FakeSessionIdResponse(), self.FakeTorrentGetResponse()],
            ) as mock_post:
                ft.log_seed_ratios_via_http()

        second_call_kwargs = mock_post.call_args_list[1].kwargs
        self.assertIsNone(second_call_kwargs.get('auth'))

    def test_explicit_auth_argument_still_wins(self):
        with unittest.mock.patch.dict(os.environ, {
            'TRANSMISSION_RPC_USERNAME': 'alice', 'TRANSMISSION_RPC_PASSWORD': 'hunter2',
        }), unittest.mock.patch.object(
            ft.requests, 'post',
            side_effect=[self.FakeSessionIdResponse(), self.FakeTorrentGetResponse()],
        ) as mock_post:
            ft.log_seed_ratios_via_http(auth=('bob', 'other'))

        second_call_kwargs = mock_post.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get('auth'), ('bob', 'other'))


class CleanupRemovesWatchFileTests(unittest.TestCase):
    """When cleanup removes a torrent's downloaded data, it must also remove
    the small .torrent file it left behind in /watch - otherwise these
    accumulate forever, since nothing else (including Transmission itself,
    by default) ever cleans them up."""

    def setUp(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_cleanup_watchfile_')
        for attr, filename in (
            ('removed_history_file', 'removed_history.json'),
            ('ratio_history_file', 'ratio_history.json'),
        ):
            patcher = unittest.mock.patch.object(ft, attr, os.path.join(tmp_dir, filename))
            patcher.start()
            self.addCleanup(patcher.stop)

        self.tmp_watch_dir = tempfile.mkdtemp(prefix='fetch_torrents_test_watch_')
        patcher = unittest.mock.patch.object(ft, 'watch_dir', self.tmp_watch_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _touch_watch_file(self, name):
        path = os.path.join(self.tmp_watch_dir, f"{name}.torrent")
        with open(path, 'w', encoding='utf-8') as f:
            f.write('fake torrent bytes')
        return path

    def test_cleanup_old_versions_removes_the_watch_file(self):
        old_path = self._touch_watch_file('ubuntu-23.10-desktop-amd64.iso')
        self._touch_watch_file('ubuntu-24.04-desktop-amd64.iso')
        torrents = [
            FakeTorrent('ubuntu-24.04-desktop-amd64.iso', 1, ratio=2.0),
            FakeTorrent('ubuntu-23.10-desktop-amd64.iso', 2, ratio=2.0),
        ]
        client = MagicMock()
        client.get_torrents.return_value = torrents

        with unittest.mock.patch.dict(os.environ, {'CLEANUP_SKIP_RATIO_CHECK': 'true'}), \
                unittest.mock.patch.object(ft, 'Client', return_value=client):
            ft.cleanup_old_versions()

        client.remove_torrent.assert_called_once_with(2, delete_data=True)
        self.assertFalse(os.path.exists(old_path))

    def test_missing_watch_file_does_not_raise(self):
        # No .torrent file created for the superseded version - cleanup must
        # still succeed and remove the torrent from Transmission.
        torrents = [
            FakeTorrent('ubuntu-24.04-desktop-amd64.iso', 1, ratio=2.0),
            FakeTorrent('ubuntu-23.10-desktop-amd64.iso', 2, ratio=2.0),
        ]
        client = MagicMock()
        client.get_torrents.return_value = torrents

        with unittest.mock.patch.dict(os.environ, {'CLEANUP_SKIP_RATIO_CHECK': 'true'}), \
                unittest.mock.patch.object(ft, 'Client', return_value=client):
            ft.cleanup_old_versions()  # must not raise

        client.remove_torrent.assert_called_once_with(2, delete_data=True)

    def test_cleanup_stagnant_torrents_removes_the_watch_file(self):
        old_path = self._touch_watch_file('ubuntu-23.10-desktop-amd64.iso')
        self._touch_watch_file('ubuntu-24.04-desktop-amd64.iso')
        torrents = [
            FakeTorrent('ubuntu-24.04-desktop-amd64.iso', 1, ratio=2.0),
            FakeTorrent('ubuntu-23.10-desktop-amd64.iso', 2, ratio=2.0),
        ]
        client = MagicMock()
        client.get_torrents.return_value = torrents

        # 32 days old: past the default 30-day stagnation window, but still
        # within update_ratio_history()'s own 37-day (window + sample
        # interval) prune horizon, since that prune runs - on this same
        # history - before plan_stagnation_cleanup() ever sees it. Ratio
        # unchanged since then, so plan_stagnation_cleanup() must select this
        # torrent for removal.
        anchor_date = (date.today() - timedelta(days=32)).isoformat()
        history = {'ubuntu-23.10-desktop-amd64.iso': [{'date': anchor_date, 'ratio': 2.0}]}
        with open(ft.ratio_history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f)

        with unittest.mock.patch.object(ft, 'Client', return_value=client):
            ft.cleanup_stagnant_torrents()

        client.remove_torrent.assert_called_once_with(2, delete_data=True)
        self.assertFalse(os.path.exists(old_path))


class PlanDiskPressureCleanupTests(unittest.TestCase):
    """plan_disk_pressure_cleanup() is the pure selection logic behind
    CLEANUP_DISK_USAGE_THRESHOLD_PERCENT - the safety valve that kicks in
    when normal ratio/stagnation-based cleanup isn't freeing space fast
    enough for a forgotten, never-updated deployment."""

    def test_below_threshold_returns_nothing(self):
        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.1),
        ]
        self.assertEqual(ft.plan_disk_pressure_cleanup(torrents, used_percent=80.0, threshold_percent=95.0), [])

    def test_disabled_when_threshold_is_zero_or_negative(self):
        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.1),
        ]
        self.assertEqual(ft.plan_disk_pressure_cleanup(torrents, used_percent=99.0, threshold_percent=0), [])
        self.assertEqual(ft.plan_disk_pressure_cleanup(torrents, used_percent=99.0, threshold_percent=-1), [])

    def test_at_or_above_threshold_returns_candidates_lowest_ratio_first(self):
        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=5.0),   # latest - never a candidate
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.5),
            FakeTorrent("ubuntu-22.04.1-live-server-amd64.iso", 3, ratio=0.2),
            FakeTorrent("ubuntu-24.04.1-live-server-amd64.iso", 4, ratio=5.0),  # latest of this group
        ]
        result = ft.plan_disk_pressure_cleanup(torrents, used_percent=95.0, threshold_percent=95.0)
        self.assertEqual(
            names_of(result),
            ["ubuntu-22.04.1-live-server-amd64.iso", "ubuntu-23.10-desktop-amd64.iso"],
        )
        # lowest ratio (least useful) first
        self.assertEqual(result[0].name, "ubuntu-22.04.1-live-server-amd64.iso")

    def test_no_superseded_candidates_returns_empty(self):
        torrents = [FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=0.0)]
        self.assertEqual(ft.plan_disk_pressure_cleanup(torrents, used_percent=99.0, threshold_percent=95.0), [])


class EnforceDiskUsageLimitTests(unittest.TestCase):
    """enforce_disk_usage_limit() wires plan_disk_pressure_cleanup() to a
    live Transmission connection and real disk usage, re-checking usage
    between removals since ratio data alone can't say how many bytes each
    torrent holds."""

    def setUp(self):
        tmp_dir = tempfile.mkdtemp(prefix='fetch_torrents_disk_pressure_')
        for attr, filename in (
            ('removed_history_file', 'removed_history.json'),
            ('ratio_history_file', 'ratio_history.json'),
        ):
            patcher = unittest.mock.patch.object(ft, attr, os.path.join(tmp_dir, filename))
            patcher.start()
            self.addCleanup(patcher.stop)

        self.tmp_watch_dir = tempfile.mkdtemp(prefix='fetch_torrents_test_watch_')
        patcher = unittest.mock.patch.object(ft, 'watch_dir', self.tmp_watch_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled_threshold_never_touches_disk_or_rpc(self):
        with unittest.mock.patch.object(ft.shutil, 'disk_usage') as mock_disk_usage, \
                unittest.mock.patch.object(ft, 'Client') as mock_client_cls:
            ft.enforce_disk_usage_limit(0)

        mock_disk_usage.assert_not_called()
        mock_client_cls.assert_not_called()

    def test_below_threshold_does_not_connect_to_transmission(self):
        with unittest.mock.patch.object(ft.shutil, 'disk_usage', return_value=(100, 50, 50)), \
                unittest.mock.patch.object(ft, 'Client') as mock_client_cls:
            ft.enforce_disk_usage_limit(95)

        mock_client_cls.assert_not_called()

    def test_removes_lowest_ratio_candidates_until_under_threshold(self):
        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=5.0),  # latest, never removed
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.5),
            FakeTorrent("ubuntu-22.04-desktop-amd64.iso", 3, ratio=0.2),
        ]
        client = MagicMock()
        client.get_torrents.return_value = torrents

        # 96% initially (over threshold); drops to 90% (under threshold)
        # after the first removal - the second, higher-ratio candidate must
        # be left alone.
        with unittest.mock.patch.object(
            ft.shutil, 'disk_usage', side_effect=[(100, 96, 4), (100, 96, 4), (100, 90, 10)],
        ), unittest.mock.patch.object(ft, 'Client', return_value=client):
            ft.enforce_disk_usage_limit(95)

        client.remove_torrent.assert_called_once_with(3, delete_data=True)

    def test_removes_the_watch_file_for_each_removal(self):
        watch_path = os.path.join(self.tmp_watch_dir, "ubuntu-22.04-desktop-amd64.iso.torrent")
        with open(watch_path, 'w', encoding='utf-8') as f:
            f.write('fake torrent bytes')

        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=5.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.5),
            FakeTorrent("ubuntu-22.04-desktop-amd64.iso", 3, ratio=0.2),
        ]
        client = MagicMock()
        client.get_torrents.return_value = torrents

        with unittest.mock.patch.object(
            ft.shutil, 'disk_usage', side_effect=[(100, 96, 4), (100, 96, 4), (100, 90, 10)],
        ), unittest.mock.patch.object(ft, 'Client', return_value=client):
            ft.enforce_disk_usage_limit(95)

        self.assertFalse(os.path.exists(watch_path))

    def test_no_candidates_logs_warning_and_does_not_raise(self):
        torrents = [FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=5.0)]
        client = MagicMock()
        client.get_torrents.return_value = torrents

        with unittest.mock.patch.object(ft.shutil, 'disk_usage', return_value=(100, 96, 4)), \
                unittest.mock.patch.object(ft, 'Client', return_value=client):
            ft.enforce_disk_usage_limit(95)  # must not raise

        client.remove_torrent.assert_not_called()

    def test_records_removal_reason_as_disk_pressure(self):
        torrents = [
            FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=5.0),
            FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.5),
            FakeTorrent("ubuntu-22.04-desktop-amd64.iso", 3, ratio=0.2),
        ]
        client = MagicMock()
        client.get_torrents.return_value = torrents

        with unittest.mock.patch.object(
            ft.shutil, 'disk_usage', side_effect=[(100, 96, 4), (100, 96, 4), (100, 90, 10)],
        ), unittest.mock.patch.object(ft, 'Client', return_value=client):
            ft.enforce_disk_usage_limit(95)

        history = ft.load_removed_history(ft.removed_history_file)
        self.assertEqual(history["ubuntu-22.04-desktop-amd64.iso"]['reason'], 'disk_pressure')


if __name__ == "__main__":
    unittest.main()
