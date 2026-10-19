"""Tests for the JSON state files the daily run keeps between runs.

Run with: python -m unittest discover -s tests
"""

import os
import unittest
import unittest.mock

import helpers

import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


class RatioHistoryPersistenceTests(unittest.TestCase):
    """load_ratio_history()/save_ratio_history() must round-trip cleanly and
    tolerate a missing or corrupt file rather than crashing a run."""

    def test_round_trips_through_disk(self):
        tmp_dir = helpers.make_temp_dir(self, "fetch_torrents_ratio_history_")
        path = os.path.join(tmp_dir, "fetch_torrents_ratio_history.json")
        history = {
            "archlinux-2026.08.01-x86_64.iso": [{"date": "2026-08-29", "ratio": 1.2}]
        }

        ft.save_ratio_history(path, history)
        loaded = ft.load_ratio_history(path)

        self.assertEqual(loaded, history)

    def test_missing_file_returns_empty_history(self):
        tmp_dir = helpers.make_temp_dir(self, "fetch_torrents_ratio_history_")
        path = os.path.join(tmp_dir, "does-not-exist.json")

        self.assertEqual(ft.load_ratio_history(path), {})

    def test_corrupt_file_returns_empty_history_instead_of_raising(self):
        tmp_dir = helpers.make_temp_dir(self, "fetch_torrents_ratio_history_")
        path = os.path.join(tmp_dir, "fetch_torrents_ratio_history.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        self.assertEqual(ft.load_ratio_history(path), {})


class OldReleaseCheckStatePersistenceTests(unittest.TestCase):
    def test_round_trips_through_disk(self):
        tmp_dir = helpers.make_temp_dir(self, "fetch_torrents_old_release_state_")
        path = os.path.join(tmp_dir, "fetch_torrents_old_release_check_state.json")
        state = {"x": {"last_checked": "2026-01-08", "leechers": 0}}

        ft.save_old_release_check_state(path, state)
        loaded = ft.load_old_release_check_state(path)

        self.assertEqual(loaded, state)

    def test_missing_file_returns_empty_state(self):
        tmp_dir = helpers.make_temp_dir(self, "fetch_torrents_old_release_state_")
        path = os.path.join(tmp_dir, "does-not-exist.json")

        self.assertEqual(ft.load_old_release_check_state(path), {})

    def test_corrupt_file_returns_empty_state_instead_of_raising(self):
        tmp_dir = helpers.make_temp_dir(self, "fetch_torrents_old_release_state_")
        path = os.path.join(tmp_dir, "fetch_torrents_old_release_check_state.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        self.assertEqual(ft.load_old_release_check_state(path), {})


class RemovedHistoryPersistenceTests(unittest.TestCase):
    def test_round_trips_through_disk(self):
        tmp_dir = helpers.make_temp_dir(self, "fetch_torrents_removed_history_")
        path = os.path.join(tmp_dir, "fetch_torrents_removed_history.json")
        history = {"x": {"removed_date": "2026-02-01", "reason": "stagnant"}}

        ft.save_removed_history(path, history)
        loaded = ft.load_removed_history(path)

        self.assertEqual(loaded, history)

    def test_missing_file_returns_empty_history(self):
        tmp_dir = helpers.make_temp_dir(self, "fetch_torrents_removed_history_")
        path = os.path.join(tmp_dir, "does-not-exist.json")

        self.assertEqual(ft.load_removed_history(path), {})

    def test_corrupt_file_returns_empty_history_instead_of_raising(self):
        tmp_dir = helpers.make_temp_dir(self, "fetch_torrents_removed_history_")
        path = os.path.join(tmp_dir, "fetch_torrents_removed_history.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        self.assertEqual(ft.load_removed_history(path), {})


if __name__ == "__main__":
    unittest.main()
