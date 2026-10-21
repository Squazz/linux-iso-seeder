"""Tests for the test doubles and guards in tests/helpers.py.

The Transmission doubles must not drift from the real transmission_rpc
library (pinned in requirements-test.txt to the version Alpine's
py3-transmission-rpc ships): a call production code makes that the real
Client wouldn't accept has to fail here, not in the container. And
isolate_module() must really keep tests off the network.

Run with: python -m unittest discover -s tests
"""

import os
import unittest
import unittest.mock
from datetime import date

import helpers
import requests
import transmission_rpc

import fetch_torrents as ft


def setUpModule():
    helpers.isolate_module()


class FakeTransmissionMatchesClientTests(unittest.TestCase):
    def test_accepts_every_call_shape_the_real_client_accepts(self):
        transmission = helpers.FakeTransmission(
            [helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1)]
        )

        transmission.get_torrents(ids=[1], arguments=["name"], timeout=5)
        transmission.remove_torrent(ids=1, delete_data=True, timeout=5)

        self.assertEqual(transmission.torrents, [])

    def test_rejects_keywords_the_real_client_lacks(self):
        transmission = helpers.FakeTransmission()

        with self.assertRaises(TypeError):
            transmission.remove_torrent(1, delete=True)
        with self.assertRaises(TypeError):
            transmission.get_torrents(fields=["name"])

    def test_every_public_method_exists_on_the_real_client(self):
        own = {
            name
            for name, value in vars(helpers.FakeTransmission).items()
            if callable(value) and not name.startswith("_")
        }

        self.assertEqual(own - set(dir(transmission_rpc.Client)), set())

    def test_removals_lists_only_the_remove_torrent_calls(self):
        transmission = helpers.FakeTransmission(
            [
                helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1),
                helpers.FakeTorrent("ubuntu-23.10-desktop-amd64.iso", 2),
            ]
        )

        transmission.get_torrents()
        transmission.remove_torrent(2, delete_data=True)
        transmission.get_torrents()
        transmission.remove_torrent(1)

        self.assertEqual(transmission.removals, [(2, True), (1, False)])


class FakeDiskTests(unittest.TestCase):
    """The real Client's remove_torrent() defaults to delete_data=False,
    which takes the torrent out of Transmission but leaves its downloaded
    data on disk - so FakeDisk must only count a removal as freed space
    when the data was deleted too."""

    def setUp(self):
        self.transmission = helpers.FakeTransmission(
            [helpers.FakeTorrent("ubuntu-22.04-desktop-amd64.iso", 1)]
        )
        self.disk = helpers.FakeDisk(self.transmission, 100, {1: 6}, base_used=10)

    def test_removal_with_data_frees_its_space(self):
        self.transmission.remove_torrent(1, delete_data=True)

        self.assertEqual(self.disk("/downloads"), (100, 10, 90))

    def test_removal_without_data_frees_nothing(self):
        self.transmission.remove_torrent(1)

        self.assertEqual(self.transmission.torrents, [])
        self.assertEqual(self.disk("/downloads"), (100, 16, 84))


class FakeTorrentTests(unittest.TestCase):
    def test_is_a_real_torrent_reading_real_rpc_field_names(self):
        torrent = helpers.FakeTorrent(
            "devuan_excalibur", 7, ratio=1.25, added_date=2000
        )

        self.assertIsInstance(torrent, transmission_rpc.Torrent)
        self.assertEqual(
            (torrent.name, torrent.id, torrent.ratio, torrent.added_date.timestamp()),
            ("devuan_excalibur", 7, 1.25, 2000.0),
        )


RPC_URL = "http://localhost:9091/transmission/rpc"
TORRENT_GET = {"method": "torrent-get", "arguments": {"fields": ["name"]}}


