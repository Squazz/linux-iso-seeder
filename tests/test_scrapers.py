"""Contract tests for fetch_torrents' upstream scrapers, replaying real
pages captured into tests/fixtures/pages by scripts/record_fixtures.py.

The expected results below were read off the recorded pages by hand, not
produced by running the scrapers. When a re-recording changes a page, update
them to the new snapshot - after checking they still make sense.

No test here touches the network (helpers.block_network()).

Run with: python -m unittest discover -s tests
"""

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
KALI_SUFFIXES = (
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-amd64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-netinst-amd64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-everything-amd64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-arm64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-netinst-arm64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-purple-amd64.iso",
    "kali.download/arm-images/kali-{v}/kali-linux-{v}-raspberry-pi-armhf.img.xz",
    "kali.download/arm-images/kali-{v}/kali-linux-{v}-raspberry-pi-zero-2-w-armhf.img.xz",
    "kali.download/arm-images/kali-{v}/kali-linux-{v}-raspberry-pi-zero-w-armel.img.xz",
    "kali.download/cloud-images/kali-{v}/kali-linux-{v}-cloud-genericcloud-amd64.tar.xz",
    "kali.download/cloud-images/kali-{v}/kali-linux-{v}-cloud-genericcloud-arm64.tar.xz",
)
FEDORA = "https://torrent.fedoraproject.org/torrents/"
DEBIAN = "https://cdimage.debian.org/debian-cd/current/"


def kali_candidates(version):
    return {
        os.path.basename(suffix.format(v=version)): (
            "https://" + suffix.format(v=version) + ".torrent"
        )
        for suffix in KALI_SUFFIXES
    }


class ScraperTestCase(unittest.TestCase):
    def fetch(self, fetcher, overrides=None):
        """Runs fetcher against the recorded pages; returns (result, logs)."""
        pages = helpers.RecordedPages(overrides)
        with (
            unittest.mock.patch.object(ft.requests, "get", pages.get),
            self.assertLogs(ft.logger, level="DEBUG") as logs,
        ):
            ft.logger.debug("fetch start")  # assertLogs needs at least one
            result = fetcher()
        self.assertEqual(pages.unexpected, [])
        self.pages = pages
        return result, [r.getMessage() for r in logs.records[1:]]


