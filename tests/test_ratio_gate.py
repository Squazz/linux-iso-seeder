"""Tests for the ratio gate: get_distro(), parse_version_type(), should_fetch_torrent()
(and its removed-history / Devuan variants) and reading the previous
run's ratio log with get_previous_ratios().

Run with: python -m unittest discover -s tests
"""

import os
import unittest
import unittest.mock

import helpers

import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


class ParseVersionTypeTests(unittest.TestCase):
    """(version, type_) is the grouping key for the ratio gate and cleanup:
    two names share a ratio history only when their type_ is equal."""

    CASES = (
        (
            "ubuntu-24.04-desktop-amd64.iso",
            "ubuntu",
            ("24.04", "ubuntu-desktop-amd64.iso"),
        ),
        (
            "ubuntu-24.04-desktop-arm64.iso",
            "ubuntu",
            ("24.04", "ubuntu-desktop-arm64.iso"),
        ),
        (
            "xubuntu-24.04-desktop-amd64.iso",
            "ubuntu",
            ("24.04", "xubuntu-desktop-amd64.iso"),
        ),
        ("debian-12.5.0-amd64-DVD-1.iso", "debian", ("12.5.0", "amd64-DVD-1.iso")),
        ("debian-12.5.0-arm64-DVD-1.iso", "debian", ("12.5.0", "arm64-DVD-1.iso")),
        (
            "kali-linux-2024.1-installer-amd64.iso",
            "kali",
            ("2024.1", "installer-amd64.iso"),
        ),
        (
            "kali-linux-2024.1-installer-arm64.iso",
            "kali",
            ("2024.1", "installer-arm64.iso"),
        ),
        ("archlinux-2024.05.01-x86_64.iso", "arch", ("2024.05.01", "")),
        ("linuxmint-22.3-cinnamon-64bit.iso", "mint", ("22.3", "cinnamon-64bit.iso")),
        ("Fedora-Workstation-Live-x86_64-44", "fedora", ("44", "x86_64")),
        ("Fedora-Workstation-Live-aarch64-44", "fedora", ("44", "aarch64")),
        ("anything-1.0", "not-a-distro", ("", "")),
    )

    def test_version_and_type_per_distro(self):
        for name, distro, expected in self.CASES:
            with self.subTest(name):
                self.assertEqual(ft.parse_version_type(name, distro), expected)

    def test_architectures_of_the_same_release_get_different_types(self):
        pairs = [
            (
                "ubuntu-24.04-desktop-amd64.iso",
                "ubuntu-24.04-desktop-arm64.iso",
                "ubuntu",
            ),
            (
                "debian-12.5.0-amd64-DVD-1.iso",
                "debian-12.5.0-arm64-DVD-1.iso",
                "debian",
            ),
            (
                "kali-linux-2024.1-installer-amd64.iso",
                "kali-linux-2024.1-installer-arm64.iso",
                "kali",
            ),
            (
                "Fedora-Workstation-Live-x86_64-44",
                "Fedora-Workstation-Live-aarch64-44",
                "fedora",
            ),
        ]
        for a, b, distro in pairs:
            with self.subTest(distro):
                self.assertNotEqual(
                    ft.parse_version_type(a, distro)[1],
                    ft.parse_version_type(b, distro)[1],
                )


class GetDistroTests(unittest.TestCase):
    def test_every_ubuntu_flavour_fetched_is_recognised_as_ubuntu(self):
        # fetch_ubuntu_lts() fetches ubuntu, lubuntu and xubuntu images; a
        # flavour get_distro() doesn't recognise skips the ratio gate and
        # cleanup grouping entirely.
        for name in (
            "ubuntu-24.04-desktop-amd64.iso",
            "lubuntu-24.04-desktop-amd64.iso",
            "xubuntu-24.04-desktop-amd64.iso",
        ):
            with self.subTest(name):
                self.assertEqual(ft.get_distro(name), "ubuntu")


