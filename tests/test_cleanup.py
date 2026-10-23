"""Tests for cleanup: the pure planners (plan_cleanup(),
plan_stagnation_cleanup(), plan_disk_pressure_cleanup(),
update_ratio_history()) and the functions that apply them to a
Transmission client (helpers.FakeTransmission).

Run with: python -m unittest discover -s tests
"""

import json
import os
import types
import unittest
import unittest.mock
from datetime import UTC, date, timedelta

import helpers

import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


class PlanCleanupTests(unittest.TestCase):
    # (group, newer, older): one (distro, type) group per row.
    VERSION_PAIRS = (
        (
            "ubuntu desktop",
            "ubuntu-24.04-desktop-amd64.iso",
            "ubuntu-23.10-desktop-amd64.iso",
        ),
        (
            "ubuntu live-server",
            "ubuntu-24.04.1-live-server-amd64.iso",
            "ubuntu-22.04.1-live-server-amd64.iso",
        ),
        ("debian", "debian-12.5.0-amd64-DVD-1.iso", "debian-12.4.0-amd64-DVD-1.iso"),
        (
            "kali",
            "kali-linux-2024.1-installer-amd64.iso",
            "kali-linux-2023.4-installer-amd64.iso",
        ),
        ("arch", "archlinux-2024.05.01-x86_64.iso", "archlinux-2024.04.01-x86_64.iso"),
        (
            "mint",
            "linuxmint-22.3-cinnamon-64bit.iso",
            "linuxmint-22.2-cinnamon-64bit.iso",
        ),
        (
            "fedora",
            "Fedora-Workstation-Live-x86_64-44",
            "Fedora-Workstation-Live-x86_64-43",
        ),
    )

    def test_selects_older_version_per_distro_and_type(self):
        for group, newer, older in self.VERSION_PAIRS:
            with self.subTest(group):
                to_remove, to_keep_low_ratio = ft.plan_cleanup(
                    [
                        helpers.FakeTorrent(newer, 1, ratio=2.0),
                        helpers.FakeTorrent(older, 2, ratio=2.0),
                    ]
                )

                self.assertEqual(helpers.names_of(to_remove), [older])
                self.assertEqual(to_keep_low_ratio, [])

    def test_groups_planned_together_do_not_affect_each_other(self):
        torrents = []
        for _group, newer, older in self.VERSION_PAIRS:
            torrents.append(helpers.FakeTorrent(newer, len(torrents), ratio=2.0))
            torrents.append(helpers.FakeTorrent(older, len(torrents), ratio=2.0))

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(
            helpers.names_of(to_remove),
            sorted(older for _group, _newer, older in self.VERSION_PAIRS),
        )
        self.assertEqual(to_keep_low_ratio, [])

    def test_single_torrent_per_group_is_left_alone(self):
        torrents = [helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=0.0)]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep_low_ratio, [])

    def test_unrelated_torrents_are_ignored(self):
        torrents = [
            helpers.FakeTorrent("some-random-linux-distro-1.0.iso", 1, ratio=5.0),
            helpers.FakeTorrent("some-random-linux-distro-2.0.iso", 2, ratio=5.0),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep_low_ratio, [])

    def test_skip_ratio_check_removes_regardless_of_ratio(self):
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.0),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(
            torrents, skip_ratio_check=True, min_ratio=1.0
        )

        self.assertEqual(
            helpers.names_of(to_remove), ["ubuntu-23.10-desktop-amd64.iso"]
        )
        self.assertEqual(to_keep_low_ratio, [])

    def test_different_types_within_same_distro_are_not_cross_removed(self):
        # desktop and live-server are different "type_" groups for ubuntu;
        # having only the desktop build twice must not affect live-server.
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=2.0),
            helpers.FakeTorrent("ubuntu-24.04.1-live-server-amd64.iso", 3, ratio=2.0),
        ]

        to_remove, _ = ft.plan_cleanup(torrents)

        self.assertEqual(
            helpers.names_of(to_remove), ["ubuntu-23.10-desktop-amd64.iso"]
        )

    def test_unparseable_name_for_matched_distro_is_skipped_not_raised(self):
        # "ubuntu-desktop" has no version segment at index 1 that parses as
        # a version; parse_version_type/version_to_tuple should fail and
        # plan_cleanup must skip it rather than raising.
        torrents = [
            helpers.FakeTorrent("ubuntu-desktop", 1, ratio=2.0),
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 2, ratio=2.0),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep_low_ratio, [])

    def test_ratio_exactly_at_min_ratio_is_removed(self):
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.0),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents, min_ratio=1.0)

        self.assertEqual(
            helpers.names_of(to_remove), ["ubuntu-23.10-desktop-amd64.iso"]
        )
        self.assertEqual(to_keep_low_ratio, [])

    def test_ratio_just_below_min_ratio_is_kept(self):
        older = helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.999)
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            older,
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents, min_ratio=1.0)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep_low_ratio, [(older, 0.999)])

    def test_default_min_ratio_is_one(self):
        older = helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.5)
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            older,
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [older])
        self.assertEqual(to_keep_low_ratio, [])

    def test_missing_or_none_ratio_counts_as_zero(self):
        no_attr = types.SimpleNamespace(name="ubuntu-23.04-desktop-amd64.iso", id=2)
        none_ratio = helpers.DuckTorrent(
            "ubuntu-23.10-desktop-amd64.iso", 3, ratio=None
        )
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            no_attr,
            none_ratio,
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents, min_ratio=1.0)

        self.assertEqual(to_remove, [])
        self.assertEqual(
            sorted(to_keep_low_ratio, key=lambda entry: entry[0].name),
            [(no_attr, 0.0), (none_ratio, 0.0)],
        )

    def test_skipped_torrents_listed_first_do_not_stop_planning(self):
        # Each kind of torrent _old_version_candidates() skips (or routes
        # elsewhere) is placed *before* a valid pair, so a 'continue' that
        # became 'break' would drop the pair.
        leading = {
            "devuan": helpers.FakeTorrent(
                "devuan_excalibur", 10, ratio=2.0, added_date=1
            ),
            "unknown distro": helpers.FakeTorrent("slackware-15.0-install-dvd.iso", 11),
            "unparseable": helpers.FakeTorrent("ubuntu-noble-desktop-amd64.iso", 12),
        }
        for kind, first in leading.items():
            with self.subTest(kind):
                older = helpers.FakeTorrent(
                    "ubuntu-23.10-desktop-amd64.iso", 2, ratio=2.0
                )
                torrents = [
                    first,
                    helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
                    older,
                ]

                with self.assertNoLogs(ft.logger, level="ERROR"):
                    to_remove, _ = ft.plan_cleanup(torrents)

                self.assertEqual(to_remove, [older])

    def test_unparseable_name_is_skipped_with_a_warning(self):
        torrents = [
            helpers.FakeTorrent("ubuntu-noble-desktop-amd64.iso", 1, ratio=2.0),
            helpers.FakeTorrent("ubuntu-mantic-desktop-amd64.iso", 2, ratio=2.0),
        ]

        with self.assertLogs(ft.logger, level="WARNING") as logs:
            to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual((to_remove, to_keep_low_ratio), ([], []))
        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                (
                    "Skipping ubuntu-noble-desktop-amd64.iso during cleanup due to "
                    "parse error: Invalid version string 'noble'"
                ),
                (
                    "Skipping ubuntu-mantic-desktop-amd64.iso during cleanup due to "
                    "parse error: Invalid version string 'mantic'"
                ),
            ],
        )


