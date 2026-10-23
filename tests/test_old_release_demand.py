"""Tests for the old-release demand check
(FETCH_TORRENTS_CHECK_OLD_RELEASES): has_unmet_demand(), the
per-release evaluation and the recheck bookkeeping.

Run with: python -m unittest discover -s tests
"""

import os
import unittest
import unittest.mock
from datetime import date

import helpers

import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


def demand(scrape, **overrides):
    """has_unmet_demand(scrape) with the daily run's default thresholds
    (10 leechers, 0.1 leechers per seeder, zero-seeder swarms excluded),
    each overridable by keyword."""
    thresholds = {
        "min_leechers": 10,
        "min_leecher_ratio": 0.1,
        "allow_zero_seeders": False,
        **overrides,
    }
    return ft.has_unmet_demand(scrape, **thresholds)


class HasUnmetDemandTests(unittest.TestCase):
    """Demand requires an absolute floor (enough leechers to be worth the
    disk/bandwidth), a relative one (leechers reach some fraction of the
    seeder count - i.e. the swarm isn't already vastly over-served), and by
    default a real, currently-seeded copy to exist at all. A single leecher
    on a 1000-seeder swarm must never pass just because leechers>0, and a
    swarm with plenty of leechers but even more seeders (already well
    served) shouldn't either."""

    def test_none_scrape_result_is_no_demand(self):
        self.assertFalse(demand(None, min_leechers=1, min_leecher_ratio=1.2))

    def test_missing_counts_mean_zero(self):
        # A tracker's scrape can omit a count; missing must read as 0, not
        # as some peer.
        self.assertIs(
            demand(
                {"seeders": 0},
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=True,
            ),
            False,
        )
        self.assertIs(demand({"leechers": 5}, min_leechers=1), False)

    def test_below_absolute_threshold_is_no_demand(self):
        # Seeded swarm and no ratio requirement, so only the leecher floor
        # can turn this down.
        self.assertFalse(
            demand({"leechers": 0, "seeders": 5}, min_leechers=1, min_leecher_ratio=0.0)
        )

    def test_single_leecher_on_huge_swarm_is_no_demand(self):
        self.assertFalse(
            demand(
                {"leechers": 1, "seeders": 1000}, min_leechers=1, min_leecher_ratio=1.2
            )
        )

    def test_meets_absolute_but_not_ratio_is_no_demand(self):
        # 11 leechers clears a min_leechers=10 floor, but 11 < 1.2x the 10 seeders.
        self.assertFalse(demand({"leechers": 11, "seeders": 10}, min_leecher_ratio=1.2))

    def test_meets_both_absolute_and_ratio_thresholds_is_demand(self):
        self.assertTrue(demand({"leechers": 25, "seeders": 10}, min_leecher_ratio=1.2))

    def test_exactly_at_ratio_threshold_is_demand(self):
        self.assertTrue(demand({"leechers": 12, "seeders": 10}, min_leecher_ratio=1.2))

    def test_zero_seeders_is_excluded_by_default(self):
        # A scrape can't tell us whether the leechers collectively hold every
        # piece - with zero seeders there's no verified-complete copy in the
        # swarm at all, so we could end up leeching something we can never
        # finish and therefore never seed back. Excluded unless the operator
        # opts into the gamble via allow_zero_seeders.
        self.assertFalse(demand({"leechers": 10, "seeders": 0}, min_leecher_ratio=1.2))

    def test_zero_seeders_counts_as_demand_when_explicitly_allowed(self):
        self.assertTrue(
            demand(
                {"leechers": 10, "seeders": 0},
                min_leecher_ratio=1.2,
                allow_zero_seeders=True,
            )
        )

    def test_zero_seeders_still_needs_the_absolute_floor_when_allowed(self):
        self.assertFalse(
            demand(
                {"leechers": 5, "seeders": 0},
                min_leecher_ratio=1.2,
                allow_zero_seeders=True,
            )
        )

    def test_lopsided_but_substantial_swarms_still_count_as_demand_at_default_ratio(
        self,
    ):
        # FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHER_RATIO defaults to 0.1: we
        # have no way of knowing whether existing seeders have spare upload
        # capacity or are bandwidth-limited, so leechers don't need to
        # approach or outnumber seeders to represent real demand - 10:100
        # and 100:1000 both clearly indicate room for another seeder.
        self.assertTrue(demand({"leechers": 10, "seeders": 100}, min_leechers=1))
        self.assertTrue(demand({"leechers": 100, "seeders": 1000}, min_leechers=1))

    def test_extreme_oversupply_still_fails_at_default_ratio(self):
        # 3 leechers on 673 seeders (an actual old Kali release scraped
        # during development) is still not demand, even at the more
        # permissive 0.1 default - it needs at least 67.3 leechers.
        self.assertFalse(demand({"leechers": 3, "seeders": 673}, min_leechers=1))


