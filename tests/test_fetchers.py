"""Tests for choosing and downloading releases: each fetch_* scraper's
candidate naming (hand-written pages; tests/test_scrapers.py replays
recorded ones), FETCH_TORRENTS_DISTROS, the low-demand filter and
download_torrent().

Run with: python -m unittest discover -s tests
"""

import os
import unittest
import unittest.mock

import helpers

import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


# Written out rather than read from ft.DEFAULT_DISTROS/ft.ALL_DISTROS, so a
# change to either has to be made here on purpose.
DEFAULT_DISTROS = ["ubuntu", "debian", "kali", "mint", "fedora"]
ALL_DISTROS_TEXT = "ubuntu, debian, kali, arch, mint, fedora, devuan"


class FetchUbuntuLtsNamingTests(unittest.TestCase):
    """The names fetch_ubuntu_lts() uses as dict keys are also what gets
    passed to should_fetch_torrent() before download, so they must match the
    shape of the names Transmission later reports for those same torrents
    (real arch suffix + .iso extension) — see
    tasks/02-ratio-key-mismatch-ubuntu-debian.md."""

    def test_candidate_names_include_arch_and_iso_suffix(self):
        meta_release = "Dist: noble\nVersion: 24.04\nSupported: 1\n"

        response = helpers.fake_response(meta_release)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            results = ft.fetch_ubuntu_lts()

        self.assertEqual(
            results,
            {
                "ubuntu-24.04-desktop-amd64.iso": (
                    "https://releases.ubuntu.com/noble/ubuntu-24.04-desktop-amd64.iso.torrent"
                ),
                "ubuntu-24.04-live-server-amd64.iso": (
                    "https://releases.ubuntu.com/noble/"
                    "ubuntu-24.04-live-server-amd64.iso.torrent"
                ),
                "lubuntu-24.04-desktop-amd64.iso": (
                    "https://cdimage.ubuntu.com/lubuntu/releases/noble/release/"
                    "lubuntu-24.04-desktop-amd64.iso.torrent"
                ),
                "xubuntu-24.04-desktop-amd64.iso": (
                    "https://torrent.ubuntu.com/xubuntu/releases/noble/release/desktop/"
                    "xubuntu-24.04-desktop-amd64.iso.torrent"
                ),
                "xubuntu-24.04-minimal-amd64.iso": (
                    "https://torrent.ubuntu.com/xubuntu/releases/noble/release/minimal/"
                    "xubuntu-24.04-minimal-amd64.iso.torrent"
                ),
            },
        )


class FetchDebianStableNamingTests(unittest.TestCase):
    """Mirrors FetchUbuntuLtsNamingTests for Debian: the dict key must keep
    the .iso extension so it matches Transmission's reported torrent name."""

    def test_candidate_name_keeps_iso_suffix(self):
        html = '<html><body><a href="debian-12.5.0-amd64-DVD-1.iso.torrent">link</a></body></html>'

        response = helpers.fake_response(html)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            results = ft.fetch_debian_stable()

        self.assertIn("debian-12.5.0-amd64-DVD-1.iso", results)


class FetchLinuxMintCinnamonNamingTests(unittest.TestCase):
    """The dict key fetch_linuxmint_cinnamon() uses must match the 'name'
    field embedded in the actual .torrent file (verified against a real
    download from linuxmint.com: linuxmint-22.3-cinnamon-64bit.iso), so it
    lines up with what Transmission later reports as torrent.name."""

    def test_candidate_name_matches_torrent_internal_name(self):
        html = "<title>Download Linux Mint 22.3 - Linux Mint</title>"

        response = helpers.fake_response(html)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
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

        response = helpers.fake_response(html)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            results = ft.fetch_fedora_workstation()

        self.assertEqual(
            results,
            {
                "Fedora-Workstation-Live-x86_64-44": "https://torrent.fedoraproject.org/torrents/Fedora-Workstation-Live-x86_64-44.torrent",
                "Fedora-Workstation-Live-aarch64-44": "https://torrent.fedoraproject.org/torrents/Fedora-Workstation-Live-aarch64-44.torrent",
            },
        )