class ShouldFetchTorrentRatioKeyTests(unittest.TestCase):
    """Candidate names must key into the same ratio-lookup bucket as the names Transmission
    actually reports (which include the arch suffix and .iso extension),
    for all supported distros."""

    # (previous version as Transmission reports it, its ratio, candidate,
    # whether the candidate is fetched). A low ratio blocks only if the
    # previous version is found; a high one shows the floor is applied, not
    # just any ratio.
    CASES = (
        (
            "ubuntu-23.10-desktop-amd64.iso",
            0.5,
            "ubuntu-24.04-desktop-amd64.iso",
            False,
        ),
        ("ubuntu-23.10-desktop-amd64.iso", 1.5, "ubuntu-24.04-desktop-amd64.iso", True),
        ("debian-12.4.0-amd64-DVD-1.iso", 0.5, "debian-12.5.0-amd64-DVD-1.iso", False),
        ("debian-12.4.0-amd64-DVD-1.iso", 1.5, "debian-12.5.0-amd64-DVD-1.iso", True),
        (
            "kali-linux-2023.4-installer-amd64.iso",
            0.3,
            "kali-linux-2024.1-installer-amd64.iso",
            False,
        ),
        (
            "kali-linux-2023.4-installer-amd64.iso",
            1.5,
            "kali-linux-2024.1-installer-amd64.iso",
            True,
        ),
        (
            "archlinux-2024.04.01-x86_64.iso",
            0.2,
            "archlinux-2024.05.01-x86_64.iso",
            False,
        ),
        (
            "archlinux-2024.04.01-x86_64.iso",
            1.5,
            "archlinux-2024.05.01-x86_64.iso",
            True,
        ),
        (
            "linuxmint-22.2-cinnamon-64bit.iso",
            0.4,
            "linuxmint-22.3-cinnamon-64bit.iso",
            False,
        ),
        (
            "linuxmint-22.2-cinnamon-64bit.iso",
            1.5,
            "linuxmint-22.3-cinnamon-64bit.iso",
            True,
        ),
        (
            "Fedora-Workstation-Live-x86_64-43",
            0.4,
            "Fedora-Workstation-Live-x86_64-44",
            False,
        ),
        (
            "Fedora-Workstation-Live-x86_64-43",
            1.5,
            "Fedora-Workstation-Live-x86_64-44",
            True,
        ),
    )

    def test_previous_version_is_found_and_its_ratio_gates_the_candidate(self):
        for previous, ratio, candidate, fetched in self.CASES:
            with self.subTest(candidate=candidate, previous_ratio=ratio):
                self.assertIs(
                    ft.should_fetch_torrent(candidate, {previous: ratio}), fetched
                )

    def test_lubuntu_is_ratio_gated_on_its_own_previous_release(self):
        ratios = {
            "lubuntu-23.10-desktop-amd64.iso": 0.2,
            "ubuntu-23.10-desktop-amd64.iso": 5.0,
        }
        self.assertFalse(
            ft.should_fetch_torrent("lubuntu-24.04-desktop-amd64.iso", ratios)
        )