class ShouldRecheckOldReleaseTests(unittest.TestCase):
    """Without this gate, check_old_releases_for_demand() would re-download
    and re-scrape every not-yet-wanted candidate on every daily run
    forever - this is what lets a recent "no demand" result be trusted for
    a while instead."""

    def test_never_checked_is_due(self):
        self.assertTrue(
            ft.should_recheck_old_release(
                "x", {}, date(2026, 1, 8), recheck_interval_days=7
            )
        )

    def test_checked_recently_is_not_due(self):
        state = {"x": {"last_checked": "2026-01-05", "leechers": 0}}
        self.assertFalse(
            ft.should_recheck_old_release(
                "x", state, date(2026, 1, 8), recheck_interval_days=7
            )
        )

    def test_checked_exactly_at_interval_is_due(self):
        state = {"x": {"last_checked": "2026-01-01", "leechers": 0}}
        self.assertTrue(
            ft.should_recheck_old_release(
                "x", state, date(2026, 1, 8), recheck_interval_days=7
            )
        )

    def test_checked_past_interval_is_due(self):
        state = {"x": {"last_checked": "2025-12-01", "leechers": 0}}
        self.assertTrue(
            ft.should_recheck_old_release(
                "x", state, date(2026, 1, 8), recheck_interval_days=7
            )
        )


class EvaluateOldReleaseDemandBoundaryTests(unittest.TestCase):
    """What evaluate_old_release_demand() hands the network: the download
    request, and a temporary on-disk copy of the .torrent for the tracker
    scrape that is gone again afterwards, whatever the scrape did."""

    NAME = "kali-linux-2025.4-installer-amd64.iso"
    BODY = b"kali-linux-2025.4-installer-amd64.iso metadata"

    def setUp(self):
        self.tracker = helpers.OldReleaseTracker()
        self.tracker.patch(self)

    def _evaluate(self, url, **kwargs):
        return ft.evaluate_old_release_demand(
            self.NAME,
            url,
            min_leechers=4,
            min_leecher_ratio=0.5,
            allow_zero_seeders=False,
            **kwargs,
        )

    def test_scrapes_a_temporary_copy_that_is_removed_afterwards(self):
        url = self.tracker.candidate(self.NAME, helpers.swarm(6, 10))

        result = self._evaluate(url)

        self.assertEqual(result, (True, self.BODY, helpers.swarm(6, 10)))
        self.assertEqual(self.tracker.requests, [(url, 30)])
        [(body, path, timeout)] = self.tracker.scrapes
        self.assertEqual((body, timeout), (self.BODY, 15))
        self.assertFalse(os.path.exists(path))

    def test_scrape_timeout_is_passed_through(self):
        url = self.tracker.candidate(self.NAME, helpers.swarm(6, 10))

        self._evaluate(url, timeout=3)

        self.assertEqual([t for _, _, t in self.tracker.scrapes], [3])

    def test_scrape_error_counts_as_unknown_demand_and_cleans_up(self):
        url = self.tracker.candidate(self.NAME, OSError("tracker went away"))

        with self.assertLogs(ft.logger, level="WARNING") as logs:
            result = self._evaluate(url)

        self.assertEqual(result, (False, self.BODY, None))
        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [f"Could not scrape {self.NAME}: tracker went away"],
        )
        [(_, path, _)] = self.tracker.scrapes
        self.assertFalse(os.path.exists(path))

    def test_temp_file_that_cannot_be_created_counts_as_unknown_demand(self):
        url = self.tracker.candidate(self.NAME, helpers.swarm(6, 10))

        with (
            unittest.mock.patch.object(
                ft.tempfile, "NamedTemporaryFile", side_effect=OSError("disk full")
            ),
            self.assertLogs(ft.logger, level="WARNING"),
        ):
            result = self._evaluate(url)

        self.assertEqual(result, (False, self.BODY, None))
        self.assertEqual(self.tracker.scrapes, [])

    def test_404_is_logged_as_not_found_not_as_a_failure(self):
        url = "https://cdimage.example/gone.torrent"

        with self.assertLogs(ft.logger, level="INFO") as logs:
            result = self._evaluate(url)

        self.assertEqual(result, (False, None, None))
        self.assertEqual(
            [(r.levelname, r.getMessage()) for r in logs.records],
            [("INFO", f"{url} not found upstream (404) during old-release check.")],
        )
        self.assertEqual(self.tracker.scrapes, [])

    def test_connection_error_is_logged_as_a_failed_download(self):
        url = "https://cdimage.example/unreachable.torrent"
        self.tracker.routes[url] = ConnectionError("connection refused")

        with self.assertLogs(ft.logger, level="INFO") as logs:
            result = self._evaluate(url)

        self.assertEqual(result, (False, None, None))
        self.assertEqual(
            [(r.levelname, r.getMessage()) for r in logs.records],
            [
                (
                    "ERROR",
                    (
                        f"Failed to download {url} for old-release check: "
                        "connection refused"
                    ),
                )
            ],
        )
        self.assertEqual(self.tracker.scrapes, [])

    def test_server_error_is_logged_as_a_failed_download(self):
        url = "https://cdimage.example/broken.torrent"
        self.tracker.routes[url] = helpers.fake_response(status=500)

        with self.assertLogs(ft.logger, level="INFO") as logs:
            result = self._evaluate(url)

        self.assertEqual(result, (False, None, None))
        [record] = logs.records
        self.assertEqual(record.levelname, "ERROR")
        self.assertRegex(
            record.getMessage(),
            f"^Failed to download {url} for old-release check: 500 Server Error",
        )
        self.assertEqual(self.tracker.scrapes, [])


