"""Tests for the pure part of scripts/live_check.py (the weekly drift job):
deciding whether a live fetcher's candidate looks like a real release.

Run with: python -m unittest discover -s tests
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

import helpers
import live_check


def setUpModule():
    unittest.addModuleCleanup(helpers.block_network())


class ProblemsTests(unittest.TestCase):
    def test_well_formed_candidates_have_no_problems(self):
        cases = (
            (
                "ubuntu",
                "xubuntu-24.04.5-minimal-amd64.iso",
                (
                    "https://torrent.ubuntu.com/xubuntu/releases/noble/release/minimal/"
                    "xubuntu-24.04.5-minimal-amd64.iso.torrent"
                ),
            ),
            (
                "debian",
                "debian-13.7.0-amd64-DVD-1.iso",
                (
                    "https://cdimage.debian.org/debian-cd/current/amd64/bt-dvd/"
                    "debian-13.7.0-amd64-DVD-1.iso.torrent"
                ),
            ),
            (
                "kali",
                "kali-linux-2026.2-installer-amd64.iso",
                (
                    "https://cdimage.kali.org/kali-2026.2/"
                    "kali-linux-2026.2-installer-amd64.iso.torrent"
                ),
            ),
            (
                "arch",
                "archlinux-2026.10.01",
                "https://archlinux.org/releng/releases/2026.10.01/torrent/",
            ),
            (
                "devuan",
                "devuan_excalibur",
                "https://files.devuan.org/devuan_excalibur.torrent",
            ),
            (
                "mint",
                "linuxmint-22.3-cinnamon-64bit.iso",
                (
                    "https://www.linuxmint.com/torrents/"
                    "linuxmint-22.3-cinnamon-64bit.iso.torrent"
                ),
            ),
            (
                "fedora",
                "Fedora-Workstation-Live-x86_64-44",
                (
                    "https://torrent.fedoraproject.org/torrents/"
                    "Fedora-Workstation-Live-x86_64-44.torrent"
                ),
            ),
        )
        for distro, name, url in cases:
            with self.subTest(distro=distro):
                self.assertEqual(live_check.problems(distro, name, url), [])

    def test_name_from_another_distro(self):
        self.assertEqual(
            live_check.problems(
                "debian", "ubuntu-24.04.5-desktop-amd64.iso", "https://x/a.torrent"
            ),
            [
                "name 'ubuntu-24.04.5-desktop-amd64.iso' doesn't look like a debian release"
            ],
        )

    def test_url_must_be_https_and_a_torrent(self):
        self.assertEqual(
            live_check.problems(
                "devuan", "devuan_excalibur", "http://files.devuan.org/devuan.iso"
            ),
            [
                "URL 'http://files.devuan.org/devuan.iso' is not https",
                "URL 'http://files.devuan.org/devuan.iso' is not a .torrent",
            ],
        )

    def test_only_arch_may_use_a_torrent_path(self):
        url = "https://cdimage.debian.org/debian-13.7.0-amd64-DVD-1/torrent/"

        self.assertEqual(
            live_check.problems("debian", "debian-13.7.0-amd64-DVD-1.iso", url),
            [f"URL {url!r} is not a .torrent"],
        )

    def test_name_without_a_parseable_version(self):
        self.assertEqual(
            live_check.problems(
                "mint", "linuxmint-latest-cinnamon", "https://x/linuxmint.torrent"
            ),
            ["name 'linuxmint-latest-cinnamon' has no parseable version"],
        )

    def test_old_release_fetchers_are_checked_as_their_distro(self):
        self.assertEqual(live_check.distro_of("kali-old"), "kali")
        self.assertEqual(live_check.distro_of("fedora-old"), "fedora")
        self.assertEqual(live_check.distro_of("mint"), "mint")


if __name__ == "__main__":
    unittest.main()