class RecordedSnapshotTests(ScraperTestCase):
    """Each fetcher, replayed against its captured pages, must produce
    exactly the candidates the snapshot lists."""

    def test_ubuntu_lists_every_supported_lts_newest_first(self):
        result, _logs = self.fetch(ft.fetch_ubuntu_lts)

        expected = {}
        for codename, version in UBUNTU_SUPPORTED:
            for template in UBUNTU_TEMPLATES:
                url = template.format(c=codename, v=version)
                expected[os.path.basename(url)[: -len(".torrent")]] = url
        self.assertEqual(result, expected)
        self.assertEqual(list(result), list(expected))

    def test_debian_takes_the_first_torrent_of_each_listing(self):
        result, logs = self.fetch(ft.fetch_debian_stable)

        self.assertEqual(
            result,
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
        self.assertEqual(logs, [])

    def test_kali_latest_uses_the_newest_installer_version(self):
        result, _logs = self.fetch(ft.fetch_kali_latest)

        self.assertEqual(result, kali_candidates("2026.2"))
        self.assertEqual(self.pages.requested, ["https://www.kali.org/get-kali/"])

    def test_kali_old_versions_lists_every_folder_but_the_newest(self):
        result, _logs = self.fetch(ft.fetch_kali_old_versions)

        self.assertEqual(result, kali_candidates("2026.1"))

    def test_arch_takes_the_newest_available_release(self):
        result, _logs = self.fetch(ft.fetch_arch_latest)

        self.assertEqual(
            result,
            {
                "archlinux-2026.10.01": (
                    "https://archlinux.org/releng/releases/2026.10.01/torrent/"
                )
            },
        )

    def test_devuan_takes_the_linked_release_torrent(self):
        result, _logs = self.fetch(ft.fetch_devuan_latest)

        self.assertEqual(
            result,
            {"devuan_excalibur": "https://files.devuan.org/devuan_excalibur.torrent"},
        )

    def test_mint_reads_the_version_from_the_title(self):
        result, _logs = self.fetch(ft.fetch_linuxmint_cinnamon)

        self.assertEqual(
            result,
            {
                "linuxmint-22.3-cinnamon-64bit.iso": (
                    "https://www.linuxmint.com/torrents/"
                    "linuxmint-22.3-cinnamon-64bit.iso.torrent"
                )
            },
        )

    def test_fedora_takes_the_newest_final_release_per_arch(self):
        # 45_Beta is listed too, but isn't a final release.
        result, _logs = self.fetch(ft.fetch_fedora_workstation)

        self.assertEqual(
            result,
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
        result, _logs = self.fetch(ft.fetch_fedora_workstation_old_versions)

        self.assertEqual(
            result,
            {
                "Fedora-Workstation-Live-aarch64-43": (
                    FEDORA + "Fedora-Workstation-Live-aarch64-43.torrent"
                ),
                "Fedora-Workstation-Live-x86_64-43": (
                    FEDORA + "Fedora-Workstation-Live-x86_64-43.torrent"
                ),
            },
        )


# (fetcher, the URL it reads, the error it logs, what it returns on failure)
LATEST_FETCHERS = (
    (
        ft.fetch_ubuntu_lts,
        "https://changelogs.ubuntu.com/meta-release-lts",
        "Ubuntu fetch error",
        False,
    ),
    (ft.fetch_kali_latest, "https://www.kali.org/get-kali/", "Kali fetch error", False),
    (
        ft.fetch_kali_old_versions,
        "https://cdimage.kali.org/",
        "Kali old-release fetch error",
        {},
    ),
    (
        ft.fetch_arch_latest,
        "https://archlinux.org/releng/releases/",
        "Arch Linux fetch error",
        False,
    ),
    (
        ft.fetch_devuan_latest,
        "https://www.devuan.org/get-devuan",
        "Devuan fetch error",
        False,
    ),
    (
        ft.fetch_linuxmint_cinnamon,
        "https://www.linuxmint.com/download.php",
        "Linux Mint fetch error",
        False,
    ),
    (ft.fetch_fedora_workstation, FEDORA, "Fedora fetch error", False),
    (
        ft.fetch_fedora_workstation_old_versions,
        FEDORA,
        "Fedora old-release fetch error",
        {},
    ),
)


class FailurePathTests(ScraperTestCase):
    """An unreachable or erroring upstream must make a fetcher log what went
    wrong and return its empty result - never raise into the daily run, and
    never pass an error page off as "no releases"."""

    def _assert_fails_with(self, overrides, expected_in_log):
        for fetcher, url, error, empty in LATEST_FETCHERS:
            with self.subTest(fetcher=fetcher.__name__):
                result, logs = self.fetch(fetcher, {url: overrides(url)})

                self.assertIs(type(result), type(empty))
                self.assertEqual(result, empty)
                self.assertTrue(
                    any(m.startswith(error) and expected_in_log in m for m in logs),
                    logs,
                )

    def test_connection_error(self):
        self._assert_fails_with(
            lambda url: requests.ConnectionError("connection refused"),
            "connection refused",
        )

    def test_http_500(self):
        self._assert_fails_with(
            lambda url: helpers.fake_response("oops", status=500, url=url),
            "500 Server Error",
        )

    def test_http_404(self):
        self._assert_fails_with(
            lambda url: helpers.fake_response("gone", status=404, url=url),
            "404 Client Error",
        )

    def test_debian_logs_each_failing_listing_and_keeps_the_rest(self):
        amd64_dvd = DEBIAN + "amd64/bt-dvd/"
        arm64_cd = DEBIAN + "arm64/bt-cd/"

        result, logs = self.fetch(
            ft.fetch_debian_stable,
            {
                amd64_dvd: requests.ConnectionError("refused"),
                arm64_cd: helpers.fake_response("oops", status=500, url=arm64_cd),
            },
        )

        self.assertEqual(
            sorted(result),
            ["debian-13.7.0-amd64-netinst.iso", "debian-13.7.0-arm64-DVD-1.iso"],
        )
        self.assertEqual([m.split(":")[0] for m in logs], ["Debian fetch error"] * 2)
        self.assertIn("refused", logs[0])
        self.assertIn("500 Server Error", logs[1])


class LayoutChangeTests(ScraperTestCase):
    """A page that loads fine but no longer has the element a scraper looks
    for must give an empty result and a warning, not an exception."""

    def _page(self, url, body):
        return {url: helpers.fake_response(body, url=url)}

    def test_kali_page_without_a_version(self):
        url = "https://www.kali.org/get-kali/"

        result, logs = self.fetch(
            ft.fetch_kali_latest, self._page(url, "<html>Get Kali</html>")
        )

        self.assertIs(result, False)
        self.assertEqual(
            logs,
            [f"Could not detect a Kali release number on {url}#kali-installer-images"],
        )

    def test_kali_cdimage_with_a_single_version_has_no_old_ones(self):
        result, logs = self.fetch(
            ft.fetch_kali_old_versions,
            self._page("https://cdimage.kali.org/", '<a href="kali-2026.2/">x</a>'),
        )

        self.assertEqual((result, logs), ({}, []))

    def test_ubuntu_block_without_a_version_line(self):
        result, logs = self.fetch(
            ft.fetch_ubuntu_lts,
            self._page(
                "https://changelogs.ubuntu.com/meta-release-lts",
                "Dist: noble\nSupported: 1\n",
            ),
        )

        self.assertIs(result, False)
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].startswith("Ubuntu fetch error"))

    def test_debian_listing_without_torrents(self):
        overrides = {}
        for listing in (
            "amd64/bt-dvd/",
            "arm64/bt-dvd/",
            "amd64/bt-cd/",
            "arm64/bt-cd/",
        ):
            overrides.update(self._page(DEBIAN + listing, "<a href='x.iso'>x</a>"))

        result, logs = self.fetch(ft.fetch_debian_stable, overrides)

        self.assertEqual(result, {})
        self.assertEqual(logs, ["No Debian DVD-1 torrent found."] * 4)

    def test_arch_page_without_the_release_table(self):
        result, logs = self.fetch(
            ft.fetch_arch_latest,
            self._page("https://archlinux.org/releng/releases/", "<html></html>"),
        )

        self.assertIs(result, False)
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].startswith("Arch Linux fetch error"))

    def test_arch_table_without_available_releases(self):
        url = "https://archlinux.org/releng/releases/"
        result, logs = self.fetch(
            ft.fetch_arch_latest,
            self._page(
                url,
                "<table id='release-table'><tr><td class='available-no'></td>"
                "<td><a href='/releng/releases/2026.10.01/torrent/'>t</a></td>"
                "</tr></table>",
            ),
        )

        self.assertIs(result, False)
        self.assertEqual(logs, [f"No available Arch Linux releases found on {url}"])

    def test_devuan_page_without_a_torrent_link(self):
        url = "https://www.devuan.org/get-devuan"

        result, logs = self.fetch(ft.fetch_devuan_latest, self._page(url, "<html/>"))

        self.assertIs(result, False)
        self.assertEqual(
            logs, [f"Could not find a Devuan release torrent link on {url}"]
        )

    def test_mint_page_without_a_versioned_title(self):
        url = "https://www.linuxmint.com/download.php"

        result, logs = self.fetch(
            ft.fetch_linuxmint_cinnamon, self._page(url, "<title>Linux Mint</title>")
        )

        self.assertIs(result, False)
        self.assertEqual(logs, [f"Could not detect a Linux Mint version on {url}"])

    def test_fedora_listing_without_workstation_torrents(self):
        result, logs = self.fetch(
            ft.fetch_fedora_workstation,
            self._page(FEDORA, "<a href='Fedora-Server-44.torrent'>x</a>"),
        )

        self.assertIs(result, False)
        self.assertEqual(logs, [f"No Fedora Workstation torrents found on {FEDORA}"])


class NetworkGuardTests(unittest.TestCase):
    def test_real_connections_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, "must not open network"):
            requests.get("http://192.0.2.1/", timeout=1)


if __name__ == "__main__":
    unittest.main()
