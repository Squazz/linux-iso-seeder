"""Tests for the test doubles and guards in tests/helpers.py.

The Transmission doubles must not drift from the real transmission_rpc
library (pinned in requirements-test.txt to the version Alpine's
py3-transmission-rpc ships): a call production code makes that the real
Client wouldn't accept has to fail here, not in the container. And
isolate_module() must really keep tests off the network.

Run with: python -m unittest discover -s tests
"""

import unittest

import helpers
import requests
import transmission_rpc


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


class NetworkGuardTests(unittest.TestCase):
    def test_real_connections_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, "must not open network"):
            requests.get("http://192.0.2.1/", timeout=1)


if __name__ == "__main__":
    unittest.main()
