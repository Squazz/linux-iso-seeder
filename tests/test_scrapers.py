"""Contract tests for fetch_torrents' upstream scrapers, replaying real
pages captured into tests/fixtures/pages by scripts/record_fixtures.py.

The expected results below were read off the recorded pages by hand, not
produced by running the scrapers. When a re-recording changes a page, update
them to the new snapshot - after checking they still make sense.

No test here touches the network (helpers.block_network()).

Run with: python -m unittest discover -s tests
"""

import dataclasses
import logging
import os
import unittest
import unittest.mock

import helpers
import requests

import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


UBUNTU_SUPPORTED = (  # newest first, as fetch_ubuntu_lts() orders them
    ("resolute", "26.04.1"),
    ("noble", "24.04.5"),
    ("jammy", "22.04.5"),
    ("focal", "20.04.6"),
    ("bionic", "18.04.6"),
    ("xenial", "16.04.7"),
    ("trusty", "14.04.6"),
)
UBUNTU_TEMPLATES = (
    "https://releases.ubuntu.com/{c}/ubuntu-{v}-desktop-amd64.iso.torrent",
    "https://releases.ubuntu.com/{c}/ubuntu-{v}-live-server-amd64.iso.torrent",
    "https://cdimage.ubuntu.com/lubuntu/releases/{c}/release/lubuntu-{v}-desktop-amd64.iso.torrent",
    "https://torrent.ubuntu.com/xubuntu/releases/{c}/release/desktop/xubuntu-{v}-desktop-amd64.iso.torrent",
    "https://torrent.ubuntu.com/xubuntu/releases/{c}/release/minimal/xubuntu-{v}-minimal-amd64.iso.torrent",
)
FEDORA = "https://torrent.fedoraproject.org/torrents/"
DEBIAN = "https://cdimage.debian.org/debian-cd/current/"


class _RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@dataclasses.dataclass
class Fetched:
    """One fetcher run: what it returned, every message it logged (any
    level, in order), the ERROR ones on their own, and the URLs it asked
    for."""

    result: object
    logs: list
    errors: list
    requested: list


class ScraperTestCase(unittest.TestCase):
    def fetch(self, fetcher, overrides=None):
        """Runs fetcher against the recorded pages, plus overrides."""
        pages = helpers.RecordedPages(overrides)
        handler = _RecordingHandler()
        level, propagate = ft.logger.level, ft.logger.propagate
        ft.logger.addHandler(handler)
        ft.logger.setLevel(logging.DEBUG)
        ft.logger.propagate = False
        try:
            with unittest.mock.patch.object(ft.requests, "get", pages.get):
                result = fetcher()
        finally:
            ft.logger.removeHandler(handler)
            ft.logger.setLevel(level)
            ft.logger.propagate = propagate
        self.assertEqual(pages.unexpected, [])
        return Fetched(
            result=result,
            logs=[r.getMessage() for r in handler.records],
            errors=[
                r.getMessage() for r in handler.records if r.levelno >= logging.ERROR
            ],
            requested=pages.requested,
        )


