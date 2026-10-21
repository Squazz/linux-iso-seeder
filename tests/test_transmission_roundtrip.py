"""Tests for the offline parts of scripts/transmission_roundtrip.py (the
drift job's real-daemon check): the polling loop, with its clock injected,
and the throwaway .torrent it seeds. main() itself is the integration check
against a real transmission-daemon, so it is only run there.

Run with: python -m unittest discover -s tests
"""

import unittest

import helpers

import torrent_scrape

roundtrip = helpers.load_script("transmission_roundtrip")


def setUpModule():
    helpers.isolate_module()


class WaitForTests(unittest.TestCase):
    def setUp(self):
        self.clock = helpers.FakeClock()
        self.polls = 0

    def ready_after(self, polls, result="torrent"):
        """A predicate that is falsy for its first `polls` calls."""

        def predicate():
            self.polls += 1
            return result if self.polls > polls else None

        return predicate

    def wait(self, predicate, **kwargs):
        return roundtrip.wait_for(
            "the torrent",
            predicate,
            clock=self.clock,
            sleep=self.clock.sleep,
            **kwargs,
        )

    def test_returns_the_first_truthy_result_without_sleeping(self):
        self.assertEqual(self.wait(self.ready_after(0)), "torrent")

        self.assertEqual(self.polls, 1)
        self.assertEqual(self.clock.sleeps, [])

    def test_polls_every_two_seconds_until_the_predicate_holds(self):
        self.assertEqual(self.wait(self.ready_after(3, result=[1])), [1])

        self.assertEqual(self.polls, 4)
        self.assertEqual(self.clock.sleeps, [2, 2, 2])

    def test_any_falsy_result_keeps_polling(self):
        # The removal check's all(...) is False, not None, until it holds.
        results = iter([False, [], 0, True])

        self.assertIs(self.wait(lambda: next(results)), True)

        self.assertEqual(self.clock.sleeps, [2, 2, 2])

    def test_times_out_with_a_failure_naming_what_it_waited_for(self):
        with self.assertRaises(SystemExit) as raised:
            self.wait(self.ready_after(1000), timeout=10)

        self.assertEqual(
            str(raised.exception), "FAILED: timed out waiting for the torrent"
        )
        # Polls at t=0,2,4,6,8; at t=10 the deadline has passed.
        self.assertEqual(self.polls, 5)
        self.assertEqual(self.clock.now, 10)

    def test_succeeds_on_the_last_poll_before_the_deadline(self):
        self.assertEqual(self.wait(self.ready_after(4), timeout=10), "torrent")

        self.assertEqual(self.polls, 5)

    def test_timeout_defaults_to_the_module_setting(self):
        with self.assertRaises(SystemExit):
            self.wait(self.ready_after(1000))

        self.assertEqual(self.clock.now, roundtrip.TIMEOUT_SECONDS)

    def test_a_system_exit_from_the_predicate_propagates(self):
        def predicate():
            raise SystemExit("FAILED: daemon went away")

        with self.assertRaises(SystemExit) as raised:
            self.wait(predicate)

        self.assertEqual(str(raised.exception), "FAILED: daemon went away")
        self.assertEqual(self.clock.sleeps, [])


class MakeTorrentTests(unittest.TestCase):
    def decode(self, data):
        value, end = torrent_scrape.bdecode(data)
        self.assertEqual(end, len(data))
        return value

    def test_is_a_single_16_byte_file_with_no_trackers(self):
        torrent = self.decode(roundtrip.make_torrent("drift-check-0a1b2c3d.bin"))

        # No announce/announce-list: the daemon never contacts a tracker.
        self.assertEqual(list(torrent), [b"info"])
        info = torrent[b"info"]
        self.assertEqual(sorted(info), [b"length", b"name", b"piece length", b"pieces"])
        self.assertEqual(info[b"name"], b"drift-check-0a1b2c3d.bin")
        self.assertEqual(info[b"length"], 16)
        self.assertEqual(info[b"piece length"], 16384)
        # One piece, so one SHA-1 digest.
        self.assertEqual(len(info[b"pieces"]), 20)

    def test_each_torrent_has_fresh_content(self):
        first = self.decode(roundtrip.make_torrent("a.bin"))
        second = self.decode(roundtrip.make_torrent("a.bin"))

        self.assertNotEqual(first[b"info"][b"pieces"], second[b"info"][b"pieces"])


if __name__ == "__main__":
    unittest.main()
