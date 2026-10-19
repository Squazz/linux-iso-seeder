"""Tests for scripts/live_check.py (the weekly drift job): deciding whether
a live fetcher's candidate looks like a real release, and the scraper and
tracker checks and exit codes built on that, with the network injected.

Run with: python -m unittest discover -s tests
"""

import contextlib
import importlib.util
import io
import os
import unittest

import helpers
import requests

# Loaded from its path so scripts/ never lands on sys.path for other tests.
_spec = importlib.util.spec_from_file_location(
    "live_check", os.path.join(helpers.REPO_ROOT, "scripts", "live_check.py")
)
assert _spec and _spec.loader
live_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_check)


def setUpModule():
    helpers.isolate_module()


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


class DistroOfTests(unittest.TestCase):
    def test_old_release_fetchers_are_checked_as_their_distro(self):
        self.assertEqual(live_check.distro_of("kali-old"), "kali")
        self.assertEqual(live_check.distro_of("fedora-old"), "fedora")
        self.assertEqual(live_check.distro_of("mint"), "mint")


def quietly(fn, *args, **kwargs):
    """Calls fn, swallowing what it prints; returns its result."""
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        return fn(*args, **kwargs)


UBUNTU_URL = "https://releases.ubuntu.com/noble/ubuntu-24.04-desktop-amd64.iso.torrent"
ARCH_URL = "https://archlinux.org/releng/releases/2026.10.01/torrent/"


class IsReachableTests(unittest.TestCase):
    def _reachable(self, head, get=None):
        def unexpected_get(url, **kwargs):
            raise AssertionError("GET should not be needed")

        return live_check.is_reachable(UBUNTU_URL, head=head, get=get or unexpected_get)

    def test_head_200_is_reachable(self):
        self.assertTrue(self._reachable(lambda url, **kw: helpers.fake_response()))

    def test_head_404_is_not_reachable(self):
        self.assertFalse(
            self._reachable(lambda url, **kw: helpers.fake_response(status=404))
        )

    def test_head_follows_redirects(self):
        heads = []

        def head(url, **kwargs):
            heads.append((url, kwargs))
            return helpers.fake_response()

        self._reachable(head)

        self.assertEqual(
            heads, [(UBUNTU_URL, {"allow_redirects": True, "timeout": 30})]
        )

    def test_head_not_allowed_falls_back_to_a_streamed_get(self):
        gets = []

        def get(url, **kwargs):
            gets.append((url, kwargs))
            return helpers.fake_response(b"d8:announce")

        self.assertTrue(
            self._reachable(
                lambda url, **kw: helpers.fake_response(status=405), get=get
            )
        )
        self.assertEqual(gets, [(UBUNTU_URL, {"stream": True, "timeout": 30})])

    def test_get_fallback_that_fails_is_not_reachable(self):
        self.assertFalse(
            self._reachable(
                lambda url, **kw: helpers.fake_response(status=405),
                get=lambda url, **kw: helpers.fake_response(status=404),
            )
        )

    def test_request_error_is_not_reachable(self):
        def head(url, **kwargs):
            raise requests.ConnectionError("down")

        self.assertFalse(self._reachable(head))


class CheckScrapersTests(unittest.TestCase):
    def _check(self, fetchers, reachable=lambda url: True):
        return quietly(
            live_check.check_scrapers, fetchers=fetchers, reachable=reachable
        )

    def test_well_formed_reachable_candidates_pass(self):
        fetchers = (("arch", lambda: {"archlinux-2026.10.01": ARCH_URL}),)

        self.assertEqual(self._check(fetchers), [])

    def test_fetcher_returning_nothing_fails(self):
        for empty in ({}, None):
            with self.subTest(empty=empty):
                fetchers = (("arch", lambda empty=empty: empty),)

                self.assertEqual(self._check(fetchers), ["arch: no candidates"])

    def test_old_release_fetchers_may_be_empty(self):
        fetchers = (("kali-old", dict), ("fedora-old", dict))

        self.assertEqual(self._check(fetchers), [])

    def test_malformed_candidates_are_reported_and_not_probed(self):
        probed = []
        fetchers = (("arch", lambda: {"archlinux-2026.10.01": "http://x/a.iso"}),)

        failures = self._check(fetchers, reachable=probed.append)

        self.assertEqual(
            failures,
            [
                "arch: URL 'http://x/a.iso' is not https",
                "arch: URL 'http://x/a.iso' is not a .torrent",
            ],
        )
        self.assertEqual(probed, [])

    def test_every_candidate_unreachable_fails(self):
        fetchers = (("ubuntu", lambda: {"ubuntu-24.04-desktop-amd64.iso": UBUNTU_URL}),)

        self.assertEqual(
            self._check(fetchers, reachable=lambda url: False),
            ["ubuntu: none of its torrent URLs returned 200"],
        )

    def test_one_reachable_candidate_is_enough_and_stops_the_probing(self):
        older = UBUNTU_URL.replace("24.04", "22.04")
        newest = UBUNTU_URL.replace("24.04", "24.10")
        probed = []

        def reachable(url):
            probed.append(url)
            return url == UBUNTU_URL

        fetchers = (
            (
                "ubuntu",
                lambda: {
                    "ubuntu-22.04-desktop-amd64.iso": older,
                    "ubuntu-24.04-desktop-amd64.iso": UBUNTU_URL,
                    "ubuntu-24.10-desktop-amd64.iso": newest,
                },
            ),
        )

        self.assertEqual(self._check(fetchers, reachable=reachable), [])
        self.assertEqual(probed, [older, UBUNTU_URL])

    def test_failures_from_every_fetcher_are_collected(self):
        fetchers = (
            ("arch", dict),
            ("ubuntu", lambda: {"ubuntu-24.04-desktop-amd64.iso": UBUNTU_URL}),
        )

        self.assertEqual(
            self._check(fetchers, reachable=lambda url: False),
            ["arch: no candidates", "ubuntu: none of its torrent URLs returned 200"],
        )

    def test_default_fetchers_include_the_old_release_ones(self):
        names = [name for name, _fetcher in live_check.FETCHERS]

        self.assertEqual(
            names,
            [name for name, _fetcher in live_check.ft.DEFAULT_FETCHERS]
            + ["kali-old", "fedora-old"],
        )