class PlanCleanupDevuanGroupingTests(unittest.TestCase):
    """Devuan releases (e.g. "devuan_excalibur") carry no dotted version to
    compare - see DEVUAN_NAME_PATTERN - so _old_version_candidates() groups
    them separately and orders by added_date (when Transmission added the
    torrent) instead of a parsed version, same idea as should_fetch_torrent()'s
    ratio gate for Devuan."""

    def test_older_devuan_release_is_a_cleanup_candidate(self):
        torrents = [
            helpers.FakeTorrent("devuan_daedalus", 1, ratio=2.0, added_date=1000),
            helpers.FakeTorrent("devuan_excalibur", 2, ratio=2.0, added_date=2000),
        ]

        to_remove, _ = ft.plan_cleanup(torrents)

        self.assertEqual(helpers.names_of(to_remove), ["devuan_daedalus"])

    def test_single_devuan_release_is_left_alone(self):
        torrents = [
            helpers.FakeTorrent("devuan_excalibur", 1, ratio=0.0, added_date=1000)
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep_low_ratio, [])

    def test_older_devuan_release_below_ratio_threshold_is_kept(self):
        torrents = [
            helpers.FakeTorrent("devuan_daedalus", 1, ratio=0.4, added_date=1000),
            helpers.FakeTorrent("devuan_excalibur", 2, ratio=2.0, added_date=2000),
        ]

        to_remove, to_keep_low_ratio = ft.plan_cleanup(torrents, min_ratio=1.0)

        self.assertEqual(to_remove, [])
        self.assertEqual(len(to_keep_low_ratio), 1)
        kept_torrent, kept_ratio = to_keep_low_ratio[0]
        self.assertEqual(kept_torrent.name, "devuan_daedalus")
        self.assertEqual(kept_ratio, 0.4)

    def test_stagnant_older_devuan_release_is_removed(self):
        today = date(2026, 8, 29)
        torrents = [
            helpers.FakeTorrent("devuan_daedalus", 1, ratio=1.5, added_date=1000),
            helpers.FakeTorrent("devuan_excalibur", 2, ratio=2.0, added_date=2000),
        ]
        history = {"devuan_daedalus": [{"date": "2026-07-20", "ratio": 1.495}]}

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, history, today, window_days=30, min_ratio_delta=0.02
        )

        self.assertEqual(helpers.names_of(to_remove), ["devuan_daedalus"])
        self.assertEqual(to_keep, [])

    def test_missing_added_date_does_not_crash(self):
        # Real Transmission torrents always carry added_date; this just
        # guards _devuan_sort_key() against a hypothetical missing attribute.
        torrents = [
            helpers.DuckTorrent("devuan_daedalus", 1, ratio=2.0, added_date=None),
            helpers.DuckTorrent("devuan_excalibur", 2, ratio=2.0, added_date=None),
        ]

        to_remove, _ = ft.plan_cleanup(torrents)

        # Tied (missing) dates: the stable sort keeps the first one listed as
        # the current release, so only the other is a candidate.
        self.assertEqual(helpers.names_of(to_remove), ["devuan_excalibur"])

    def test_release_without_added_date_sorts_as_oldest(self):
        undated = helpers.DuckTorrent("devuan_daedalus", 1, ratio=2.0, added_date=None)
        torrents = [
            undated,
            helpers.DuckTorrent("devuan_excalibur", 2, ratio=2.0, added_date=0.5),
        ]

        to_remove, _ = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [undated])

    def test_datetime_added_dates_are_ordered_by_timestamp(self):
        from datetime import datetime

        older = helpers.DuckTorrent(
            "devuan_daedalus",
            1,
            ratio=2.0,
            added_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        torrents = [
            helpers.DuckTorrent(
                "devuan_excalibur",
                2,
                ratio=2.0,
                added_date=datetime(2026, 6, 1, tzinfo=UTC),
            ),
            older,
        ]

        to_remove, _ = ft.plan_cleanup(torrents)

        self.assertEqual(to_remove, [older])


class UpdateRatioHistoryTests(unittest.TestCase):
    """update_ratio_history() must keep the on-disk history bounded: drop
    torrents that are no longer seeding, only add a new sample once per
    sample_interval_days, and prune samples once they're older than
    window_days + sample_interval_days - so it stays a fixed handful of
    samples per torrent forever, not one entry per run."""

    def test_new_torrent_gets_a_first_sample(self):
        today = date(2026, 8, 29)
        history = ft.update_ratio_history(
            {}, {"archlinux-2026.08.01-x86_64.iso": 1.2}, today
        )

        self.assertEqual(
            history,
            {"archlinux-2026.08.01-x86_64.iso": [{"date": "2026-08-29", "ratio": 1.2}]},
        )

    def test_torrent_no_longer_seeding_is_dropped(self):
        today = date(2026, 8, 29)
        history = {
            "archlinux-2026.07.01-x86_64.iso": [{"date": "2026-08-20", "ratio": 1.0}],
        }

        updated = ft.update_ratio_history(history, {}, today)

        self.assertEqual(updated, {})

    def _days_ago(self, today, days):
        return (today - timedelta(days=days)).isoformat()

    def test_sample_exactly_one_interval_old_triggers_a_new_sample(self):
        today = date(2026, 8, 29)
        history = {"a.iso": [{"date": self._days_ago(today, 7), "ratio": 1.0}]}

        updated = ft.update_ratio_history(
            history, {"a.iso": 1.2}, today, sample_interval_days=7, window_days=30
        )

        self.assertEqual(
            updated["a.iso"],
            [
                {"date": self._days_ago(today, 7), "ratio": 1.0},
                {"date": today.isoformat(), "ratio": 1.2},
            ],
        )

    def test_sample_just_under_one_interval_old_adds_nothing(self):
        today = date(2026, 8, 29)
        history = {"a.iso": [{"date": self._days_ago(today, 6), "ratio": 1.0}]}

        updated = ft.update_ratio_history(
            history, {"a.iso": 1.2}, today, sample_interval_days=7, window_days=30
        )

        self.assertEqual(
            updated["a.iso"], [{"date": self._days_ago(today, 6), "ratio": 1.0}]
        )

    def test_prune_horizon_defaults_to_window_plus_interval(self):
        # Defaults: window 30 + interval 7 = 37 days. A sample exactly 37
        # days old is kept; 38 days old is pruned.
        today = date(2026, 8, 29)
        history = {
            "a.iso": [
                {"date": self._days_ago(today, 38), "ratio": 0.5},
                {"date": self._days_ago(today, 37), "ratio": 0.6},
                {"date": self._days_ago(today, 1), "ratio": 0.9},
            ]
        }

        updated = ft.update_ratio_history(history, {"a.iso": 1.0}, today)

        self.assertEqual(
            updated["a.iso"],
            [
                {"date": self._days_ago(today, 37), "ratio": 0.6},
                {"date": self._days_ago(today, 1), "ratio": 0.9},
            ],
        )


class PlanStagnationCleanupTests(unittest.TestCase):
    """plan_stagnation_cleanup() removes only superseded (non-latest)
    versions within a (distro, type) group once their ratio has stopped
    growing - the newest/only version of a group is never a candidate,
    since removing it would just get it re-fetched and re-downloaded the
    next run (should_fetch_torrent() only skips a fetch when a *previous*
    version's ratio is on record)."""

    def test_latest_or_only_version_is_never_removed_even_if_flat(self):
        today = date(2026, 8, 29)
        torrents = [
            helpers.FakeTorrent("archlinux-2026.08.01-x86_64.iso", 1, ratio=1.0)
        ]
        # 60 days of a perfectly flat ratio - as stagnant as it gets.
        history = {
            "archlinux-2026.08.01-x86_64.iso": [{"date": "2026-06-30", "ratio": 1.0}],
        }

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, history, today, window_days=30, min_ratio_delta=0.02
        )

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep, [])

    def test_unrelated_single_torrent_groups_are_ignored(self):
        today = date(2026, 8, 29)
        torrents = [
            helpers.FakeTorrent("some-random-linux-distro-1.0.iso", 1, ratio=5.0)
        ]

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, {}, today, window_days=30, min_ratio_delta=0.02
        )

        self.assertEqual(to_remove, [])
        self.assertEqual(to_keep, [])

    def _pair(self, older_ratio):
        older = helpers.FakeTorrent(
            "ubuntu-23.10-desktop-amd64.iso", 2, ratio=older_ratio
        )
        return older, [helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1), older]

    def _history(self, today, *samples):
        return {
            "ubuntu-23.10-desktop-amd64.iso": [
                {"date": (today - timedelta(days=days)).isoformat(), "ratio": ratio}
                for days, ratio in samples
            ]
        }

    def test_anchor_exactly_window_days_old_is_used(self):
        today = date(2026, 8, 29)
        older, torrents = self._pair(1.0)

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, self._history(today, (30, 1.0)), today, 30, 0.02
        )

        self.assertEqual((to_remove, to_keep), ([older], []))

    def test_anchor_one_day_short_of_window_is_too_new_to_judge(self):
        today = date(2026, 8, 29)
        older, torrents = self._pair(1.0)

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, self._history(today, (29, 1.0)), today, 30, 0.02
        )

        self.assertEqual((to_remove, to_keep), ([], [(older, None)]))

    def test_oldest_qualifying_sample_is_the_anchor(self):
        # Listed newest-first, so picking the first old-enough sample
        # instead of the oldest would give a different delta.
        today = date(2026, 8, 29)
        older, torrents = self._pair(1.0)
        history = self._history(today, (35, 0.99), (45, 0.5))

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, history, today, 30, 0.02
        )

        self.assertEqual((to_remove, to_keep), ([], [(older, 0.5)]))

    def test_delta_exactly_at_min_ratio_delta_is_kept(self):
        today = date(2026, 8, 29)
        older, torrents = self._pair(1.5)

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, self._history(today, (40, 1.0)), today, 30, 0.5
        )

        self.assertEqual((to_remove, to_keep), ([], [(older, 0.5)]))

    def test_delta_just_below_min_ratio_delta_is_removed(self):
        today = date(2026, 8, 29)
        older, torrents = self._pair(1.25)

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, self._history(today, (40, 1.0)), today, 30, 0.5
        )

        self.assertEqual((to_remove, to_keep), ([older], []))

    def test_defaults_are_a_30_day_window_and_0_02_delta(self):
        today = date(2026, 8, 29)
        growing, torrents = self._pair(1.5)

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, self._history(today, (30, 1.0)), today
        )

        self.assertEqual((to_remove, to_keep), ([], [(growing, 0.5)]))

        stagnant, torrents = self._pair(1.01)
        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, self._history(today, (30, 1.0)), today
        )

        self.assertEqual((to_remove, to_keep), ([stagnant], []))

    def test_missing_or_none_ratio_counts_as_zero(self):
        today = date(2026, 8, 29)
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1),
            types.SimpleNamespace(name="ubuntu-23.04-desktop-amd64.iso", id=2),
            helpers.DuckTorrent("ubuntu-23.10-desktop-amd64.iso", 3, ratio=None),
        ]
        history = {
            name: [{"date": (today - timedelta(days=40)).isoformat(), "ratio": -0.5}]
            for name in (
                "ubuntu-23.04-desktop-amd64.iso",
                "ubuntu-23.10-desktop-amd64.iso",
            )
        }

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, history, today, 30, 0.02
        )

        self.assertEqual(to_remove, [])
        self.assertEqual(
            sorted((t.name, delta) for t, delta in to_keep),
            [
                ("ubuntu-23.04-desktop-amd64.iso", 0.5),
                ("ubuntu-23.10-desktop-amd64.iso", 0.5),
            ],
        )

    def test_candidate_without_anchor_does_not_stop_later_ones(self):
        today = date(2026, 8, 29)
        no_history = helpers.FakeTorrent("ubuntu-23.04-desktop-amd64.iso", 3, ratio=1.0)
        stagnant = helpers.FakeTorrent("ubuntu-22.10-desktop-amd64.iso", 4, ratio=1.0)
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1),
            no_history,
            stagnant,
        ]
        history = {
            "ubuntu-22.10-desktop-amd64.iso": [
                {"date": (today - timedelta(days=40)).isoformat(), "ratio": 1.0}
            ]
        }

        to_remove, to_keep = ft.plan_stagnation_cleanup(
            torrents, history, today, 30, 0.02
        )

        self.assertEqual((to_remove, to_keep), ([stagnant], [(no_history, None)]))