class FetchArchLatestNamingTests(unittest.TestCase):
    """archlinux.org/releng/releases/ lists every release still available
    (typically the last 2-3 months) as available-yes. fetch_arch_latest()
    must pick only the single newest one - fetching all of them fragments
    whatever little torrent demand Arch has across several near-duplicate
    monthly builds (see tasks/01-demand-checks-for-default-distros.md)."""

    def test_picks_only_the_single_newest_release(self):
        html = (
            "<html><body><table id='release-table'>"
            "<tr><td class='available-yes'></td><td><a href='/releng/releases/2026.07.01/torrent/'>t</a></td></tr>"
            "<tr><td class='available-yes'></td><td><a href='/releng/releases/2026.09.01/torrent/'>t</a></td></tr>"
            "<tr><td class='available-yes'></td><td><a href='/releng/releases/2026.08.01/torrent/'>t</a></td></tr>"
            "</table></body></html>"
        )

        response = helpers.fake_response(html)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            results = ft.fetch_arch_latest()

        self.assertEqual(
            results,
            {
                "archlinux-2026.09.01": "https://archlinux.org/releng/releases/2026.09.01/torrent/"
            },
        )


class FetchDevuanLatestNamingTests(unittest.TestCase):
    """Devuan's get-devuan page links a single release torrent whose
    filename embeds the current release codename (e.g.
    devuan_excalibur.torrent, verified against the real download) - the
    dict key must match that basename since it's also what Transmission
    later reports as torrent.name."""

    def test_extracts_current_release_torrent(self):
        html = (
            '<h2 id="torrent-and-magnet-link">Torrent and Magnet Link</h2><ul>'
            '<li><a href="https://files.devuan.org/devuan_excalibur.torrent">Release torrent</a></li>'
            "</ul>"
        )

        response = helpers.fake_response(html)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            results = ft.fetch_devuan_latest()

        self.assertEqual(
            results,
            {"devuan_excalibur": "https://files.devuan.org/devuan_excalibur.torrent"},
        )


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

        response = helpers.fake_response(html)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            results = ft.fetch_kali_old_versions()

        self.assertEqual(results, helpers.kali_candidates("2026.1"))


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

        response = helpers.fake_response(html)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            results = ft.fetch_fedora_workstation_old_versions()

        self.assertEqual(
            results,
            {
                "Fedora-Workstation-Live-x86_64-43": "https://torrent.fedoraproject.org/torrents/Fedora-Workstation-Live-x86_64-43.torrent",
                "Fedora-Workstation-Live-aarch64-43": "https://torrent.fedoraproject.org/torrents/Fedora-Workstation-Live-aarch64-43.torrent",
            },
        )

    def test_single_version_per_arch_returns_nothing(self):
        html = '<html><body><a href="Fedora-Workstation-Live-x86_64-44.torrent">a</a></body></html>'

        response = helpers.fake_response(html)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            results = ft.fetch_fedora_workstation_old_versions()

        self.assertEqual(results, {})


