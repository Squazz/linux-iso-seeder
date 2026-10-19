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
            ft.has_unmet_demand(
                None, min_leechers=1, min_leecher_ratio=1.2, allow_zero_seeders=False
            )
        )

    def test_missing_counts_mean_zero(self):
        # A tracker's scrape can omit a count; missing must read as 0, not
        # as some peer.
        self.assertIs(
            ft.has_unmet_demand(
                {"seeders": 0},
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=True,
            ),
            False,
        )
        self.assertIs(
            ft.has_unmet_demand(
                {"leechers": 5},
                min_leechers=1,
                min_leecher_ratio=0.1,
                allow_zero_seeders=False,
            ),
            False,
        )

    def test_below_absolute_threshold_is_no_demand(self):
        self.assertFalse(
            ft.has_unmet_demand(
                {"leechers": 0, "seeders": 0},
                min_leechers=1,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )
        )

    def test_single_leecher_on_huge_swarm_is_no_demand(self):
        self.assertFalse(
            ft.has_unmet_demand(
                {"leechers": 1, "seeders": 1000},
                min_leechers=1,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )
        )

    def test_meets_absolute_but_not_ratio_is_no_demand(self):
        # 11 leechers clears a min_leechers=10 floor, but 11 < 1.2x the 10 seeders.
        self.assertFalse(
            ft.has_unmet_demand(
                {"leechers": 11, "seeders": 10},
                min_leechers=10,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )
        )

    def test_meets_both_absolute_and_ratio_thresholds_is_demand(self):
        self.assertTrue(
            ft.has_unmet_demand(
                {"leechers": 25, "seeders": 10},
                min_leechers=10,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )
        )

    def test_exactly_at_ratio_threshold_is_demand(self):
        self.assertTrue(
            ft.has_unmet_demand(
                {"leechers": 12, "seeders": 10},
                min_leechers=10,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
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
                {"leechers": 10, "seeders": 0},
                min_leechers=10,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )
        )

    def test_zero_seeders_counts_as_demand_when_explicitly_allowed(self):
        self.assertTrue(
            ft.has_unmet_demand(
                {"leechers": 10, "seeders": 0},
                min_leechers=10,
                min_leecher_ratio=1.2,
                allow_zero_seeders=True,
            )
        )

    def test_zero_seeders_still_needs_the_absolute_floor_when_allowed(self):
        self.assertFalse(
            ft.has_unmet_demand(
                {"leechers": 5, "seeders": 0},
                min_leechers=10,
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
        self.assertTrue(
            ft.has_unmet_demand(
                {"leechers": 10, "seeders": 100},
                min_leechers=1,
                min_leecher_ratio=0.1,
                allow_zero_seeders=False,
            )
        )
        self.assertTrue(
            ft.has_unmet_demand(
                {"leechers": 100, "seeders": 1000},
                min_leechers=1,
                min_leecher_ratio=0.1,
                allow_zero_seeders=False,
            )
        )

    def test_extreme_oversupply_still_fails_at_default_ratio(self):
        # 3 leechers on 673 seeders (an actual old Kali release scraped
        # during development) is still not demand, even at the more
        # permissive 0.1 default - it needs at least 67.3 leechers.
        self.assertFalse(
            ft.has_unmet_demand(
                {"leechers": 3, "seeders": 673},
                min_leechers=1,
                min_leecher_ratio=0.1,
                allow_zero_seeders=False,
            )
        )


class EvaluateOldReleaseDemandTests(unittest.TestCase):
    def test_404_is_not_kept_and_not_scraped(self):
        response = helpers.fake_response(status=404)

        with (
            unittest.mock.patch.object(ft.requests, "get", return_value=response),
            unittest.mock.patch.object(
                ft.torrent_scrape, "scrape_torrent"
            ) as mock_scrape,
        ):
            keep, torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                "ubuntu-14.04.6-desktop-amd64.iso",
                "https://example.invalid/x.torrent",
                min_leechers=1,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )

        mock_scrape.assert_not_called()
        self.assertFalse(keep)
        self.assertIsNone(torrent_bytes)
        self.assertIsNone(scrape_result)

    def test_download_failure_is_not_kept(self):
        with unittest.mock.patch.object(
            ft.requests, "get", side_effect=ConnectionError("nope")
        ):
            keep, torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                "ubuntu-14.04.6-desktop-amd64.iso",
                "https://example.invalid/x.torrent",
                min_leechers=1,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )

        self.assertFalse(keep)
        self.assertIsNone(torrent_bytes)
        self.assertIsNone(scrape_result)

    def test_scrape_below_threshold_is_not_kept(self):
        response = helpers.fake_response(b"fake torrent bytes")

        with (
            unittest.mock.patch.object(ft.requests, "get", return_value=response),
            unittest.mock.patch.object(
                ft.torrent_scrape,
                "scrape_torrent",
                return_value={
                    "tracker": "http://t.example/scrape",
                    "seeders": 10,
                    "leechers": 0,
                    "completed": 0,
                },
            ),
        ):
            keep, torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                "ubuntu-14.04.6-desktop-amd64.iso",
                "https://example.invalid/x.torrent",
                min_leechers=1,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )

        self.assertFalse(keep)
        self.assertEqual(torrent_bytes, b"fake torrent bytes")
        self.assertEqual(scrape_result["leechers"], 0)

    def test_scrape_meeting_threshold_is_kept(self):
        response = helpers.fake_response(b"fake torrent bytes")

        with (
            unittest.mock.patch.object(ft.requests, "get", return_value=response),
            unittest.mock.patch.object(
                ft.torrent_scrape,
                "scrape_torrent",
                return_value={
                    "tracker": "http://t.example/scrape",
                    "seeders": 10,
                    "leechers": 30,
                    "completed": 0,
                },
            ),
        ):
            keep, torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                "ubuntu-14.04.6-desktop-amd64.iso",
                "https://example.invalid/x.torrent",
                min_leechers=1,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )

        self.assertTrue(keep)
        self.assertEqual(torrent_bytes, b"fake torrent bytes")
        self.assertEqual(scrape_result["leechers"], 30)

    def test_meets_absolute_floor_but_already_well_seeded_is_not_kept(self):
        response = helpers.fake_response(b"fake torrent bytes")

        # 1 leecher clears a min_leechers=1 floor, but 1000 seeders already
        # cover it - not unmet demand.
        with (
            unittest.mock.patch.object(ft.requests, "get", return_value=response),
            unittest.mock.patch.object(
                ft.torrent_scrape,
                "scrape_torrent",
                return_value={
                    "tracker": "http://t.example/scrape",
                    "seeders": 1000,
                    "leechers": 1,
                    "completed": 0,
                },
            ),
        ):
            keep, _torrent_bytes, scrape_result = ft.evaluate_old_release_demand(
                "ubuntu-14.04.6-desktop-amd64.iso",
                "https://example.invalid/x.torrent",
                min_leechers=1,
                min_leecher_ratio=1.2,
                allow_zero_seeders=False,
            )

        self.assertFalse(keep)
        self.assertEqual(scrape_result["leechers"], 1)