def kali(version, variant="installer"):
    return f"kali-linux-2025.{version}-{variant}-amd64.iso"


class CheckOldReleasesSociableTests(unittest.TestCase):
    """check_old_releases_for_demand() over the real
    evaluate_old_release_demand(), with only the download and the tracker
    scrape faked (OldReleaseTracker). Tests run several candidates, so one
    skipped candidate can't stop the rest from being checked, and every
    counter has to add up past 1."""

    TRACKER = "udp://tracker.example:6969"

    def setUp(self):
        self.tmp_watch_dir = helpers.use_watch_dir(self)
        self.tracker = helpers.OldReleaseTracker()
        self.tracker.patch(self)

    def _check(self, discovery, distros=("kali",), **overrides):
        """Thresholds: >= 4 leechers and >= 0.5x as many leechers as
        seeders, zero-seeder swarms excluded."""
        kwargs = {
            "include_low_demand": False,
            "min_leechers": 4,
            "min_leecher_ratio": 0.5,
            "allow_zero_seeders": False,
            "check_state": {},
            "removed_history": {},
            "today": date(2026, 1, 8),
        }
        kwargs.update(overrides)
        return ft.check_old_releases_for_demand(
            list(distros), discovery=discovery, **kwargs
        )

    def _watch_files(self):
        return sorted(os.listdir(self.tmp_watch_dir))

    def test_release_transmission_already_loaded_is_not_downloaded_again(self):
        # transmission-daemon renames a loaded watch file to .torrent.added.
        loaded = kali(4)
        candidates = {loaded: self.tracker.candidate(loaded, helpers.swarm(50, 1))}
        with open(
            os.path.join(self.tmp_watch_dir, f"{loaded}.torrent.added"), "wb"
        ) as f:
            f.write(b"already seeding")

        added, skipped, _state = self._check({"kali": lambda: candidates})

        self.assertEqual((added, skipped), (0, 0))
        self.assertEqual(self._watch_files(), [f"{loaded}.torrent.added"])

    def test_every_outcome_is_counted_and_later_candidates_still_checked(self):
        removed_a, removed_b = kali(1), kali(1, "live")
        unsafe = "kali-linux-../../etc/cron.d/evil"
        present, recent = kali(2, "live"), kali(2)
        thin, zero, unknown = kali(3), kali(3, "live"), kali(3, "installer-purple")
        missing = kali(3, "everything")
        wanted_a, wanted_b = kali(4), kali(4, "live")
        candidates = {
            removed_a: self.tracker.candidate(removed_a, helpers.swarm(50, 1)),
            removed_b: self.tracker.candidate(removed_b, helpers.swarm(50, 1)),
            unsafe: "https://cdimage.example/evil.torrent",
            present: self.tracker.candidate(present, helpers.swarm(50, 1)),
            recent: self.tracker.candidate(recent, helpers.swarm(50, 1)),
            thin: self.tracker.candidate(thin, helpers.swarm(5, 20)),
            zero: self.tracker.candidate(zero, helpers.swarm(9, 0)),
            unknown: self.tracker.candidate(unknown, None),
            missing: "https://cdimage.example/missing.torrent",
            wanted_a: self.tracker.candidate(wanted_a, helpers.swarm(6, 10)),
            wanted_b: self.tracker.candidate(wanted_b, helpers.swarm(30, 2)),
        }
        with open(os.path.join(self.tmp_watch_dir, f"{present}.torrent"), "wb") as f:
            f.write(b"already seeding")
        check_state = {recent: {"last_checked": "2026-01-05", "leechers": 0}}
        removed_history = {
            **helpers.removed(removed_a, on="2025-12-01"),
            **helpers.removed(removed_b, on="2025-12-01"),
        }

        with self.assertLogs(ft.logger, level="DEBUG") as logs:
            added, skipped, new_state = self._check(
                # ubuntu has no discovery and fedora finds nothing: neither
                # may stop kali from being checked.
                {"fedora": dict, "kali": lambda: candidates},
                distros=("ubuntu", "fedora", "kali"),
                check_state=check_state,
                removed_history=removed_history,
            )

        # Skipped: removed x2, unsafe, recent, thin, zero, unknown, missing.
        # Already present isn't counted either way.
        self.assertEqual((added, skipped), (2, 8))
        self.assertEqual(
            self._watch_files(),
            sorted(f"{n}.torrent" for n in (present, wanted_a, wanted_b)),
        )
        with open(os.path.join(self.tmp_watch_dir, f"{wanted_a}.torrent"), "rb") as f:
            self.assertEqual(f.read(), f"{wanted_a} metadata".encode())
        self.assertEqual(
            new_state,
            {
                recent: {"last_checked": "2026-01-05", "leechers": 0},
                thin: {"last_checked": "2026-01-08", "leechers": 5},
                zero: {"last_checked": "2026-01-08", "leechers": 9},
                unknown: {"last_checked": "2026-01-08", "leechers": None},
                missing: {"last_checked": "2026-01-08", "leechers": None},
                wanted_a: {"last_checked": "2026-01-08", "leechers": 6},
                wanted_b: {"last_checked": "2026-01-08", "leechers": 30},
            },
        )
        self.assertEqual(
            check_state, {recent: {"last_checked": "2026-01-05", "leechers": 0}}
        )
        self.assertEqual(
            [url for url, _ in self.tracker.requests],
            [candidates[n] for n in (thin, zero, unknown, missing, wanted_a, wanted_b)],
        )
        messages = [r.getMessage() for r in logs.records]
        for expected in (
            (
                f"Skipping old release {removed_a} - previously removed on 2025-12-01, "
                "not re-adding automatically."
            ),
            (
                f"Skipping old release {removed_b} - previously removed on 2025-12-01, "
                "not re-adding automatically."
            ),
            f"Refusing to save old release with unsafe name: {unsafe!r}",
            f"Skipping old release {recent} - checked recently, not due for recheck.",
            (
                f"Skipping old release {thin} - 5 leechers / 20 seeders via "
                f"{self.TRACKER} (need >= 4 leechers and >= 0.5x as many leechers "
                "as seeders)."
            ),
            (
                f"Skipping old release {zero} - 9 leechers but 0 seeders via "
                f"{self.TRACKER} (no verified-complete copy in the swarm; set "
                "FETCH_TORRENTS_OLD_RELEASE_ALLOW_ZERO_SEEDERS=true to gamble on it)."
            ),
            (
                f"Skipping old release {unknown} - could not determine live demand "
                "from any tracker."
            ),
            (
                f"Found unmet demand on old release {wanted_a} (6 leechers via "
                f"{self.TRACKER}) - added."
            ),
            (
                f"Found unmet demand on old release {wanted_b} (30 leechers via "
                f"{self.TRACKER}) - added."
            ),
        ):
            self.assertIn(expected, messages)
        self.assertEqual(
            [m for m in messages if m.startswith(f"Skipping old release {missing}")],
            [],
        )

    def test_below_floor_zero_seeder_swarm_is_logged_against_the_thresholds(self):
        # allow_zero_seeders=True: a zero-seeder swarm can count as demand,
        # but 2 leechers is still under the 4-leecher floor.
        name = kali(3)
        candidates = {name: self.tracker.candidate(name, helpers.swarm(2, 0))}

        with self.assertLogs(ft.logger, level="INFO") as logs:
            added, skipped, _ = self._check(
                {"kali": lambda: candidates}, allow_zero_seeders=True
            )

        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                (
                    f"Skipping old release {name} - 2 leechers / 0 seeders via "
                    f"{self.TRACKER} (need >= 4 leechers and >= 0.5x as many "
                    "leechers as seeders)."
                )
            ],
        )

    def test_rechecks_after_7_days_by_default(self):
        name = kali(3)
        candidates = {name: self.tracker.candidate(name, helpers.swarm(6, 10))}
        check_state = {name: {"last_checked": "2026-01-01", "leechers": 0}}

        # Checked exactly 7 days ago; _check() leaves recheck_interval_days
        # at its default.
        added, _, _ = self._check({"kali": lambda: candidates}, check_state=check_state)

        self.assertEqual(added, 1)

    def test_today_and_saved_state_default_to_now_and_empty(self):
        name = kali(3)
        candidates = {name: self.tracker.candidate(name, helpers.swarm(2, 10))}

        with unittest.mock.patch.object(
            ft, "date", helpers.fixed_date(date(2026, 3, 14))
        ):
            _added, _skipped, new_state = ft.check_old_releases_for_demand(
                ["kali"],
                include_low_demand=False,
                min_leechers=4,
                min_leecher_ratio=0.5,
                allow_zero_seeders=False,
                discovery={"kali": lambda: candidates},
            )

        self.assertEqual(
            new_state, {name: {"last_checked": "2026-03-14", "leechers": 2}}
        )