class ParseSupportedDistrosTests(unittest.TestCase):
    """Arch and Devuan are opt-in only: neither can be pre-verified for real
    demand (Arch publishes no tracker at all; Devuan bundles every edition
    into one multi-file torrent, so a demand reading only ever covers the
    whole bundle, never a specific file within it) - see
    tasks/01-demand-checks-for-default-distros.md. They must never be
    fetched just because FETCH_TORRENTS_DISTROS is unset."""

    def test_default_excludes_opt_in_distros(self):
        with helpers.isolated_env():
            result = ft.parse_supported_distros()
        self.assertEqual(result, DEFAULT_DISTROS)

    def test_explicit_opt_in_distros_are_honored(self):
        with unittest.mock.patch.dict(
            os.environ, {"FETCH_TORRENTS_DISTROS": "arch,devuan"}
        ):
            result = ft.parse_supported_distros()
        self.assertEqual(result, ["arch", "devuan"])

    def test_can_mix_default_and_opt_in_distros(self):
        with unittest.mock.patch.dict(
            os.environ, {"FETCH_TORRENTS_DISTROS": "ubuntu,arch"}
        ):
            result = ft.parse_supported_distros()
        self.assertEqual(result, ["ubuntu", "arch"])

    def test_unknown_entries_are_dropped_but_valid_ones_kept(self):
        with (
            unittest.mock.patch.dict(
                os.environ, {"FETCH_TORRENTS_DISTROS": "ubuntu,nonsense"}
            ),
            self.assertLogs(ft.logger, level="WARNING") as logs,
        ):
            result = ft.parse_supported_distros()
        self.assertEqual(result, ["ubuntu"])
        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                "FETCH_TORRENTS_DISTROS contains unknown distributions: nonsense. "
                "Valid values: " + ALL_DISTROS_TEXT
            ],
        )

    def test_all_invalid_falls_back_to_default_not_all_distros(self):
        with (
            unittest.mock.patch.dict(
                os.environ, {"FETCH_TORRENTS_DISTROS": "nonsense"}
            ),
            self.assertLogs(ft.logger, level="WARNING") as logs,
        ):
            result = ft.parse_supported_distros()
        self.assertEqual(result, DEFAULT_DISTROS)
        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                (
                    "FETCH_TORRENTS_DISTROS contains unknown distributions: "
                    "nonsense. Valid values: " + ALL_DISTROS_TEXT
                ),
                (
                    "FETCH_TORRENTS_DISTROS did not specify any valid distros. "
                    "Falling back to defaults: ubuntu, debian, kali, mint, fedora"
                ),
            ],
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
        self.tmp_watch_dir = helpers.use_watch_dir(self)

    def test_404_response_is_not_found_not_failed(self):
        response = helpers.fake_response(status=404)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            status = ft.download_torrent(
                "ubuntu-14.04.6-live-server-amd64.iso",
                "https://example.invalid/x.torrent",
            )

        self.assertEqual(status, "not_found")
        dest = os.path.join(
            self.tmp_watch_dir, "ubuntu-14.04.6-live-server-amd64.iso.torrent"
        )
        self.assertFalse(os.path.exists(dest))

    def test_other_http_error_is_still_failed(self):
        response = helpers.fake_response(status=500)

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            status = ft.download_torrent(
                "ubuntu-24.04-desktop-amd64.iso", "https://example.invalid/x.torrent"
            )

        self.assertEqual(status, "failed")

    def test_successful_download_is_still_added(self):
        response = helpers.fake_response(b"fake torrent bytes")

        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            status = ft.download_torrent(
                "ubuntu-24.04-desktop-amd64.iso", "https://example.invalid/x.torrent"
            )

        self.assertEqual(status, "added")
        dest = os.path.join(
            self.tmp_watch_dir, "ubuntu-24.04-desktop-amd64.iso.torrent"
        )
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"fake torrent bytes")


class DownloadTorrentAtomicWriteTests(unittest.TestCase):
    """transmission-daemon watches *.torrent, and download_torrent() treats
    an existing <name>.torrent as already fetched - so a write that dies
    part-way must never leave a partial file under that name."""

    NAME = "ubuntu-24.04-desktop-amd64.iso"

    def setUp(self):
        self.tmp_watch_dir = helpers.use_watch_dir(self)

    def _download(self):
        response = helpers.fake_response(b"d8:announce3:urle" * 64)
        with unittest.mock.patch.object(ft.requests, "get", return_value=response):
            return ft.download_torrent(self.NAME, "https://example.invalid/x.torrent")

    def test_write_failing_part_way_leaves_no_file_behind(self):
        with helpers.disk_full_open(ft):
            status = self._download()

        self.assertEqual(status, "failed")
        self.assertEqual(os.listdir(self.tmp_watch_dir), [])

    def test_next_run_downloads_again_after_a_failed_write(self):
        with helpers.disk_full_open(ft):
            self._download()

        status = self._download()

        self.assertEqual(status, "added")
        dest = os.path.join(self.tmp_watch_dir, f"{self.NAME}.torrent")
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"d8:announce3:urle" * 64)
        self.assertEqual(os.listdir(self.tmp_watch_dir), [f"{self.NAME}.torrent"])

    def test_partial_file_is_never_named_like_a_torrent(self):
        # Whatever exists mid-write must not match transmission's *.torrent
        # watch glob.
        seen = []
        real_replace = os.replace

        def spy_replace(src, dst):
            seen.extend(os.listdir(self.tmp_watch_dir))
            real_replace(src, dst)

        with unittest.mock.patch.object(ft.os, "replace", spy_replace):
            self.assertEqual(self._download(), "added")

        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].endswith(".torrent"), seen[0])