class ShouldFetchTorrentRemovedHistoryFallbackTests(unittest.TestCase):
    """Once a previous version is removed by cleanup, Transmission stops
    reporting it and it drops out of `ratios` (see get_previous_ratios()) -
    without a fallback, should_fetch_torrent() would then hit its "no
    previous version" branch and fetch unconditionally, silently bypassing
    the ratio gate for exactly the versions cleanup already gave up on.
    removed_history (record_removal()'s output) is the fallback source."""

    def test_falls_back_to_removed_history_ratio_when_not_live(self):
        removed_history = helpers.removed("ubuntu-23.10-desktop-amd64.iso", 0.4)
        self.assertFalse(
            ft.should_fetch_torrent(
                "ubuntu-24.04-desktop-amd64.iso",
                ratios={},
                removed_history=removed_history,
            )
        )

    def test_removed_history_ratio_above_floor_allows_fetch(self):
        removed_history = helpers.removed("ubuntu-23.10-desktop-amd64.iso", 1.5)
        self.assertTrue(
            ft.should_fetch_torrent(
                "ubuntu-24.04-desktop-amd64.iso",
                ratios={},
                removed_history=removed_history,
            )
        )

    def test_live_ratio_takes_priority_over_removed_history(self):
        # Same name in both is not expected in practice (a torrent Transmission
        # still reports hasn't been removed), but live data winning if it ever
        # happens is the safer default.
        removed_history = helpers.removed("ubuntu-23.10-desktop-amd64.iso", 0.1)
        ratios = {"ubuntu-23.10-desktop-amd64.iso": 1.5}
        self.assertTrue(
            ft.should_fetch_torrent(
                "ubuntu-24.04-desktop-amd64.iso",
                ratios,
                removed_history=removed_history,
            )
        )

    def test_low_live_ratio_is_not_overridden_by_high_removed_history(self):
        removed_history = helpers.removed("ubuntu-23.10-desktop-amd64.iso", 1.5)
        ratios = {"ubuntu-23.10-desktop-amd64.iso": 0.4}
        self.assertFalse(
            ft.should_fetch_torrent(
                "ubuntu-24.04-desktop-amd64.iso",
                ratios,
                removed_history=removed_history,
            )
        )

    def test_removed_history_entry_without_ratio_is_ignored(self):
        # Legacy entries recorded before this field existed have no 'ratio'
        # key - must not crash, and must not count as a usable prior version.
        removed_history = helpers.removed("ubuntu-23.10-desktop-amd64.iso")
        # Skipped up front, not by tripping over the missing key and logging
        # a parse-error warning.
        with self.assertNoLogs(ft.logger, level="WARNING"):
            result = ft.should_fetch_torrent(
                "ubuntu-24.04-desktop-amd64.iso",
                ratios={},
                removed_history=removed_history,
            )
        self.assertIs(result, True)

    def test_skipped_removed_history_entry_does_not_hide_later_ones(self):
        removed_history = {
            **helpers.removed("ubuntu-23.04-desktop-amd64.iso"),
            **helpers.removed("ubuntu-23.10-desktop-amd64.iso", 0.4),
        }
        self.assertFalse(
            ft.should_fetch_torrent(
                "ubuntu-24.04-desktop-amd64.iso",
                ratios={},
                removed_history=removed_history,
            )
        )

    def test_removed_history_from_a_different_distro_is_not_consulted(self):
        removed_history = helpers.removed("debian-12.4.0-amd64-DVD-1.iso", 0.1)
        self.assertTrue(
            ft.should_fetch_torrent(
                "ubuntu-24.04-desktop-amd64.iso",
                ratios={},
                removed_history=removed_history,
            )
        )


class ShouldFetchTorrentDevuanRatioGateTests(unittest.TestCase):
    """Devuan has no per-name version to compare (get_distro() returns None
    for it - see distro_patterns), so should_fetch_torrent() instead gates
    fetching a new Devuan release on the ratio achieved by whichever Devuan
    release we currently hold, using the same 1.0 floor as other distros."""

    def test_no_previous_devuan_release_fetches(self):
        self.assertTrue(ft.should_fetch_torrent("devuan_excalibur", ratios={}))

    def test_low_ratio_on_current_release_blocks_next_release(self):
        ratios = {"devuan_daedalus": 0.4}
        self.assertFalse(ft.should_fetch_torrent("devuan_excalibur", ratios))

    def test_high_ratio_on_current_release_allows_next_release(self):
        ratios = {"devuan_daedalus": 1.5}
        self.assertTrue(ft.should_fetch_torrent("devuan_excalibur", ratios))

    def test_already_holding_this_exact_release_is_always_fetched(self):
        # download_torrent()'s own file-existence check is what actually
        # dedupes a re-offered current release - not this ratio gate.
        ratios = {"devuan_excalibur": 0.1}
        self.assertTrue(ft.should_fetch_torrent("devuan_excalibur", ratios))

    def test_falls_back_to_removed_history_when_no_live_ratio(self):
        removed_history = helpers.removed("devuan_daedalus", 0.4)
        self.assertFalse(
            ft.should_fetch_torrent(
                "devuan_excalibur", ratios={}, removed_history=removed_history
            )
        )

    def test_other_distros_removed_history_not_consulted_for_devuan(self):
        removed_history = helpers.removed("debian-12.4.0-amd64-DVD-1.iso", 0.1)
        self.assertTrue(
            ft.should_fetch_torrent(
                "devuan_excalibur", ratios={}, removed_history=removed_history
            )
        )