class CheckOldReleasesForDemandTests(unittest.TestCase):
    def setUp(self):
        self.tmp_watch_dir = helpers.make_temp_dir(self, "fetch_torrents_test_watch_")
        patcher = unittest.mock.patch.object(ft, "watch_dir", self.tmp_watch_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_adds_only_torrents_with_unmet_demand(self):
        # Neither name matches LOW_DEMAND_PATTERN - that filtering is
        # covered separately by test_low_demand_variant_is_filtered_before_evaluation.
        candidates = {
            "kali-linux-2026.1-installer-purple-amd64.iso": "https://example.invalid/dead.torrent",
            "kali-linux-2026.1-installer-amd64.iso": "https://example.invalid/alive.torrent",
        }

        def fake_evaluate(
            name, url, min_leechers, min_leecher_ratio, allow_zero_seeders, timeout=15
        ):
            if "purple" in name:
                return (
                    False,
                    b"dead bytes",
                    {"tracker": "t", "seeders": 5, "leechers": 0, "completed": 0},
                )
            return (
                True,
                b"alive bytes",
                {"tracker": "t", "seeders": 5, "leechers": 30, "completed": 0},
            )

        with (
            unittest.mock.patch.dict(
                ft.OLD_RELEASE_DISCOVERY, {"kali": lambda: candidates}, clear=True
            ),
            unittest.mock.patch.object(
                ft, "evaluate_old_release_demand", side_effect=fake_evaluate
            ),
        ):
            added, skipped, _ = ft.check_old_releases_for_demand(
                ["kali"],
                include_low_demand=False,
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=False,
            )

        self.assertEqual(added, 1)
        self.assertEqual(skipped, 1)
        alive_path = os.path.join(
            self.tmp_watch_dir, "kali-linux-2026.1-installer-amd64.iso.torrent"
        )
        dead_path = os.path.join(
            self.tmp_watch_dir, "kali-linux-2026.1-installer-purple-amd64.iso.torrent"
        )
        with open(alive_path, "rb") as f:
            self.assertEqual(f.read(), b"alive bytes")
        self.assertFalse(os.path.exists(dead_path))

    def test_skips_distros_without_old_release_discovery(self):
        with unittest.mock.patch.dict(ft.OLD_RELEASE_DISCOVERY, {}, clear=True):
            added, skipped, _ = ft.check_old_releases_for_demand(
                ["ubuntu"],
                include_low_demand=False,
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=False,
            )

        self.assertEqual((added, skipped), (0, 0))

    def test_already_present_torrent_is_not_re_evaluated(self):
        name = "kali-linux-2026.1-installer-amd64.iso"
        existing_path = os.path.join(self.tmp_watch_dir, f"{name}.torrent")
        with open(existing_path, "wb") as f:
            f.write(b"already here")

        with (
            unittest.mock.patch.dict(
                ft.OLD_RELEASE_DISCOVERY,
                {"kali": lambda: {name: "https://example.invalid/x.torrent"}},
                clear=True,
            ),
            unittest.mock.patch.object(
                ft, "evaluate_old_release_demand"
            ) as mock_evaluate,
        ):
            added, skipped, _ = ft.check_old_releases_for_demand(
                ["kali"],
                include_low_demand=False,
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=False,
            )

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 0))

    def test_unsafe_candidate_name_is_skipped_without_evaluation(self):
        name = "kali-linux-2026.1-installer-../../etc/cron.d/evil"

        with (
            unittest.mock.patch.dict(
                ft.OLD_RELEASE_DISCOVERY,
                {"kali": lambda: {name: "https://example.invalid/x.torrent"}},
                clear=True,
            ),
            unittest.mock.patch.object(
                ft, "evaluate_old_release_demand"
            ) as mock_evaluate,
        ):
            added, skipped, _ = ft.check_old_releases_for_demand(
                ["kali"],
                include_low_demand=False,
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=False,
            )

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 1))

    def test_low_demand_variant_is_filtered_before_evaluation(self):
        name = "kali-linux-2026.1-installer-netinst-amd64.iso"

        with (
            unittest.mock.patch.dict(
                ft.OLD_RELEASE_DISCOVERY,
                {"kali": lambda: {name: "https://example.invalid/x.torrent"}},
                clear=True,
            ),
            unittest.mock.patch.object(
                ft, "evaluate_old_release_demand"
            ) as mock_evaluate,
        ):
            added, skipped, _ = ft.check_old_releases_for_demand(
                ["kali"],
                include_low_demand=False,
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=False,
            )

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 0))


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