class SafeWatchPathTests(unittest.TestCase):
    """_safe_watch_path() is the shared guard download_torrent(),
    _remove_watch_file(), and check_old_releases_for_demand() all rely on to
    keep a torrent name confined to a single file directly under watch_dir -
    defense in depth against a future fetch_*() parser turning scraped
    upstream content into a path escape."""

    def setUp(self):
        self.watch_dir = helpers.use_watch_dir(self)

    def test_normal_name_resolves_under_watch_dir(self):
        self.assertEqual(
            ft._safe_watch_path("ubuntu-24.04-desktop-amd64.iso"),
            os.path.join(self.watch_dir, "ubuntu-24.04-desktop-amd64.iso.torrent"),
        )

    def test_rejects_path_separators(self):
        self.assertIsNone(ft._safe_watch_path("archlinux-../../../etc/cron.d/evil"))
        self.assertIsNone(ft._safe_watch_path("foo/bar"))
        self.assertIsNone(ft._safe_watch_path("foo\\bar"))

    def test_rejects_empty_or_dot_names(self):
        self.assertIsNone(ft._safe_watch_path(""))
        self.assertIsNone(ft._safe_watch_path(None))
        self.assertIsNone(ft._safe_watch_path("."))
        self.assertIsNone(ft._safe_watch_path(".."))


class DownloadTorrentUnsafeNameTests(unittest.TestCase):
    def setUp(self):
        self.tmp_watch_dir = helpers.use_watch_dir(self)

    def test_download_torrent_refuses_unsafe_name_without_any_request(self):
        with unittest.mock.patch.object(ft.requests, "get") as mock_get:
            status = ft.download_torrent("../evil", "https://example.invalid/x.torrent")

        mock_get.assert_not_called()
        self.assertEqual(status, "failed")
        self.assertEqual(os.listdir(self.tmp_watch_dir), [])

    def test_remove_watch_file_refuses_unsafe_name_without_touching_disk(self):
        # Asserted on disk rather than by patching os.remove: that patch is
        # process-wide, so a log rotation triggered by the warning would
        # trip it too.
        parent = helpers.make_temp_dir(self, "fetch_torrents_test_escape_")
        watch_dir = os.path.join(parent, "watch")
        os.mkdir(watch_dir)
        outside = os.path.join(parent, "evil.torrent")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("must survive")

        with unittest.mock.patch.object(ft, "watch_dir", watch_dir):
            ft._remove_watch_file("../evil")

        with open(outside, encoding="utf-8") as f:
            self.assertEqual(f.read(), "must survive")


class FetcherRequestTimeoutTests(unittest.TestCase):
    """Every upstream request has a timeout, so no slow or stalled distro
    site can hang the daily run."""

    def test_every_fetcher_and_the_download_pass_a_30_second_timeout(self):
        helpers.use_watch_dir(self)
        calls = {
            **{name: fetcher for name, fetcher in ft.DEFAULT_FETCHERS},
            "kali-old": ft.fetch_kali_old_versions,
            "fedora-old": ft.fetch_fedora_workstation_old_versions,
            "download": lambda: ft.download_torrent(
                "x.iso", "https://example.invalid/x"
            ),
        }
        for name, call in calls.items():
            with self.subTest(name):
                timeouts = []

                def get(url, timeouts=timeouts, **kwargs):
                    timeouts.append(kwargs)
                    return helpers.fake_response("<html></html>")

                with (
                    unittest.mock.patch.object(ft.requests, "get", get),
                    self.assertNoLogs(ft.logger, level="CRITICAL"),
                ):
                    call()

                self.assertTrue(timeouts)
                self.assertEqual(timeouts, [{"timeout": 30}] * len(timeouts))