class RecordedSnapshotTests(ScraperTestCase):
    """Each fetcher, replayed against its captured pages, must produce
    exactly the candidates the snapshot lists."""

    def test_ubuntu_lists_every_supported_lts_newest_first(self):
        fetched = self.fetch(ft.fetch_ubuntu_lts)

        expected = {}
        for codename, version in UBUNTU_SUPPORTED:
            for template in UBUNTU_TEMPLATES:
                url = template.format(c=codename, v=version)
                expected[os.path.basename(url)[: -len(".torrent")]] = url
        self.assertEqual(fetched.result, expected)
        self.assertEqual(list(fetched.result), list(expected))

    def test_debian_takes_the_first_torrent_of_each_listing(self):
        fetched = self.fetch(ft.fetch_debian_stable)

        self.assertEqual(
            fetched.result,
            {
                "debian-13.7.0-amd64-DVD-1.iso": DEBIAN
                + "amd64/bt-dvd/debian-13.7.0-amd64-DVD-1.iso.torrent",
                "debian-13.7.0-arm64-DVD-1.iso": DEBIAN
                + "arm64/bt-dvd/debian-13.7.0-arm64-DVD-1.iso.torrent",
                "debian-13.7.0-amd64-netinst.iso": DEBIAN
                + "amd64/bt-cd/debian-13.7.0-amd64-netinst.iso.torrent",
                "debian-13.7.0-arm64-netinst.iso": DEBIAN
                + "arm64/bt-cd/debian-13.7.0-arm64-netinst.iso.torrent",
            },
        )
        self.assertEqual(fetched.logs, [])

    def test_kali_latest_uses_the_newest_installer_version(self):
        fetched = self.fetch(ft.fetch_kali_latest)

        self.assertEqual(fetched.result, helpers.kali_candidates("2026.2"))
        self.assertEqual(fetched.requested, ["https://www.kali.org/get-kali/"])

    def test_kali_old_versions_lists_every_folder_but_the_newest(self):
        fetched = self.fetch(ft.fetch_kali_old_versions)

        self.assertEqual(fetched.result, helpers.kali_candidates("2026.1"))

    def test_arch_takes_the_newest_available_release(self):
        fetched = self.fetch(ft.fetch_arch_latest)

        self.assertEqual(
            fetched.result,
            {
                "archlinux-2026.10.01": (
                    "https://archlinux.org/releng/releases/2026.10.01/torrent/"
                )
            },
        )

    def test_devuan_takes_the_linked_release_torrent(self):
        fetched = self.fetch(ft.fetch_devuan_latest)

        self.assertEqual(
            fetched.result,
            {"devuan_excalibur": "https://files.devuan.org/devuan_excalibur.torrent"},
        )

    def test_mint_reads_the_version_from_the_title(self):
        fetched = self.fetch(ft.fetch_linuxmint_cinnamon)

        self.assertEqual(
            fetched.result,
            {
                "linuxmint-22.3-cinnamon-64bit.iso": (
                    "https://www.linuxmint.com/torrents/"
                    "linuxmint-22.3-cinnamon-64bit.iso.torrent"
                )
            },
        )

    def test_fedora_takes_the_newest_final_release_per_arch(self):
        # 45_Beta is listed too, but isn't a final release.
        fetched = self.fetch(ft.fetch_fedora_workstation)

        self.assertEqual(
            fetched.result,
            {
                "Fedora-Workstation-Live-aarch64-44": (
                    FEDORA + "Fedora-Workstation-Live-aarch64-44.torrent"
                ),
                "Fedora-Workstation-Live-x86_64-44": (
                    FEDORA + "Fedora-Workstation-Live-x86_64-44.torrent"
                ),
            },
        )

    def test_fedora_old_versions_lists_the_older_final_releases(self):
        fetched = self.fetch(ft.fetch_fedora_workstation_old_versions)

        self.assertEqual(
            fetched.result,
            {
                "Fedora-Workstation-Live-aarch64-43": (
                    FEDORA + "Fedora-Workstation-Live-aarch64-43.torrent"
                ),
                "Fedora-Workstation-Live-x86_64-43": (
                    FEDORA + "Fedora-Workstation-Live-x86_64-43.torrent"
                ),
            },
        )


# Every fetcher that reads a single page (Debian reads four; see
# test_debian_logs_each_failing_listing_and_keeps_the_rest), with that
# page's URL and what the fetcher returns when it fails.
SINGLE_PAGE_FETCHERS = (
    (ft.fetch_ubuntu_lts, "https://changelogs.ubuntu.com/meta-release-lts", False),
    (ft.fetch_kali_latest, "https://www.kali.org/get-kali/", False),
    (ft.fetch_kali_old_versions, "https://cdimage.kali.org/", {}),
    (ft.fetch_arch_latest, "https://archlinux.org/releng/releases/", False),
    (ft.fetch_devuan_latest, "https://www.devuan.org/get-devuan", False),
    (ft.fetch_linuxmint_cinnamon, "https://www.linuxmint.com/download.php", False),
    (ft.fetch_fedora_workstation, FEDORA, False),
    (ft.fetch_fedora_workstation_old_versions, FEDORA, {}),
)


class FailurePathTests(ScraperTestCase):
    """An unreachable or erroring upstream must make a fetcher log what went
    wrong and return its empty result - never raise into the daily run, and
    never pass an error page off as "no releases"."""

    def _assert_fails_with(self, overrides, cause):
        for fetcher, url, empty in SINGLE_PAGE_FETCHERS:
            with self.subTest(fetcher=fetcher.__name__):
                fetched = self.fetch(fetcher, {url: overrides(url)})

                self.assertIs(type(fetched.result), type(empty))
                self.assertEqual(fetched.result, empty)
                self.assertEqual(len(fetched.errors), 1, fetched.logs)
                self.assertIn(cause, fetched.errors[0])

    def test_connection_error(self):
        self._assert_fails_with(
            lambda url: requests.ConnectionError("connection refused"),
            "connection refused",
        )

    def test_http_error_status(self):
        for status, cause in ((500, "500 Server Error"), (404, "404 Client Error")):
            with self.subTest(status=status):
                self._assert_fails_with(
                    lambda url, status=status: helpers.fake_response(
                        "oops", status=status, url=url
                    ),
                    cause,
                )

    def test_debian_logs_each_failing_listing_and_keeps_the_rest(self):
        amd64_dvd = DEBIAN + "amd64/bt-dvd/"
        arm64_cd = DEBIAN + "arm64/bt-cd/"

        fetched = self.fetch(
            ft.fetch_debian_stable,
            {
                amd64_dvd: requests.ConnectionError("refused"),
                arm64_cd: helpers.fake_response("oops", status=500, url=arm64_cd),
            },
        )

        self.assertEqual(
            sorted(fetched.result),
            ["debian-13.7.0-amd64-netinst.iso", "debian-13.7.0-arm64-DVD-1.iso"],
        )
        self.assertEqual(len(fetched.errors), 2, fetched.logs)
        self.assertIn("refused", fetched.errors[0])
        self.assertIn("500 Server Error", fetched.errors[1])