class RecordRemovalTests(unittest.TestCase):
    def test_adds_entry_without_mutating_input(self):
        history = {}
        updated = ft.record_removal(
            history,
            "kali-linux-2026.1-installer-amd64.iso",
            date(2026, 2, 1),
            "stagnant",
            0.42,
        )

        self.assertEqual(history, {})  # input untouched
        self.assertEqual(
            updated["kali-linux-2026.1-installer-amd64.iso"],
            {"removed_date": "2026-02-01", "reason": "stagnant", "ratio": 0.42},
        )


class CleanupRemovesWatchFileTests(unittest.TestCase):
    """When cleanup removes a torrent's downloaded data, it must also remove
    the small .torrent file it left behind in /watch - otherwise these
    accumulate forever, since nothing else (including Transmission itself,
    by default) ever cleans them up."""

    def setUp(self):
        helpers.use_state_files(self)
        self.tmp_watch_dir = helpers.use_watch_dir(self)

    def _touch_watch_file(self, name, suffix=".torrent"):
        path = os.path.join(self.tmp_watch_dir, f"{name}{suffix}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("fake torrent bytes")
        return path

    def _transmission(self):
        return helpers.FakeTransmission(
            [
                helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
                helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=2.0),
            ]
        )

    def test_cleanup_old_versions_removes_the_watch_file(self):
        old_path = self._touch_watch_file("ubuntu-23.10-desktop-amd64.iso")
        new_path = self._touch_watch_file("ubuntu-24.04-desktop-amd64.iso")
        transmission = self._transmission()

        ft.cleanup_old_versions(
            transmission, today=date(2026, 8, 1), skip_ratio_check=True
        )

        self.assertEqual(transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])
        self.assertIn(("remove_torrent", 2, True), transmission.calls)
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(new_path))
        self.assertEqual(
            ft.load_removed_history(ft.removed_history_file),
            {
                "ubuntu-23.10-desktop-amd64.iso": {
                    "removed_date": "2026-08-01",
                    "reason": "keep_only_latest",
                    "ratio": 2.0,
                }
            },
        )

    def test_cleanup_old_versions_removes_the_added_watch_file(self):
        # transmission-daemon renames a loaded watch file to .torrent.added.
        old_path = self._touch_watch_file(
            "ubuntu-23.10-desktop-amd64.iso", ".torrent.added"
        )
        new_path = self._touch_watch_file(
            "ubuntu-24.04-desktop-amd64.iso", ".torrent.added"
        )

        ft.cleanup_old_versions(
            self._transmission(), today=date(2026, 8, 1), skip_ratio_check=True
        )

        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(new_path))

    def test_missing_watch_file_does_not_raise(self):
        # No .torrent file created for the superseded version - cleanup must
        # still succeed and remove the torrent from Transmission.
        transmission = self._transmission()

        ft.cleanup_old_versions(
            transmission, today=date(2026, 8, 1), skip_ratio_check=True
        )

        self.assertEqual(transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])

    def test_unremovable_watch_file_is_reported_and_cleanup_carries_on(self):
        # A directory under the .torrent file's name can't be os.remove()d.
        old_path = os.path.join(
            self.tmp_watch_dir, "ubuntu-23.10-desktop-amd64.iso.torrent"
        )
        os.mkdir(old_path)
        transmission = self._transmission()

        with self.assertLogs(ft.logger, level="WARNING") as logs:
            ft.cleanup_old_versions(
                transmission, today=date(2026, 8, 1), skip_ratio_check=True
            )

        self.assertEqual(transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])
        self.assertIn(
            "ubuntu-23.10-desktop-amd64.iso",
            ft.load_removed_history(ft.removed_history_file),
        )
        self.assertTrue(os.path.isdir(old_path))
        self.assertEqual(
            [
                r.getMessage().split(": ")[0]
                for r in logs.records
                if r.getMessage().startswith("Could not remove")
            ],
            ["Could not remove watch-folder file for ubuntu-23.10-desktop-amd64.iso"],
        )

    def test_cleanup_old_versions_keeps_versions_below_min_ratio(self):
        transmission = helpers.FakeTransmission(
            [
                helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
                helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.5),
            ]
        )

        ft.cleanup_old_versions(transmission, today=date(2026, 8, 1), min_ratio=2.0)

        self.assertEqual(
            transmission.names,
            ["ubuntu-23.10-desktop-amd64.iso", "ubuntu-24.04-desktop-amd64.iso"],
        )
        self.assertEqual(transmission.removals, [])

    def test_cleanup_stagnant_torrents_removes_the_watch_file(self):
        old_path = self._touch_watch_file("ubuntu-23.10-desktop-amd64.iso")
        self._touch_watch_file("ubuntu-24.04-desktop-amd64.iso")
        transmission = self._transmission()

        # 32 days old: past the default 30-day stagnation window, but still
        # within update_ratio_history()'s own 37-day (window + sample
        # interval) prune horizon, since that prune runs - on this same
        # history - before plan_stagnation_cleanup() ever sees it. Ratio
        # unchanged since then, so plan_stagnation_cleanup() must select this
        # torrent for removal.
        today = date(2026, 8, 1)
        anchor_date = (today - timedelta(days=32)).isoformat()
        history = {
            "ubuntu-23.10-desktop-amd64.iso": [{"date": anchor_date, "ratio": 2.0}]
        }
        with open(ft.ratio_history_file, "w", encoding="utf-8") as f:
            json.dump(history, f)

        ft.cleanup_stagnant_torrents(transmission, today=today)

        self.assertEqual(transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])
        self.assertFalse(os.path.exists(old_path))
        removed = ft.load_removed_history(ft.removed_history_file)
        self.assertEqual(
            removed["ubuntu-23.10-desktop-amd64.iso"],
            {"removed_date": "2026-08-01", "reason": "stagnant", "ratio": 2.0},
        )

    def _write_ratio_history(self, history):
        with open(ft.ratio_history_file, "w", encoding="utf-8") as f:
            json.dump(history, f)

    def test_cleanup_stagnant_torrents_deletes_the_downloaded_data(self):
        today = date(2026, 8, 1)
        self._write_ratio_history(
            {
                "ubuntu-23.10-desktop-amd64.iso": [
                    {"date": (today - timedelta(days=32)).isoformat(), "ratio": 2.0}
                ]
            }
        )
        transmission = self._transmission()

        ft.cleanup_stagnant_torrents(transmission, today=today)

        self.assertEqual(transmission.removals, [(2, True)])

    def test_cleanup_stagnant_torrents_judges_over_a_30_day_window_by_default(self):
        # Exactly 30 days of flat ratio: stagnant under the default window,
        # though a day short of it under any longer one.
        today = date(2026, 8, 1)
        self._write_ratio_history(
            {
                "ubuntu-23.10-desktop-amd64.iso": [
                    {"date": (today - timedelta(days=30)).isoformat(), "ratio": 2.0}
                ]
            }
        )
        transmission = self._transmission()

        ft.cleanup_stagnant_torrents(transmission, today=today)

        self.assertEqual(transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])

    def test_cleanup_stagnant_torrents_keeps_growth_above_the_default_delta(self):
        # Ratio grew 0.5 over the window: well above the 0.02 default.
        today = date(2026, 8, 1)
        self._write_ratio_history(
            {
                "ubuntu-23.10-desktop-amd64.iso": [
                    {"date": (today - timedelta(days=32)).isoformat(), "ratio": 1.5}
                ]
            }
        )
        transmission = self._transmission()

        with self.assertLogs(ft.logger, level="INFO") as logs:
            ft.cleanup_stagnant_torrents(transmission, today=today)

        self.assertEqual(
            transmission.names,
            ["ubuntu-23.10-desktop-amd64.iso", "ubuntu-24.04-desktop-amd64.iso"],
        )
        self.assertEqual(transmission.removals, [])
        self.assertIn(
            "Keeping old version ubuntu-23.10-desktop-amd64.iso – ratio grew by "
            "0.500 over the last 30 days.",
            [r.getMessage() for r in logs.records],
        )

    def test_cleanup_stagnant_torrents_honours_custom_window_and_delta(self):
        # window_days=10, min_ratio_delta=0.5. 23.10 grew 0.6 in 12 days
        # (kept); 22.04 grew 0.3 (removed). Swapping the two settings would
        # remove both. The 20-day-old 23.10 sample is past the 10 + 7 day
        # prune horizon, so it must be dropped from the saved history.
        today = date(2026, 8, 1)

        def days_ago(n):
            return (today - timedelta(days=n)).isoformat()

        self._write_ratio_history(
            {
                "ubuntu-23.10-desktop-amd64.iso": [
                    {"date": days_ago(20), "ratio": 0.9},
                    {"date": days_ago(12), "ratio": 1.0},
                ],
                "ubuntu-22.04-desktop-amd64.iso": [
                    {"date": days_ago(12), "ratio": 1.0}
                ],
            }
        )
        transmission = helpers.FakeTransmission(
            [
                helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
                helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.6),
                helpers.FakeTorrent("ubuntu-22.04-desktop-amd64.iso", 3, ratio=1.3),
            ]
        )

        with self.assertLogs(ft.logger, level="INFO") as logs:
            ft.cleanup_stagnant_torrents(
                transmission, today=today, window_days=10, min_ratio_delta=0.5
            )

        self.assertEqual(
            transmission.names,
            ["ubuntu-23.10-desktop-amd64.iso", "ubuntu-24.04-desktop-amd64.iso"],
        )
        self.assertIn(
            "Removing stagnant torrent: ubuntu-22.04-desktop-amd64.iso "
            "(no meaningful ratio growth in 10 days)",
            [r.getMessage() for r in logs.records],
        )
        self.assertEqual(
            ft.load_ratio_history(ft.ratio_history_file)[
                "ubuntu-23.10-desktop-amd64.iso"
            ],
            [
                {"date": days_ago(12), "ratio": 1.0},
                {"date": "2026-08-01", "ratio": 1.6},
            ],
        )

    def test_cleanup_stagnant_torrents_records_a_zero_ratio_as_zero(self):
        transmission = helpers.FakeTransmission(
            [helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=0.0)]
        )

        ft.cleanup_stagnant_torrents(transmission, today=date(2026, 8, 1))

        self.assertEqual(
            ft.load_ratio_history(ft.ratio_history_file),
            {"ubuntu-24.04-desktop-amd64.iso": [{"date": "2026-08-01", "ratio": 0.0}]},
        )

    def test_cleanup_stagnant_torrents_records_todays_sample(self):
        transmission = self._transmission()

        ft.cleanup_stagnant_torrents(
            transmission, today=date(2026, 8, 1), window_days=10
        )

        self.assertEqual(
            ft.load_ratio_history(ft.ratio_history_file),
            {
                "ubuntu-24.04-desktop-amd64.iso": [
                    {"date": "2026-08-01", "ratio": 2.0}
                ],
                "ubuntu-23.10-desktop-amd64.iso": [
                    {"date": "2026-08-01", "ratio": 2.0}
                ],
            },
        )


