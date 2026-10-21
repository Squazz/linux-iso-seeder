"""Tests for the JSON state files kept between runs: fetch_torrents' ratio
history, removed-torrent history and old-release check state, and
configure_transmission's settings.json. All four share one contract
(JsonStoreContract), so a store can't quietly drift from the others.

Run with: python -m unittest discover -s tests
"""

import contextlib
import io
import os
import subprocess
import sys
import unittest
from typing import ClassVar

import helpers

import configure_transmission as ct
import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


class JsonStoreContract:
    """Mixed into one TestCase per store. A store must round-trip, treat a
    missing file as empty, and treat a corrupt one as empty *and say so*
    (rather than crash the run), and saving must leave only the file."""

    filename = ""
    sample: ClassVar[dict] = {}
    corrupt_report = ""  # start of what a corrupt file makes the store report

    def load(self, path):
        raise NotImplementedError

    def save(self, path, data):
        raise NotImplementedError

    def load_reporting(self, path):
        """load(path), plus whatever it reported, as text."""
        with self.assertLogs(ft.logger, level="WARNING") as logs:
            data = self.load(path)
        return data, "\n".join(r.getMessage() for r in logs.records)

    def setUp(self):
        self.dir = helpers.make_temp_dir(self, "persistence_")
        self.path = os.path.join(self.dir, self.filename)

    def test_round_trips_through_disk(self):
        self.save(self.path, self.sample)

        self.assertEqual(self.load(self.path), self.sample)

    def test_missing_file_loads_as_empty(self):
        self.assertEqual(self.load(os.path.join(self.dir, "does-not-exist.json")), {})

    def test_corrupt_file_loads_as_empty_and_says_so(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        data, report = self.load_reporting(self.path)

        self.assertEqual(data, {})
        self.assertTrue(
            report.startswith(f"{self.corrupt_report} {self.path} ("), report
        )
        self.assertIn("starting fresh", report)

    def test_unreadable_file_loads_as_empty_and_says_so(self):
        # A directory in the file's place: open() fails with an OSError
        # (IsADirectoryError on Linux, PermissionError on Windows).
        os.mkdir(self.path)

        data, report = self.load_reporting(self.path)

        self.assertEqual(data, {})
        self.assertTrue(
            report.startswith(f"{self.corrupt_report} {self.path} ("), report
        )
        self.assertIn("starting fresh", report)

    def test_saving_again_replaces_the_file_and_leaves_nothing_else(self):
        self.save(self.path, {"stale": 1})
        self.save(self.path, self.sample)

        self.assertEqual(self.load(self.path), self.sample)
        self.assertEqual(os.listdir(self.dir), [self.filename])


class RatioHistoryPersistenceTests(JsonStoreContract, unittest.TestCase):
    filename = "fetch_torrents_ratio_history.json"
    sample: ClassVar[dict] = {
        "archlinux-2026.08.01-x86_64.iso": [{"date": "2026-08-29", "ratio": 1.2}]
    }
    corrupt_report = "Could not read ratio history at"

    def load(self, path):
        return ft.load_ratio_history(path)

    def save(self, path, data):
        ft.save_ratio_history(path, data)


class RemovedHistoryPersistenceTests(JsonStoreContract, unittest.TestCase):
    filename = "fetch_torrents_removed_history.json"
    sample: ClassVar[dict] = {"x": {"removed_date": "2026-02-01", "reason": "stagnant"}}
    corrupt_report = "Could not read removed-torrent history at"

    def load(self, path):
        return ft.load_removed_history(path)

    def save(self, path, data):
        ft.save_removed_history(path, data)


class OldReleaseCheckStatePersistenceTests(JsonStoreContract, unittest.TestCase):
    filename = "fetch_torrents_old_release_check_state.json"
    sample: ClassVar[dict] = {"x": {"last_checked": "2026-01-08", "leechers": 0}}
    corrupt_report = "Could not read old-release check state at"

    def load(self, path):
        return ft.load_old_release_check_state(path)

    def save(self, path, data):
        ft.save_old_release_check_state(path, data)


class SettingsFilePersistenceTests(JsonStoreContract, unittest.TestCase):
    filename = "settings.json"
    sample: ClassVar[dict] = {"rpc-whitelist": "10.0.0.*", "peer-limit-global": 200}
    corrupt_report = "configure_transmission: could not read"

    def load(self, path):
        return ct.load_settings(path)

    def save(self, path, data):
        ct.save_settings(path, data)

    def load_reporting(self, path):
        # Runs before logging exists in the container, so it reports on stderr.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            data = self.load(path)
        return data, stderr.getvalue().strip()


class StateFileLocationTests(unittest.TestCase):
    """Every test patches these paths, so their real values are pinned
    here: state lives under the log dir, torrents go to /watch."""

    def test_state_files_live_in_the_log_dir(self):
        self.assertEqual(
            (
                ft.ratio_log_file,
                ft.ratio_history_file,
                ft.removed_history_file,
                ft.old_release_check_state_file,
            ),
            tuple(
                os.path.join(ft.log_dir, name)
                for name in (
                    "fetch_torrents_ratios.log",
                    "fetch_torrents_ratio_history.json",
                    "fetch_torrents_removed_history.json",
                    "fetch_torrents_old_release_check_state.json",
                )
            ),
        )

    def _watch_dir_on_import(self, **env):
        """ft.watch_dir as a fresh interpreter importing the module under
        `env` sees it (this process imported it long ago)."""
        script = (
            "import sys\n"
            f"sys.path.insert(0, {helpers.REPO_ROOT!r})\n"
            "import fetch_torrents as ft\n"
            "print(ft.watch_dir)\n"
        )
        result = subprocess.run(
            [sys.executable, "-W", "ignore", "-c", script],
            check=False,
            env=helpers.scrubbed_environ(**env),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.rstrip("\n")

    def test_torrents_are_written_to_the_watch_volume_by_default(self):
        self.assertEqual(self._watch_dir_on_import(), "/watch")

    def test_fetch_torrents_watch_dir_moves_the_watch_dir(self):
        self.assertEqual(
            self._watch_dir_on_import(FETCH_TORRENTS_WATCH_DIR="/srv/torrents"),
            "/srv/torrents",
        )


class StateFileFormatTests(unittest.TestCase):
    """The state files sit in the /logs volume for people to read and diff,
    so they are written indented, with keys sorted."""

    def test_state_files_are_indented_with_sorted_keys(self):
        directory = helpers.make_temp_dir(self, "persistence_")
        for save in (
            ft.save_ratio_history,
            ft.save_removed_history,
            ft.save_old_release_check_state,
        ):
            with self.subTest(save.__name__):
                path = os.path.join(directory, f"{save.__name__}.json")

                save(path, {"b.iso": {"y": 1, "x": 2}, "a.iso": []})

                with open(path, encoding="utf-8") as f:
                    self.assertEqual(
                        f.read(),
                        '{\n  "a.iso": [],\n  "b.iso": {\n    "x": 2,\n    "y": 1\n  }\n}',
                    )


if __name__ == "__main__":
    unittest.main()