def _get_page(html):
    return unittest.mock.patch.object(
        ft.requests, "get", return_value=helpers.fake_response(html)
    )


class FetchArchLatestSelectionTests(unittest.TestCase):
    def test_unavailable_row_before_an_available_one_is_skipped(self):
        html = (
            "<html><body><table id='release-table'>"
            "<tr><td class='available-no'></td>"
            "<td><a href='/releng/releases/2026.10.01/torrent/'>t</a></td></tr>"
            "<tr><td class='available-yes'></td>"
            "<td><a href='/releng/releases/2026.09.01/torrent/'>t</a></td></tr>"
            "</table></body></html>"
        )

        with _get_page(html):
            results = ft.fetch_arch_latest()

        self.assertEqual(
            results,
            {
                "archlinux-2026.09.01": "https://archlinux.org/releng/releases/2026.09.01/torrent/"
            },
        )

    def test_row_without_a_torrent_link_is_skipped(self):
        html = (
            "<html><body><table id='release-table'>"
            "<tr><td class='available-yes'></td><td>no link</td></tr>"
            "<tr><td class='available-yes'></td>"
            "<td><a href='/releng/releases/2026.09.01/torrent/'>t</a></td></tr>"
            "</table></body></html>"
        )

        with _get_page(html):
            results = ft.fetch_arch_latest()

        self.assertEqual(list(results), ["archlinux-2026.09.01"])


class FetchKaliSelectionTests(unittest.TestCase):
    def test_page_without_a_release_number_returns_false(self):
        with _get_page("<html><body>no installers here</body></html>"):
            self.assertIs(ft.fetch_kali_latest(), False)

    def test_old_versions_are_every_version_but_the_newest(self):
        html = "".join(
            f'<a href="kali-{v}/">kali-{v}</a>'
            for v in ("2025.4", "2026.2", "2025.10", "2026.1")
        )

        with _get_page(f"<html><body>{html}</body></html>"):
            results = ft.fetch_kali_old_versions()

        self.assertEqual(
            results, helpers.kali_candidates("2025.4", "2025.10", "2026.1")
        )


class FetchFedoraSelectionTests(unittest.TestCase):
    BASE = "https://torrent.fedoraproject.org/torrents/"

    def _page(self, *versions, arch="x86_64"):
        links = "".join(
            f'<a href="Fedora-Workstation-Live-{arch}-{v}.torrent">t</a>'
            for v in versions
        )
        return _get_page(f"<html><body>{links}</body></html>")

    def _entry(self, version, arch="x86_64"):
        name = f"Fedora-Workstation-Live-{arch}-{version}"
        return name, f"{self.BASE}{name}.torrent"

    def test_latest_compares_versions_numerically(self):
        with self._page(100, 99, 98):
            results = ft.fetch_fedora_workstation()

        self.assertEqual(results, dict([self._entry(100)]))

    def test_old_versions_compare_numerically_and_skip_only_the_newest(self):
        with self._page(99, 100, 98):
            results = ft.fetch_fedora_workstation_old_versions()

        self.assertEqual(results, dict([self._entry(99), self._entry(98)]))

    def test_same_version_listed_twice_is_one_candidate(self):
        with self._page(44, 44, 43):
            latest = ft.fetch_fedora_workstation()
        with self._page(44, 44, 43):
            old = ft.fetch_fedora_workstation_old_versions()

        self.assertEqual(latest, dict([self._entry(44)]))
        self.assertEqual(old, dict([self._entry(43)]))


class ParseSupportedDistrosWarningTests(unittest.TestCase):
    def test_unknown_entries_are_named_in_the_warning(self):
        with self.assertLogs(ft.logger, level="WARNING") as logs:
            result = ft.parse_supported_distros(
                env={"FETCH_TORRENTS_DISTROS": "Ubuntu, gentoo,arch,slackware"}
            )

        self.assertEqual(result, ["ubuntu", "arch"])
        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                "FETCH_TORRENTS_DISTROS contains unknown distributions: gentoo, "
                "slackware. Valid values: " + ALL_DISTROS_TEXT
            ],
        )


if __name__ == "__main__":
    unittest.main()