class CheckOldReleasesAtomicWriteTests(unittest.TestCase):
    """An old release whose .torrent can't be written in full must leave no
    <name>.torrent behind (it would count as present forever) and must not
    be recorded as checked, so the next run tries it again. The real
    evaluate_old_release_demand() runs (OldReleaseTracker); the disk fills
    at fetch_torrents' own open()."""

    NAME = kali(4)

    def setUp(self):
        self.tmp_watch_dir = helpers.use_watch_dir(self)
        self.tracker = helpers.OldReleaseTracker()
        self.tracker.patch(self)

    def _check(self, candidates):
        """Every served candidate has unmet demand (30 leechers, 1 seeder)."""
        return ft.check_old_releases_for_demand(
            ["kali"],
            include_low_demand=False,
            min_leechers=4,
            min_leecher_ratio=0.5,
            allow_zero_seeders=False,
            check_state={},
            removed_history={},
            today=date(2026, 1, 8),
            discovery={"kali": lambda: candidates},
        )

    def _wanted(self, *names):
        return {
            name: self.tracker.candidate(name, helpers.swarm(30, 1)) for name in names
        }

    def test_failed_write_leaves_no_file_and_is_not_recorded(self):
        with (
            helpers.disk_full_open(ft),
            self.assertLogs(ft.logger, level="ERROR") as logs,
        ):
            added, skipped, state = self._check(self._wanted(self.NAME))

        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(os.listdir(self.tmp_watch_dir), [])
        self.assertEqual(state, {})
        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                (
                    f"Failed to save old release {self.NAME}: "
                    "[Errno 28] No space left on device"
                )
            ],
        )

    def test_next_run_adds_it_after_a_failed_write(self):
        candidates = self._wanted(self.NAME)
        with helpers.disk_full_open(ft), self.assertLogs(ft.logger, level="ERROR"):
            self._check(candidates)

        added, _, _ = self._check(candidates)

        self.assertEqual(added, 1)
        self.assertEqual(os.listdir(self.tmp_watch_dir), [f"{self.NAME}.torrent"])
        with open(os.path.join(self.tmp_watch_dir, f"{self.NAME}.torrent"), "rb") as f:
            self.assertEqual(f.read(), f"{self.NAME} metadata".encode())

    def test_a_failed_write_is_counted_and_later_candidates_still_added(self):
        later = kali(4, "live")
        # An unsafe name is skipped first, so the failed write is a second skip.
        candidates = {"kali-linux/../evil": "https://cdimage.example/evil.torrent"}
        candidates |= self._wanted(self.NAME, later)

        with (
            helpers.disk_full_open(ft, only=self.NAME),
            self.assertLogs(ft.logger, level="ERROR"),
        ):
            added, skipped, state = self._check(candidates)

        self.assertEqual((added, skipped), (1, 2))
        self.assertEqual(os.listdir(self.tmp_watch_dir), [f"{later}.torrent"])
        self.assertEqual(list(state), [later])


if __name__ == "__main__":
    unittest.main()