SERVER_URL = UBUNTU_URL.replace("desktop", "live-server")
OLDER_URL = UBUNTU_URL.replace("24.04", "22.04")
UBUNTU_CANDIDATES = {
    "ubuntu-24.04-live-server-amd64.iso": SERVER_URL,
    "ubuntu-24.04-desktop-amd64.iso": UBUNTU_URL,
    "ubuntu-22.04-desktop-amd64.iso": OLDER_URL,
}


class CheckTrackerTests(unittest.TestCase):
    def setUp(self):
        self.requested = []
        self.scraped = []
        self.routes = {}
        self.result = None

    def get(self, url, timeout=None):
        self.requested.append(url)
        return self.routes.get(url, helpers.fake_response(status=404))

    def scrape(self, path):
        with open(path, "rb") as f:
            self.scraped.append(f.read())
        return self.result

    def _check(self, candidates=UBUNTU_CANDIDATES):
        return quietly(
            live_check.check_tracker,
            fetch=lambda: candidates,
            get=self.get,
            scrape=self.scrape,
        )

    def test_integer_counts_from_the_newest_desktop_torrent_pass(self):
        self.routes[UBUNTU_URL] = helpers.fake_response(b"d8:announce")
        self.result = {"seeders": 10, "leechers": 2}

        self.assertEqual(self._check(), [])
        self.assertEqual(self.requested, [UBUNTU_URL])
        self.assertEqual(self.scraped, [b"d8:announce"])

    def test_falls_back_to_an_older_desktop_torrent(self):
        self.routes[OLDER_URL] = helpers.fake_response(b"old")
        self.result = {"seeders": 1, "leechers": 0}

        self.assertEqual(self._check(), [])
        self.assertEqual(self.requested, [UBUNTU_URL, OLDER_URL])
        self.assertEqual(self.scraped, [b"old"])

    def test_no_downloadable_desktop_torrent_fails_without_scraping(self):
        self.routes[SERVER_URL] = helpers.fake_response(b"server")

        self.assertEqual(
            self._check(),
            ["tracker: no current Ubuntu desktop torrent could be downloaded"],
        )
        self.assertNotIn(SERVER_URL, self.requested)
        self.assertEqual(self.scraped, [])

    def test_no_candidates_at_all_fails(self):
        for candidates in ({}, None):
            with self.subTest(candidates=candidates):
                self.assertEqual(
                    self._check(candidates),
                    ["tracker: no current Ubuntu desktop torrent could be downloaded"],
                )

    def test_no_tracker_answer_fails(self):
        self.routes[UBUNTU_URL] = helpers.fake_response(b"d8:announce")

        self.assertEqual(self._check(), ["tracker: no tracker answered the scrape"])

    def test_non_integer_counts_fail(self):
        self.routes[UBUNTU_URL] = helpers.fake_response(b"d8:announce")
        for result in (
            {"seeders": "10", "leechers": 2},
            {"seeders": 10, "leechers": None},
            {"seeders": 10},
        ):
            with self.subTest(result=result):
                self.result = result

                self.assertEqual(
                    self._check(),
                    [f"tracker: non-integer seeders/leechers in {result}"],
                )


class MainTests(unittest.TestCase):
    def _main(self, argv, failures=()):
        calls = []

        def check():
            calls.append("check")
            return list(failures)

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = live_check.main(argv, checks={"scrapers": check})
        return code, calls, err.getvalue()

    def test_no_problems_exits_0(self):
        self.assertEqual(self._main(["scrapers"]), (0, ["check"], ""))

    def test_a_problem_exits_1_and_is_reported(self):
        code, _calls, err = self._main(["scrapers"], failures=["arch: no candidates"])

        self.assertEqual(code, 1)
        self.assertEqual(err, "DRIFT: arch: no candidates\n")

    def test_bad_usage_exits_2_with_the_usage_text(self):
        for argv in ([], ["nope"], ["scrapers", "tracker"]):
            with self.subTest(argv=argv):
                code, calls, err = self._main(argv)

                self.assertEqual((code, calls), (2, []))
                self.assertIn("Usage:", err)

    def test_default_checks_are_scrapers_and_tracker(self):
        self.assertEqual(
            live_check.CHECKS,
            {
                "scrapers": live_check.check_scrapers,
                "tracker": live_check.check_tracker,
            },
        )


if __name__ == "__main__":
    unittest.main()