class PlanDiskPressureCleanupTests(unittest.TestCase):
    """plan_disk_pressure_cleanup() is the pure selection logic behind
    CLEANUP_DISK_USAGE_THRESHOLD_PERCENT - the safety valve that kicks in
    when normal ratio/stagnation-based cleanup isn't freeing space fast
    enough for a forgotten, never-updated deployment."""

    def test_below_threshold_returns_nothing(self):
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.1),
        ]
        self.assertEqual(
            ft.plan_disk_pressure_cleanup(
                torrents, used_percent=80.0, threshold_percent=95.0
            ),
            [],
        )

    def test_disabled_when_threshold_is_zero_or_negative(self):
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
            helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.1),
        ]
        self.assertEqual(
            ft.plan_disk_pressure_cleanup(
                torrents, used_percent=99.0, threshold_percent=0
            ),
            [],
        )
        self.assertEqual(
            ft.plan_disk_pressure_cleanup(
                torrents, used_percent=99.0, threshold_percent=-1
            ),
            [],
        )

    def test_at_or_above_threshold_returns_candidates_lowest_ratio_first(self):
        torrents = [
            helpers.FakeTorrent(
                "ubuntu-24.04-desktop-amd64.iso", 1, ratio=5.0
            ),  # latest - never a candidate
            helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.5),
            helpers.FakeTorrent("ubuntu-22.04.1-live-server-amd64.iso", 3, ratio=0.2),
            helpers.FakeTorrent(
                "ubuntu-24.04.1-live-server-amd64.iso", 4, ratio=5.0
            ),  # latest of this group
        ]
        result = ft.plan_disk_pressure_cleanup(
            torrents, used_percent=95.0, threshold_percent=95.0
        )
        self.assertEqual(
            helpers.names_of(result),
            ["ubuntu-22.04.1-live-server-amd64.iso", "ubuntu-23.10-desktop-amd64.iso"],
        )
        # lowest ratio (least useful) first
        self.assertEqual(result[0].name, "ubuntu-22.04.1-live-server-amd64.iso")

    def test_no_superseded_candidates_returns_empty(self):
        torrents = [helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=0.0)]
        self.assertEqual(
            ft.plan_disk_pressure_cleanup(
                torrents, used_percent=99.0, threshold_percent=95.0
            ),
            [],
        )

    def test_any_positive_threshold_is_enabled(self):
        older = helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=0.1)
        torrents = [helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1), older]

        self.assertEqual(
            ft.plan_disk_pressure_cleanup(
                torrents, used_percent=50.0, threshold_percent=1
            ),
            [older],
        )

    def test_missing_or_none_ratio_sorts_as_zero(self):
        half = helpers.FakeTorrent("ubuntu-22.10-desktop-amd64.iso", 2, ratio=0.5)
        no_attr = types.SimpleNamespace(name="ubuntu-23.04-desktop-amd64.iso", id=3)
        none_ratio = helpers.DuckTorrent(
            "ubuntu-23.10-desktop-amd64.iso", 4, ratio=None
        )
        torrents = [
            helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1),
            half,
            no_attr,
            none_ratio,
        ]

        planned = ft.plan_disk_pressure_cleanup(
            torrents, used_percent=99.0, threshold_percent=95.0
        )

        self.assertEqual(planned[-1], half)
        self.assertEqual(
            sorted(t.name for t in planned[:2]),
            ["ubuntu-23.04-desktop-amd64.iso", "ubuntu-23.10-desktop-amd64.iso"],
        )


