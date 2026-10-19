"""The Transmission doubles in tests/helpers.py must not drift from the real
transmission_rpc library (pinned in requirements-test.txt to the version
Alpine's py3-transmission-rpc ships): a call production code makes that the
real Client wouldn't accept has to fail here, not in the container.

Run with: python -m unittest discover -s tests
"""

import unittest

import helpers
import transmission_rpc


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


if __name__ == "__main__":
    unittest.main()
