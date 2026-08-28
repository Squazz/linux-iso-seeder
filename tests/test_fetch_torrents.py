"""Tests for fetch_torrents.py, focused on the cleanup_old_versions() logic.

fetch_torrents.py is written to run inside the container: it imports
transmission_rpc (an apk-only package not available via pip) and opens log
files under /logs at import time. To make the module importable in a plain
test environment, this file stubs transmission_rpc and points
FETCH_TORRENTS_LOG_DIR at a temp directory before importing it.

Run with: python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import types
import unittest
import unittest.mock
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
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(
            names_of(to_remove),
            [
                "archlinux-2024.04.01-x86_64.iso",
                "debian-12.4.0-amd64-DVD-1.iso",
                "kali-linux-2023.4-installer-amd64.iso",
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


if __name__ == "__main__":
    unittest.main()