class FakeTransmissionRpcTests(unittest.TestCase):
    """The HTTP RPC double behaves like the daemon's CSRF handshake: no
    answer without the session id it handed out in a 409."""

    def setUp(self):
        self.rpc = helpers.FakeTransmissionRpc(
            helpers.FakeTransmission(
                [helpers.FakeTorrent("ubuntu-24.04-desktop-amd64.iso", 1, ratio=1.5)]
            )
        )

    def _session_headers(self):
        refused = self.rpc.post(RPC_URL, timeout=15)
        return {
            "X-Transmission-Session-Id": refused.headers["X-Transmission-Session-Id"]
        }

    def test_a_request_without_the_session_id_gets_a_409_carrying_it(self):
        for headers in (None, {"X-Transmission-Session-Id": "stale"}):
            with self.subTest(headers=headers):
                response = self.rpc.post(
                    RPC_URL, json=TORRENT_GET, headers=headers, timeout=15
                )

                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    response.headers["X-Transmission-Session-Id"],
                    helpers.FakeTransmissionRpc.SESSION_ID,
                )
        self.assertEqual(self.rpc.auths, [])

    def test_torrent_get_lists_the_requested_fields_and_records_auth(self):
        response = self.rpc.post(
            RPC_URL,
            json={
                "method": "torrent-get",
                "arguments": {"fields": ["name", "uploadRatio"]},
            },
            headers=self._session_headers(),
            auth=("alice", "hunter2"),
            timeout=15,
        )

        response.raise_for_status()
        self.assertEqual(
            response.json(),
            {
                "arguments": {
                    "torrents": [
                        {"name": "ubuntu-24.04-desktop-amd64.iso", "uploadRatio": 1.5}
                    ]
                },
                "result": "success",
            },
        )
        self.assertEqual(self.rpc.auths, [("alice", "hunter2")])

    def test_every_post_is_recorded_in_order(self):
        headers = self._session_headers()
        self.rpc.post(RPC_URL, json=TORRENT_GET, headers=headers, timeout=15)

        self.assertEqual(
            self.rpc.calls,
            [
                unittest.mock.call(RPC_URL, timeout=15),
                unittest.mock.call(
                    RPC_URL, json=TORRENT_GET, headers=headers, timeout=15
                ),
            ],
        )

    def test_rejects_what_the_pinned_library_does_not_know(self):
        headers = self._session_headers()
        for payload in (
            {"method": "torrent-fetch", "arguments": {"fields": ["name"]}},
            {"method": "torrent-get", "arguments": {"fields": ["ratio"]}},
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaisesRegex(ValueError, "transmission_rpc"),
            ):
                self.rpc.post(RPC_URL, json=payload, headers=headers, timeout=15)

    def test_other_urls_are_not_found(self):
        response = self.rpc.post("http://localhost:9091/rpc", timeout=15)

        self.assertEqual(response.status_code, 404)


class PathFixtureTests(unittest.TestCase):
    """use_watch_dir()/use_state_files() point fetch_torrents' module path
    globals at fresh temp files for one test, and put them back after."""

    def test_use_watch_dir_patches_watch_dir_until_the_test_ends(self):
        original = ft.watch_dir
        test = unittest.FunctionTestCase(lambda: None)

        path = helpers.use_watch_dir(test)

        self.assertEqual(ft.watch_dir, path)
        self.assertEqual(os.listdir(path), [])
        test.doCleanups()
        self.assertEqual(ft.watch_dir, original)
        self.assertFalse(os.path.exists(path))

    def test_use_state_files_patches_every_state_file_until_the_test_ends(self):
        names = (
            "ratio_log_file",
            "ratio_history_file",
            "removed_history_file",
            "old_release_check_state_file",
        )
        originals = [getattr(ft, name) for name in names]
        test = unittest.FunctionTestCase(lambda: None)

        state = helpers.use_state_files(test)

        self.assertEqual(
            [getattr(ft, name) for name in names],
            [
                os.path.join(state.dir, "fetch_torrents_ratios.log"),
                os.path.join(state.dir, "fetch_torrents_ratio_history.json"),
                os.path.join(state.dir, "fetch_torrents_removed_history.json"),
                os.path.join(state.dir, "fetch_torrents_old_release_check_state.json"),
            ],
        )
        self.assertEqual(
            [getattr(state, name) for name in names], [getattr(ft, n) for n in names]
        )
        self.assertEqual(os.listdir(state.dir), [])
        test.doCleanups()
        self.assertEqual([getattr(ft, name) for name in names], originals)
        self.assertFalse(os.path.exists(state.dir))


class RemovedTests(unittest.TestCase):
    def test_matches_what_record_removal_writes(self):
        self.assertEqual(
            helpers.removed("ubuntu-23.10-desktop-amd64.iso", 0.4),
            ft.record_removal(
                {}, "ubuntu-23.10-desktop-amd64.iso", date(2026, 1, 1), "stagnant", 0.4
            ),
        )

    def test_without_a_ratio_is_a_legacy_entry(self):
        self.assertEqual(
            helpers.removed("devuan_daedalus", on="2025-12-01"),
            {"devuan_daedalus": {"removed_date": "2025-12-01", "reason": "stagnant"}},
        )


class NetworkGuardTests(unittest.TestCase):
    def test_real_connections_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, "must not open network"):
            requests.get("http://192.0.2.1/", timeout=1)


if __name__ == "__main__":
    unittest.main()