class ShouldFetchTorrentBoundaryTests(unittest.TestCase):
    """The 1.0 floor is inclusive, only strictly older versions count as the
    "previous" one, and the branches that bypass the gate entirely."""

    def test_previous_ratio_exactly_at_floor_allows_fetch(self):
        ratios = {"ubuntu-23.10-desktop-amd64.iso": 1.0}
        self.assertTrue(
            ft.should_fetch_torrent("ubuntu-24.04-desktop-amd64.iso", ratios)
        )

    def test_previous_ratio_just_below_floor_blocks_fetch(self):
        ratios = {"ubuntu-23.10-desktop-amd64.iso": 0.999}
        self.assertFalse(
            ft.should_fetch_torrent("ubuntu-24.04-desktop-amd64.iso", ratios)
        )

    def test_devuan_previous_ratio_exactly_at_floor_allows_fetch(self):
        self.assertTrue(
            ft.should_fetch_torrent("devuan_excalibur", {"devuan_daedalus": 1.0})
        )

    def test_devuan_previous_ratio_just_below_floor_blocks_fetch(self):
        self.assertFalse(
            ft.should_fetch_torrent("devuan_excalibur", {"devuan_daedalus": 0.999})
        )

    def test_only_newer_versions_on_record_fetches(self):
        # A newer release with a low ratio isn't a "previous" one, so there
        # is nothing to gate on.
        ratios = {"ubuntu-24.10-desktop-amd64.iso": 0.1}
        self.assertTrue(
            ft.should_fetch_torrent("ubuntu-24.04-desktop-amd64.iso", ratios)
        )

    def test_same_version_on_record_is_not_its_own_predecessor(self):
        ratios = {"ubuntu-24.04-desktop-amd64.iso": 0.1}
        self.assertTrue(
            ft.should_fetch_torrent("ubuntu-24.04-desktop-amd64.iso", ratios)
        )

    def test_highest_older_version_decides_not_any_older_version(self):
        ratios = {
            "ubuntu-22.04-desktop-amd64.iso": 5.0,
            "ubuntu-23.10-desktop-amd64.iso": 0.4,
        }
        self.assertFalse(
            ft.should_fetch_torrent("ubuntu-24.04-desktop-amd64.iso", ratios)
        )

    def test_other_architecture_ratio_is_not_consulted(self):
        ratios = {"ubuntu-23.10-desktop-arm64.iso": 0.1}
        self.assertTrue(
            ft.should_fetch_torrent("ubuntu-24.04-desktop-amd64.iso", ratios)
        )

    def test_devuan_ignores_non_devuan_ratios(self):
        ratios = {"debian-12.4.0-amd64-DVD-1.iso": 5.0, "devuan_daedalus": 0.4}
        self.assertFalse(ft.should_fetch_torrent("devuan_excalibur", ratios))

    def test_devuan_removed_history_for_the_same_release_is_not_a_predecessor(self):
        removed_history = helpers.removed("devuan_excalibur", 0.1)
        self.assertTrue(
            ft.should_fetch_torrent(
                "devuan_excalibur", ratios={}, removed_history=removed_history
            )
        )

    def test_devuan_live_ratio_beats_removed_history(self):
        removed_history = helpers.removed("devuan_chimaera", 0.1)
        self.assertTrue(
            ft.should_fetch_torrent(
                "devuan_excalibur",
                {"devuan_daedalus": 1.5},
                removed_history=removed_history,
            )
        )

    def test_skip_ratio_check_fetches_despite_low_previous_ratio(self):
        ratios = {"ubuntu-23.10-desktop-amd64.iso": 0.1}
        self.assertTrue(
            ft.should_fetch_torrent(
                "ubuntu-24.04-desktop-amd64.iso", ratios, skip_ratio_check=True
            )
        )

    def test_unknown_distro_fetches(self):
        ratios = {"slackware-15.0-install-dvd.iso": 0.1}
        self.assertTrue(
            ft.should_fetch_torrent("slackware-15.1-install-dvd.iso", ratios)
        )

    def test_unparseable_name_of_known_distro_fetches_and_logs_error(self):
        ratios = {"ubuntu-23.10-desktop-amd64.iso": 0.1}
        with self.assertLogs(ft.logger, level="ERROR") as logs:
            result = ft.should_fetch_torrent("ubuntu-noble-desktop-amd64.iso", ratios)

        self.assertIs(result, True)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("ubuntu-noble-desktop-amd64.iso", logs.output[0])

    def test_unparseable_stored_ratio_entry_is_skipped(self):
        ratios = {
            "ubuntu-mantic-desktop-amd64.iso": 0.1,
            "ubuntu-23.10-desktop-amd64.iso": 1.5,
        }
        with self.assertLogs(ft.logger, level="WARNING"):
            self.assertTrue(
                ft.should_fetch_torrent("ubuntu-24.04-desktop-amd64.iso", ratios)
            )