class LayoutChangeTests(ScraperTestCase):
    """A page that loads fine but no longer has the element a scraper looks
    for must give an empty result and a warning, not an exception."""

    def _page(self, url, body):
        return {url: helpers.fake_response(body, url=url)}

    def test_kali_page_without_a_version(self):
        url = "https://www.kali.org/get-kali/"

        fetched = self.fetch(
            ft.fetch_kali_latest, self._page(url, "<html>Get Kali</html>")
        )

        self.assertIs(fetched.result, False)
        self.assertEqual(
            fetched.logs,
            [f"Could not detect a Kali release number on {url}#kali-installer-images"],
        )

    def test_kali_cdimage_with_a_single_version_has_no_old_ones(self):
        fetched = self.fetch(
            ft.fetch_kali_old_versions,
            self._page("https://cdimage.kali.org/", '<a href="kali-2026.2/">x</a>'),
        )

        self.assertEqual((fetched.result, fetched.logs), ({}, []))

    def test_ubuntu_block_without_a_version_line(self):
        fetched = self.fetch(
            ft.fetch_ubuntu_lts,
            self._page(
                "https://changelogs.ubuntu.com/meta-release-lts",
                "Dist: noble\nSupported: 1\n",
            ),
        )

        self.assertIs(fetched.result, False)
        self.assertEqual(len(fetched.logs), 1)
        self.assertRegex(fetched.logs[0], r"^Ubuntu fetch error: ")

    def test_debian_listing_without_torrents(self):
        overrides = {}
        for listing in (
            "amd64/bt-dvd/",
            "arm64/bt-dvd/",
            "amd64/bt-cd/",
            "arm64/bt-cd/",
        ):
            overrides.update(self._page(DEBIAN + listing, "<a href='x.iso'>x</a>"))

        fetched = self.fetch(ft.fetch_debian_stable, overrides)

        self.assertEqual(fetched.result, {})
        self.assertEqual(fetched.logs, ["No Debian DVD-1 torrent found."] * 4)

    def test_arch_page_without_the_release_table(self):
        fetched = self.fetch(
            ft.fetch_arch_latest,
            self._page("https://archlinux.org/releng/releases/", "<html></html>"),
        )

        self.assertIs(fetched.result, False)
        self.assertEqual(len(fetched.logs), 1)
        self.assertRegex(fetched.logs[0], r"^Arch Linux fetch error: ")

    def test_arch_table_without_available_releases(self):
        url = "https://archlinux.org/releng/releases/"
        fetched = self.fetch(
            ft.fetch_arch_latest,
            self._page(
                url,
                "<table id='release-table'><tr><td class='available-no'></td>"
                "<td><a href='/releng/releases/2026.10.01/torrent/'>t</a></td>"
                "</tr></table>",
            ),
        )

        self.assertIs(fetched.result, False)
        self.assertEqual(
            fetched.logs, [f"No available Arch Linux releases found on {url}"]
        )

    def test_devuan_page_without_a_torrent_link(self):
        url = "https://www.devuan.org/get-devuan"

        fetched = self.fetch(ft.fetch_devuan_latest, self._page(url, "<html/>"))

        self.assertIs(fetched.result, False)
        self.assertEqual(
            fetched.logs, [f"Could not find a Devuan release torrent link on {url}"]
        )

    def test_mint_page_without_a_versioned_title(self):
        url = "https://www.linuxmint.com/download.php"

        fetched = self.fetch(
            ft.fetch_linuxmint_cinnamon, self._page(url, "<title>Linux Mint</title>")
        )

        self.assertIs(fetched.result, False)
        self.assertEqual(
            fetched.logs, [f"Could not detect a Linux Mint version on {url}"]
        )

    def test_fedora_listing_without_workstation_torrents(self):
        fetched = self.fetch(
            ft.fetch_fedora_workstation,
            self._page(FEDORA, "<a href='Fedora-Server-44.torrent'>x</a>"),
        )

        self.assertIs(fetched.result, False)
        self.assertEqual(
            fetched.logs, [f"No Fedora Workstation torrents found on {FEDORA}"]
        )


if __name__ == "__main__":
    unittest.main()