class EnforceDiskUsageLimitTests(unittest.TestCase):
    """enforce_disk_usage_limit() wires plan_disk_pressure_cleanup() to a
    Transmission connection and real disk usage, re-checking usage between
    removals since ratio data alone can't say how many bytes each torrent
    holds."""

    def setUp(self):
        helpers.use_state_files(self)
        self.tmp_watch_dir = helpers.use_watch_dir(self)

        self.transmission = helpers.FakeTransmission(
            [
                helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=5.0),
                helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2, ratio=1.5),
                helpers.FakeTorrent("ubuntu-22.04-desktop-amd64.iso", 3, ratio=0.2),
            ]
        )
        self.connections = 0

    def _connect(self):
        self.connections += 1
        return self.transmission

    def _disk(self, base_used, sizes=None):
        # 100 GB disk; each torrent's size in GB.
        return helpers.FakeDisk(
            self.transmission, 100, sizes or {1: 2, 2: 2, 3: 6}, base_used
        )

    def _enforce(self, threshold, disk):
        ft.enforce_disk_usage_limit(
            self._connect,
            threshold,
            today=date(2026, 8, 1),
            disk_usage=disk,
            download_path="/downloads",
        )

    def test_disabled_threshold_never_touches_disk_or_rpc(self):
        disk = self._disk(base_used=99)

        self._enforce(0, disk)

        self.assertEqual((disk.paths, self.connections), ([], 0))

    def test_keeps_removing_while_still_over_threshold(self):
        # 96%; removing 22.04 (1 GB) leaves 95% - still at the threshold -
        # so 23.10 (4 GB) goes too.
        disk = self._disk(base_used=90, sizes={1: 1, 2: 4, 3: 1})

        self._enforce(95, disk)

        self.assertEqual(self.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])

    def test_removal_deletes_the_downloaded_data(self):
        self._enforce(95, self._disk(base_used=86))

        self.assertEqual(self.transmission.removals, [(3, True)])

    def test_usage_exactly_at_threshold_triggers_cleanup(self):
        # 85 + 10 = 95% used: at the threshold counts as exceeded.
        disk = self._disk(base_used=85)

        self._enforce(95, disk)

        self.assertEqual(
            self.transmission.names,
            ["ubuntu-23.10-desktop-amd64.iso", "ubuntu-24.04-desktop-amd64.iso"],
        )

    def test_usage_just_below_threshold_does_not_connect(self):
        disk = self._disk(base_used=84.5)  # 94.5%

        self._enforce(95, disk)

        self.assertEqual(disk.paths, ["/downloads"])
        self.assertEqual(self.connections, 0)

    def test_stops_once_usage_is_just_below_threshold(self):
        # 95.5% used; removing 22.04 (1 GB) leaves 94.5%, so 23.10 stays.
        disk = self._disk(base_used=89.5, sizes={1: 1, 2: 4, 3: 1})

        self._enforce(95, disk)

        self.assertEqual(
            self.transmission.names,
            ["ubuntu-23.10-desktop-amd64.iso", "ubuntu-24.04-desktop-amd64.iso"],
        )

    def test_a_1_percent_threshold_is_enforced(self):
        disk = self._disk(base_used=40)  # 50%

        self._enforce(1, disk)

        self.assertEqual(self.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])

    def test_zero_size_disk_does_not_connect_or_raise(self):
        disk = helpers.FakeDisk(self.transmission, 0, {})

        self._enforce(1, disk)

        self.assertEqual((disk.paths, self.connections), (["/downloads"], 0))

    def test_checks_the_given_download_path_and_connects_once(self):
        disk = self._disk(base_used=99)

        ft.enforce_disk_usage_limit(
            self._connect,
            95,
            today=date(2026, 8, 1),
            disk_usage=disk,
            download_path="/mnt/seeds",
        )

        self.assertEqual(set(disk.paths), {"/mnt/seeds"})
        self.assertEqual(self.connections, 1)

    def test_logs_each_removal_with_usage_and_ratio(self):
        with self.assertLogs(ft.logger, level="WARNING") as logs:
            self._enforce(95, self._disk(base_used=86))

        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                (
                    "Downloads folder usage 96.0% >= 95.0% threshold - removing "
                    "ubuntu-22.04-desktop-amd64.iso (ratio 0.200) to free space."
                )
            ],
        )

    def test_records_a_zero_ratio_removal_as_zero(self):
        self.transmission.torrents[2] = helpers.FakeTorrent(
            "ubuntu-22.04-desktop-amd64.iso", 3, ratio=0.0
        )

        self._enforce(95, self._disk(base_used=86))

        self.assertEqual(
            ft.load_removed_history(ft.removed_history_file)[
                "ubuntu-22.04-desktop-amd64.iso"
            ]["ratio"],
            0.0,
        )

    def test_never_removes_the_latest_version(self):
        disk = self._disk(base_used=99)

        self._enforce(95, disk)

        self.assertEqual(self.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])

    def test_removes_the_watch_file_for_each_removal(self):
        watch_path = os.path.join(
            self.tmp_watch_dir, "ubuntu-22.04-desktop-amd64.iso.torrent"
        )
        with open(watch_path, "w", encoding="utf-8") as f:
            f.write("fake torrent bytes")

        self._enforce(95, self._disk(base_used=86))

        self.assertFalse(os.path.exists(watch_path))

    def test_no_candidates_logs_warning_and_does_not_raise(self):
        self.transmission.torrents = self.transmission.torrents[:1]

        with self.assertLogs(ft.logger, level="WARNING") as logs:
            self._enforce(95, self._disk(base_used=96))

        self.assertEqual(self.transmission.names, ["ubuntu-24.04-desktop-amd64.iso"])
        self.assertIn("no superseded versions are available", logs.output[0])

    def test_records_removal_reason_as_disk_pressure(self):
        self._enforce(95, self._disk(base_used=86))

        self.assertEqual(
            ft.load_removed_history(ft.removed_history_file),
            {
                "ubuntu-22.04-desktop-amd64.iso": {
                    "removed_date": "2026-08-01",
                    "reason": "disk_pressure",
                    "ratio": 0.2,
                }
            },
        )