class GetPreviousRatiosTests(unittest.TestCase):
    """get_previous_ratios() is what feeds should_fetch_torrent()'s ratios:
    only the last START/END segment of the previous run's ratio log counts,
    so a ratio from an older run can't satisfy (or block) the gate."""

    def _write_log(self, *messages):
        path = os.path.join(
            helpers.make_temp_dir(self, "fetch_torrents_prev_ratios_"),
            "fetch_torrents_ratios.log",
        )
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(
                f"2026-08-01 00:00:00,000 INFO: {message}\n" for message in messages
            )
        return path

    def test_missing_file_returns_empty(self):
        missing = os.path.join(
            helpers.make_temp_dir(self, "fetch_torrents_prev_ratios_"), "nope.log"
        )
        self.assertEqual(ft.get_previous_ratios(missing), {})

    def test_without_markers_every_ratio_line_is_parsed(self):
        path = self._write_log(
            "[ratio] ubuntu-24.04-desktop-amd64.iso → 1.250",
            "unrelated line",
            "[ratio] debian-12.5.0-amd64-DVD-1.iso → 0.664",
        )
        self.assertEqual(
            ft.get_previous_ratios(path),
            {
                "ubuntu-24.04-desktop-amd64.iso": 1.25,
                "debian-12.5.0-amd64-DVD-1.iso": 0.664,
            },
        )

    def test_only_the_last_complete_segment_is_returned(self):
        path = self._write_log(
            "[ratio] RATIOS START",
            "[ratio] old-only.iso → 0.100",
            "[ratio] shared.iso → 0.200",
            "[ratio] RATIOS END",
            "[ratio] RATIOS START",
            "[ratio] shared.iso → 1.500",
            "[ratio] RATIOS END",
            "[ratio] after-end.iso → 0.300",
        )
        self.assertEqual(ft.get_previous_ratios(path), {"shared.iso": 1.5})

    def test_start_without_end_parses_to_end_of_file(self):
        # A run that crashed mid-way never wrote its END marker.
        path = self._write_log(
            "[ratio] RATIOS START",
            "[ratio] old.iso → 0.100",
            "[ratio] RATIOS END",
            "[ratio] RATIOS START",
            "[ratio] crashed-run.iso → 0.700",
        )
        self.assertEqual(ft.get_previous_ratios(path), {"crashed-run.iso": 0.7})

    def test_end_before_the_last_start_is_ignored(self):
        path = self._write_log(
            "[ratio] RATIOS END",
            "[ratio] before-start.iso → 0.100",
            "[ratio] RATIOS START",
            "[ratio] current.iso → 0.900",
        )
        self.assertEqual(ft.get_previous_ratios(path), {"current.iso": 0.9})

    def test_last_end_after_the_last_start_closes_the_segment(self):
        # Not written by a normal run; pins current behavior.
        path = self._write_log(
            "[ratio] RATIOS START",
            "[ratio] first.iso → 0.100",
            "[ratio] RATIOS END",
            "[ratio] second.iso → 0.200",
            "[ratio] RATIOS END",
            "[ratio] after.iso → 0.300",
        )
        self.assertEqual(
            ft.get_previous_ratios(path), {"first.iso": 0.1, "second.iso": 0.2}
        )

    def test_padded_names_are_stripped(self):
        path = self._write_log(
            "[ratio] archlinux-2026.04.01-x86_64.iso            → 0.664",
        )
        self.assertEqual(
            ft.get_previous_ratios(path), {"archlinux-2026.04.01-x86_64.iso": 0.664}
        )

    def test_names_with_internal_spaces_keep_them(self):
        path = self._write_log("[ratio]   Some Torrent Name   → 2.000")
        self.assertEqual(ft.get_previous_ratios(path), {"Some Torrent Name": 2.0})

    def test_ratio_without_decimal_point_is_not_matched(self):
        # Pins current behavior: log_seed_ratios_via_http() always writes
        # three decimals, so an integer ratio means a line it didn't write.
        path = self._write_log("[ratio] whole.iso → 1")
        self.assertEqual(ft.get_previous_ratios(path), {})

    def test_duplicate_name_in_a_segment_last_one_wins(self):
        path = self._write_log(
            "[ratio] RATIOS START",
            "[ratio] dup.iso → 0.100",
            "[ratio] dup.iso → 1.100",
            "[ratio] RATIOS END",
        )
        self.assertEqual(ft.get_previous_ratios(path), {"dup.iso": 1.1})


if __name__ == "__main__":
    unittest.main()