class CheckOldReleasesForDemandStateTests(unittest.TestCase):
    """check_old_releases_for_demand() must consult both the recheck-state
    (skip candidates checked too recently) and the removed-history (skip
    candidates cleanup has already given up on) before ever hitting the
    network, and must record a fresh check for anything it does evaluate."""

    def setUp(self):
        self.tmp_watch_dir = helpers.make_temp_dir(self, "fetch_torrents_test_watch_")
        patcher = unittest.mock.patch.object(ft, "watch_dir", self.tmp_watch_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_recently_checked_candidate_is_skipped_without_network_call(self):
        name = "kali-linux-2026.1-installer-amd64.iso"
        candidates = {name: "https://example.invalid/x.torrent"}
        check_state = {name: {"last_checked": "2026-01-05", "leechers": 0}}

        with (
            unittest.mock.patch.dict(
                ft.OLD_RELEASE_DISCOVERY, {"kali": lambda: candidates}, clear=True
            ),
            unittest.mock.patch.object(
                ft, "evaluate_old_release_demand"
            ) as mock_evaluate,
        ):
            added, skipped, new_state = ft.check_old_releases_for_demand(
                ["kali"],
                include_low_demand=False,
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=False,
                check_state=check_state,
                removed_history={},
                today=date(2026, 1, 8),
                recheck_interval_days=7,
            )

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(new_state, check_state)

    def test_previously_removed_candidate_is_skipped_without_network_call(self):
        name = "kali-linux-2026.1-installer-amd64.iso"
        candidates = {name: "https://example.invalid/x.torrent"}
        removed_history = {name: {"removed_date": "2026-01-01", "reason": "stagnant"}}

        with (
            unittest.mock.patch.dict(
                ft.OLD_RELEASE_DISCOVERY, {"kali": lambda: candidates}, clear=True
            ),
            unittest.mock.patch.object(
                ft, "evaluate_old_release_demand"
            ) as mock_evaluate,
        ):
            added, skipped, _new_state = ft.check_old_releases_for_demand(
                ["kali"],
                include_low_demand=False,
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=False,
                check_state={},
                removed_history=removed_history,
                today=date(2026, 1, 8),
                recheck_interval_days=7,
            )

        mock_evaluate.assert_not_called()
        self.assertEqual((added, skipped), (0, 1))

    def test_due_candidate_is_evaluated_and_recorded(self):
        name = "kali-linux-2026.1-installer-amd64.iso"
        candidates = {name: "https://example.invalid/x.torrent"}

        with (
            unittest.mock.patch.dict(
                ft.OLD_RELEASE_DISCOVERY, {"kali": lambda: candidates}, clear=True
            ),
            unittest.mock.patch.object(
                ft,
                "evaluate_old_release_demand",
                return_value=(
                    True,
                    b"bytes",
                    {"tracker": "t", "seeders": 1, "leechers": 30, "completed": 0},
                ),
            ),
        ):
            added, skipped, new_state = ft.check_old_releases_for_demand(
                ["kali"],
                include_low_demand=False,
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=False,
                check_state={},
                removed_history={},
                today=date(2026, 1, 8),
                recheck_interval_days=7,
            )

        self.assertEqual((added, skipped), (1, 0))
        self.assertEqual(
            new_state[name], {"last_checked": "2026-01-08", "leechers": 30}
        )

    def test_no_demand_result_is_still_recorded_for_future_recheck_gating(self):
        name = "kali-linux-2026.1-installer-arm64.iso"
        candidates = {name: "https://example.invalid/x.torrent"}

        with (
            unittest.mock.patch.dict(
                ft.OLD_RELEASE_DISCOVERY, {"kali": lambda: candidates}, clear=True
            ),
            unittest.mock.patch.object(
                ft,
                "evaluate_old_release_demand",
                return_value=(
                    False,
                    b"bytes",
                    {"tracker": "t", "seeders": 1, "leechers": 0, "completed": 0},
                ),
            ),
        ):
            added, skipped, new_state = ft.check_old_releases_for_demand(
                ["kali"],
                include_low_demand=False,
                min_leechers=1,
                min_leecher_ratio=0.0,
                allow_zero_seeders=False,
                check_state={},
                removed_history={},
                today=date(2026, 1, 8),
                recheck_interval_days=7,
            )

        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(new_state[name], {"last_checked": "2026-01-08", "leechers": 0})


if __name__ == "__main__":
    unittest.main()