class CleanupOldVersionsDefaultsTests(unittest.TestCase):
    """cleanup_old_versions() called the way the daily run calls it."""

    def setUp(self):
        self.history_path = helpers.use_state_files(self).removed_history_file
        helpers.use_watch_dir(self)

    def _transmission(self, old_ratio):
        return helpers.FakeTransmission(
            [
                helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=2.0),
                helpers.FakeTorrent(
                    "ubuntu-23.10-desktop-amd64.iso", 2, ratio=old_ratio
                ),
            ]
        )

    def test_default_min_ratio_is_one(self):
        for old_ratio, kept in ((1.5, False), (0.99, True)):
            with self.subTest(old_ratio=old_ratio):
                transmission = self._transmission(old_ratio)

                ft.cleanup_old_versions(transmission, today=date(2026, 8, 1))

                self.assertEqual(
                    "ubuntu-23.10-desktop-amd64.iso" in transmission.names, kept
                )

    def test_a_zero_ratio_removal_is_recorded_as_zero(self):
        transmission = self._transmission(0.0)

        ft.cleanup_old_versions(
            transmission, today=date(2026, 8, 1), skip_ratio_check=True
        )

        self.assertEqual(
            ft.load_removed_history(self.history_path),
            {
                "ubuntu-23.10-desktop-amd64.iso": {
                    "removed_date": "2026-08-01",
                    "reason": "keep_only_latest",
                    "ratio": 0.0,
                }
            },
        )


class RecordRemovalRatioTests(unittest.TestCase):
    def test_ratio_is_rounded_to_three_decimals(self):
        history = ft.record_removal({}, "x.iso", date(2026, 8, 1), "stagnant", 0.12345)

        self.assertEqual(history["x.iso"]["ratio"], 0.123)


if __name__ == "__main__":
    unittest.main()
