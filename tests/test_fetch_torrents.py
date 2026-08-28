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
    """Covers the real-world names from tasks/01-cleanup-old-versions-regex-bug.md
    that the old `(\\d+\\.\\d+)\\.iso` regex could never match."""

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


if __name__ == "__main__":
    unittest.main()
