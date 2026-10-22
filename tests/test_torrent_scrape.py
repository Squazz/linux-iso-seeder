"""Tests for torrent_scrape.py: bencode parsing and tracker "scrape" support.

Socket-level tests replace socket.socket with mocks; any real connection
is refused (helpers.block_network()).

Run with: python -m unittest discover -s tests
"""

import hashlib
import inspect
import os
import socket
import struct
import tempfile
import unittest
import unittest.mock

import helpers

import torrent_scrape as ts


def setUpModule():
    helpers.isolate_module()


def bstr(s):
    """Hand-rolled bencode byte-string, independent of ts.bencode(), so it
    serves as an oracle rather than testing the implementation against
    itself."""
    b = s if isinstance(s, bytes) else s.encode("utf-8")
    return str(len(b)).encode() + b":" + b


def bint(n):
    return b"i" + str(n).encode() + b"e"


class BdecodeBencodeTests(unittest.TestCase):
    def test_bdecode_integer(self):
        value, index = ts.bdecode(b"i12345e")
        self.assertEqual(value, 12345)
        self.assertEqual(index, 7)

    def test_bdecode_negative_integer(self):
        value, _index = ts.bdecode(b"i-42e")
        self.assertEqual(value, -42)

    def test_bdecode_bytestring(self):
        value, index = ts.bdecode(b"4:spam trailing")
        self.assertEqual(value, b"spam")
        self.assertEqual(index, 6)

    def test_bdecode_empty_bytestring(self):
        value, index = ts.bdecode(b"0:")
        self.assertEqual(value, b"")
        self.assertEqual(index, 2)

    def test_bdecode_list(self):
        value, _index = ts.bdecode(b"l4:spam4:eggse")
        self.assertEqual(value, [b"spam", b"eggs"])

    def test_bdecode_dict(self):
        value, _index = ts.bdecode(b"d3:cow3:moo4:spam4:eggse")
        self.assertEqual(value, {b"cow": b"moo", b"spam": b"eggs"})

    def test_bdecode_nested(self):
        data = b"d4:infod4:name4:test6:lengthi10eee"
        value, _ = ts.bdecode(data)
        self.assertEqual(value, {b"info": {b"name": b"test", b"length": 10}})

    def test_bdecode_invalid_prefix_raises(self):
        with self.assertRaisesRegex(
            ts.BencodeError, r"Invalid bencode prefix b'x' at index 0"
        ):
            ts.bdecode(b"x123")

    def test_bdecode_malformed_input_raises_bencode_error(self):
        # A truncated .torrent must fail loudly: decoding it silently gives
        # a wrong info dict, hence a wrong info-hash and a bogus scrape.
        cases = {
            b"4:ab": "declares 4 bytes, has 2",
            b"i12": "integer without terminating e",
            b"iabce": "non-numeric integer",
            b"i1_0e": "int() accepts underscores, bencode doesn't",
            b"i e": "blank integer",
            b"2x:ab": "non-numeric length",
            b"12": "length without colon",
            b"l4:spam": "unterminated list",
            b"d3:cow3:moo": "unterminated dict",
        }
        for data, problem in cases.items():
            with (
                self.subTest(problem, data=data),
                self.assertRaisesRegex(ts.BencodeError, r"index \d+"),
            ):
                ts.bdecode(data)

    def test_bdecode_truncated_string_reports_declared_and_remaining_bytes(self):
        with self.assertRaisesRegex(
            ts.BencodeError, r"index 0 declares 4 bytes, only 2 remain"
        ):
            ts.bdecode(b"4:ab")

    def test_bdecode_unterminated_list_reports_end_of_data(self):
        with self.assertRaisesRegex(
            ts.BencodeError, r"Unexpected end of data at index 7"
        ):
            ts.bdecode(b"l4:spam")

    def test_bdecode_truncated_string_inside_container_raises(self):
        with self.assertRaisesRegex(ts.BencodeError, "declares 10 bytes"):
            ts.bdecode(b"d4:info10:shorte")

    def test_bdecode_dict_with_a_non_string_key_raises(self):
        with self.assertRaisesRegex(ts.BencodeError, "Dict keys must be byte strings"):
            ts.bdecode(b"di1e3:mooe")

    def test_bdecode_string_ending_exactly_at_end_of_data_is_accepted(self):
        self.assertEqual(ts.bdecode(b"4:spam"), (b"spam", 6))

    def test_bencode_roundtrip(self):
        for value in (0, -5, 12345, b"", b"hello", [b"a", b"b"], {b"a": 1, b"b": b"x"}):
            encoded = ts.bencode(value)
            decoded, index = ts.bdecode(encoded)
            self.assertEqual(index, len(encoded))
            self.assertEqual(decoded, value)

    def test_bencode_dict_sorts_keys(self):
        # Insertion order deliberately reversed vs. bencode's required sort order.
        encoded = ts.bencode({b"zebra": 1, b"apple": 2})
        self.assertEqual(encoded, b"d5:applei2e5:zebrai1ee")


class BencodeStrTests(unittest.TestCase):
    def test_str_encodes_as_utf8_byte_string(self):
        self.assertEqual(ts.bencode("abc"), b"3:abc")
        # Length is in encoded bytes, not characters.
        self.assertEqual(ts.bencode("æ"), b"2:" + "æ".encode())

    def test_str_keys_encode_like_bytes_keys(self):
        self.assertEqual(
            ts.bencode({"cow": b"moo", "spam": 1}),
            ts.bencode({b"cow": b"moo", b"spam": 1}),
        )

    def test_mixed_keys_are_sorted_by_byte_value(self):
        # "B" (0x42) sorts before "a" (0x61) by byte value.
        self.assertEqual(ts.bencode({"a": 1, b"B": 2}), b"d1:Bi2e1:ai1ee")

    def test_unsupported_types_raise(self):
        for value in (True, 1.5, None, ("tuple",)):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(
                    ts.BencodeError, "is not a bencode type|Cannot bencode type"
                ),
            ):
                ts.bencode(value)


class ComputeInfoHashTests(unittest.TestCase):
    def test_matches_sha1_of_raw_info_bytes(self):
        info_bytes = (
            b"d6:lengthi12345e4:name8:test.iso12:piece lengthi16384e"
            b"6:pieces20:" + b"A" * 20 + b"e"
        )
        torrent_bytes = (
            b"d"
            + bstr("announce")
            + bstr("http://tracker.example.com:6969/announce")
            + bstr("info")
            + info_bytes
            + b"e"
        )

        expected = hashlib.sha1(info_bytes, usedforsecurity=False).digest()
        self.assertEqual(ts.compute_info_hash(torrent_bytes), expected)

    def test_raises_when_info_missing(self):
        torrent_bytes = (
            b"d" + bstr("announce") + bstr("http://tracker.example.com/announce") + b"e"
        )
        with self.assertRaisesRegex(ts.BencodeError, "missing 'info' dictionary"):
            ts.compute_info_hash(torrent_bytes)


class GetAnnounceUrlsTests(unittest.TestCase):
    def test_combines_announce_list_and_primary_announce(self):
        torrent_bytes = (
            b"d"
            + bstr("announce")
            + bstr("http://a.example.com/announce")
            + bstr("announce-list")
            + b"l"
            + b"l"
            + bstr("http://a.example.com/announce")
            + b"e"
            + b"l"
            + bstr("http://b.example.com/announce")
            + b"e"
            + b"e"
            + bstr("info")
            + b"de"
            + b"e"
        )
        urls = ts.get_announce_urls(torrent_bytes)
        self.assertEqual(
            urls,
            [
                "http://a.example.com/announce",
                "http://b.example.com/announce",
            ],
        )

    def test_announce_list_alone_is_de_duplicated_in_tier_order(self):
        torrent_bytes = (
            b"d"
            + bstr("announce-list")
            + b"ll"
            + bstr("http://a.example.com/announce")
            + bstr("http://b.example.com/announce")
            + b"el"
            + bstr("http://a.example.com/announce")
            + b"ee"
            + bstr("info")
            + b"de"
            + b"e"
        )
        self.assertEqual(
            ts.get_announce_urls(torrent_bytes),
            ["http://a.example.com/announce", "http://b.example.com/announce"],
        )

    def test_falls_back_to_bare_announce(self):
        torrent_bytes = (
            b"d"
            + bstr("announce")
            + bstr("http://only.example.com/announce")
            + bstr("info")
            + b"de"
            + b"e"
        )
        self.assertEqual(
            ts.get_announce_urls(torrent_bytes), ["http://only.example.com/announce"]
        )

    def test_primary_announce_missing_from_the_list_goes_first(self):
        torrent_bytes = (
            b"d"
            + bstr("announce")
            + bstr("http://primary.example.com/announce")
            + bstr("announce-list")
            + b"ll"
            + bstr("http://a.example.com/announce")
            + b"el"
            + bstr("http://b.example.com/announce")
            + b"ee"
            + bstr("info")
            + b"de"
            + b"e"
        )
        self.assertEqual(
            ts.get_announce_urls(torrent_bytes),
            [
                "http://primary.example.com/announce",
                "http://a.example.com/announce",
                "http://b.example.com/announce",
            ],
        )


class DeriveScrapeUrlTests(unittest.TestCase):
    def test_examples_from_the_scrape_convention(self):
        cases = [
            ("http://example.com/announce", "http://example.com/scrape"),
            ("http://example.com/x/announce", "http://example.com/x/scrape"),
            ("http://example.com/announce.php", "http://example.com/scrape.php"),
            (
                "http://example.com/a/announce?x2%0644",
                "http://example.com/a/scrape?x2%0644",
            ),
            ("http://example.com/a", None),
            ("https://example.com/announce", "https://example.com/scrape"),
            (
                "https://example.com/x/announce.php?a=1",
                "https://example.com/x/scrape.php?a=1",
            ),
            # 'announce' only counts in the last path segment.
            ("http://example.com/announce/x", None),
            # Only the first 'announce' in the segment is substituted.
            (
                "http://example.com/announce_announce",
                "http://example.com/scrape_announce",
            ),
        ]
        for announce_url, expected in cases:
            with self.subTest(announce_url=announce_url):
                self.assertEqual(ts.derive_scrape_url(announce_url), expected)

    def test_non_http_scheme_unsupported(self):
        self.assertIsNone(ts.derive_scrape_url("udp://tracker.example.com:80/announce"))


class BuildScrapeRequestUrlTests(unittest.TestCase):
    def test_adds_query_param_with_no_existing_query(self):
        info_hash = bytes(range(20))
        url = ts.build_scrape_request_url("http://example.com/scrape", info_hash)
        self.assertEqual(
            url,
            "http://example.com/scrape?info_hash="
            "%00%01%02%03%04%05%06%07%08%09%0A%0B%0C%0D%0E%0F%10%11%12%13",
        )

    def test_appends_to_existing_query(self):
        info_hash = bytes(range(20))
        url = ts.build_scrape_request_url("http://example.com/scrape?x=1", info_hash)
        self.assertIn("?x=1&info_hash=", url)

    def test_percent_encoding_roundtrips(self):
        from urllib.parse import unquote_to_bytes, urlsplit

        info_hash = bytes(range(20))
        url = ts.build_scrape_request_url("http://example.com/scrape", info_hash)
        query = urlsplit(url).query
        raw_value = query.split("info_hash=", 1)[1]
        self.assertEqual(unquote_to_bytes(raw_value), info_hash)


class ParseScrapeResponseTests(unittest.TestCase):
    def test_extracts_seeders_leechers_completed(self):
        info_hash = b"A" * 20
        response = (
            b"d5:filesd"
            + bstr(info_hash)
            + b"d8:completei33e10:incompletei73e10:downloadedi9e"
            + b"ee"
            + b"e"
        )
        stats = ts.parse_scrape_response(response, info_hash)
        self.assertEqual(stats, {"seeders": 33, "leechers": 73, "completed": 9})

    def test_missing_counts_default_to_zero(self):
        info_hash = b"A" * 20
        response = b"d5:filesd" + bstr(info_hash) + b"dee" + b"e"
        self.assertEqual(
            ts.parse_scrape_response(response, info_hash),
            {"seeders": 0, "leechers": 0, "completed": 0},
        )

    def test_returns_none_when_hash_absent(self):
        response = b"d5:filesdee" + b"e"
        self.assertIsNone(ts.parse_scrape_response(response, b"A" * 20))

    def test_raises_on_failure_reason(self):
        response = b"d14:failure reason7:blockede"
        with self.assertRaisesRegex(ts.BencodeError, "^blocked$"):
            ts.parse_scrape_response(response, b"A" * 20)

    def test_non_utf8_failure_reason_is_still_reported_readably(self):
        response = b"d14:failure reason5:bad \xffe"
        with self.assertRaisesRegex(ts.BencodeError, "^bad \ufffd$"):
            ts.parse_scrape_response(response, b"A" * 20)


class ParseUdpTrackerUrlTests(unittest.TestCase):
    def test_udp_url_with_port(self):
        self.assertEqual(
            ts.parse_udp_tracker_url("udp://tracker.example.com:1337/announce"),
            ("tracker.example.com", 1337),
        )

    def test_udp_url_without_path_still_parses(self):
        self.assertEqual(
            ts.parse_udp_tracker_url("udp://tracker.example.com:1337"),
            ("tracker.example.com", 1337),
        )

    def test_missing_port_is_none(self):
        self.assertIsNone(
            ts.parse_udp_tracker_url("udp://tracker.example.com/announce")
        )

    def test_non_udp_scheme_is_none(self):
        self.assertIsNone(
            ts.parse_udp_tracker_url("http://tracker.example.com:1337/announce")
        )


def _connect_response(transaction_id, connection_id, action=0):
    """Hand-rolled BEP 15 connect response, independent of
    ts.build_udp_connect_request()/parse_udp_connect_response(), so it serves
    as an oracle rather than testing the implementation against itself."""
    return struct.pack(">IIQ", action, transaction_id, connection_id)


def _scrape_response(transaction_id, seeders, completed, leechers, action=2):
    return struct.pack(">IIIII", action, transaction_id, seeders, completed, leechers)


def _error_response(transaction_id, message):
    return struct.pack(">II", 3, transaction_id) + message.encode("utf-8")


class BuildParseUdpConnectRequestTests(unittest.TestCase):
    def test_request_matches_bep15_layout(self):
        request = ts.build_udp_connect_request(0xAABBCCDD)
        protocol_id, action, transaction_id = struct.unpack(">QII", request)
        self.assertEqual(protocol_id, 0x41727101980)
        self.assertEqual(action, 0)
        self.assertEqual(transaction_id, 0xAABBCCDD)

    def test_parses_valid_response(self):
        response = _connect_response(
            transaction_id=42, connection_id=0x1122334455667788
        )
        connection_id = ts.parse_udp_connect_response(response, transaction_id=42)
        self.assertEqual(connection_id, 0x1122334455667788)

    def test_transaction_id_mismatch_raises(self):
        response = _connect_response(transaction_id=42, connection_id=1)
        with self.assertRaisesRegex(
            ts.UdpTrackerError, "Transaction ID mismatch in connect response"
        ):
            ts.parse_udp_connect_response(response, transaction_id=99)

    def test_wrong_action_raises(self):
        response = _connect_response(transaction_id=42, connection_id=1, action=2)
        with self.assertRaisesRegex(
            ts.UdpTrackerError, "Unexpected action 2 in connect response"
        ):
            ts.parse_udp_connect_response(response, transaction_id=42)

    def test_short_response_raises_with_its_length(self):
        for length in (8, 15):
            with (
                self.subTest(length=length),
                self.assertRaisesRegex(
                    ts.UdpTrackerError, rf"too short \({length} bytes\)"
                ),
            ):
                ts.parse_udp_connect_response(b"\x00" * length, transaction_id=42)

    def test_trailing_bytes_after_connect_response_are_ignored(self):
        response = _connect_response(transaction_id=42, connection_id=7) + b"xx"
        self.assertEqual(ts.parse_udp_connect_response(response, transaction_id=42), 7)

    def test_error_action_with_empty_message_is_still_a_tracker_error(self):
        # Exactly 8 bytes: action + transaction id, no message text.
        with self.assertRaisesRegex(ts.UdpTrackerError, r"^Tracker error: $"):
            ts.parse_udp_connect_response(
                _error_response(transaction_id=42, message=""), transaction_id=42
            )

    def test_error_action_for_another_transaction_is_not_reported_as_ours(self):
        response = _error_response(transaction_id=99, message="not for you")
        with self.assertRaisesRegex(
            ts.UdpTrackerError, "^Unexpected action 3 in connect response$"
        ):
            ts.parse_udp_connect_response(response, transaction_id=42)

    def test_tracker_error_action_raises_with_message(self):
        response = _error_response(transaction_id=42, message="bad request")
        with self.assertRaisesRegex(ts.UdpTrackerError, "^Tracker error: bad request$"):
            ts.parse_udp_connect_response(response, transaction_id=42)


class BuildParseUdpScrapeRequestTests(unittest.TestCase):
    def test_request_matches_bep15_layout(self):
        info_hash = bytes(range(20))
        request = ts.build_udp_scrape_request(
            connection_id=0x1122334455667788,
            transaction_id=7,
            info_hash=info_hash,
        )
        connection_id, action, transaction_id = struct.unpack(">QII", request[:16])
        self.assertEqual(connection_id, 0x1122334455667788)
        self.assertEqual(action, 2)
        self.assertEqual(transaction_id, 7)
        self.assertEqual(request[16:], info_hash)

    def test_wrong_length_info_hash_raises(self):
        with self.assertRaisesRegex(
            ts.UdpTrackerError, "info_hash must be 20 bytes, got 5"
        ):
            ts.build_udp_scrape_request(
                connection_id=1, transaction_id=1, info_hash=b"short"
            )

    def test_parses_valid_response(self):
        response = _scrape_response(
            transaction_id=7, seeders=33, completed=9, leechers=73
        )
        stats = ts.parse_udp_scrape_response(response, transaction_id=7)
        self.assertEqual(stats, {"seeders": 33, "leechers": 73, "completed": 9})

    def test_transaction_id_mismatch_raises(self):
        response = _scrape_response(
            transaction_id=7, seeders=1, completed=1, leechers=1
        )
        with self.assertRaisesRegex(
            ts.UdpTrackerError, "Transaction ID mismatch in scrape response"
        ):
            ts.parse_udp_scrape_response(response, transaction_id=8)

    def test_wrong_action_raises(self):
        response = _scrape_response(
            transaction_id=7, seeders=1, completed=1, leechers=1, action=0
        )
        with self.assertRaisesRegex(
            ts.UdpTrackerError, "Unexpected action 0 in scrape response"
        ):
            ts.parse_udp_scrape_response(response, transaction_id=7)

    def test_non_utf8_tracker_error_is_still_reported_readably(self):
        response = struct.pack(">II", 3, 7) + b"bad \xff"
        with self.assertRaisesRegex(ts.UdpTrackerError, "^Tracker error: bad \ufffd$"):
            ts.parse_udp_scrape_response(response, transaction_id=7)

    def test_short_response_raises_with_its_length(self):
        # 19 bytes is one short of the stats for a single hash.
        full = _scrape_response(7, seeders=1, completed=1, leechers=1)
        for length in (4, 19):
            with (
                self.subTest(length=length),
                self.assertRaisesRegex(
                    ts.UdpTrackerError, rf"too short \({length} bytes\)"
                ),
            ):
                ts.parse_udp_scrape_response(full[:length], transaction_id=7)

    def test_trailing_bytes_after_first_hash_are_ignored(self):
        response = (
            _scrape_response(7, seeders=1, completed=2, leechers=3) + b"\x00" * 12
        )
        self.assertEqual(
            ts.parse_udp_scrape_response(response, transaction_id=7),
            {"seeders": 1, "leechers": 3, "completed": 2},
        )

    def test_tracker_error_action_raises_with_message(self):
        response = _error_response(transaction_id=7, message="scrape not supported")
        with self.assertRaisesRegex(
            ts.UdpTrackerError, "^Tracker error: scrape not supported$"
        ):
            ts.parse_udp_scrape_response(response, transaction_id=7)


class ScrapeUdpTrackerTests(unittest.TestCase):
    """Exercises scrape_udp_tracker()'s socket I/O against an autospec'd
    socket (so a mistyped socket method fails) and a fixed transaction id
    sequence, so no real network access or randomness is involved."""

    INFO_HASH = bytes(range(20))
    ADDR = ("tracker.example.com", 1337)

    def _scrape(self, replies, ids=(1, 2), **kwargs):
        """Runs scrape_udp_tracker with `replies` as what recvfrom returns
        (or raises); returns (result or raised exception, fake socket)."""
        fake_sock = unittest.mock.create_autospec(socket.socket, instance=True)
        fake_sock.recvfrom.side_effect = replies
        with unittest.mock.patch.object(ts.socket, "socket", return_value=fake_sock):
            result = ts.scrape_udp_tracker(
                *self.ADDR,
                self.INFO_HASH,
                new_transaction_id=iter(ids).__next__,
                **kwargs,
            )
        return result, fake_sock

    def test_full_round_trip_sends_both_bep15_requests_and_returns_stats(self):
        stats, fake_sock = self._scrape(
            [
                (_connect_response(transaction_id=1, connection_id=0xCAFEBABE), None),
                (_scrape_response(2, seeders=5, completed=2, leechers=3), None),
            ],
            timeout=5,
        )

        self.assertEqual(stats, {"seeders": 5, "leechers": 3, "completed": 2})
        fake_sock.settimeout.assert_called_once_with(5)
        self.assertEqual(
            fake_sock.sendto.call_args_list,
            [
                unittest.mock.call(struct.pack(">QII", 0x41727101980, 0, 1), self.ADDR),
                unittest.mock.call(
                    struct.pack(">QII", 0xCAFEBABE, 2, 2) + self.INFO_HASH, self.ADDR
                ),
            ],
        )
        fake_sock.close.assert_called_once()

    def test_scrape_uses_a_fresh_transaction_id_not_the_connect_one(self):
        # A reply to the scrape that echoes the connect's id is not ours.
        with self.assertRaisesRegex(
            ts.UdpTrackerError, "Transaction ID mismatch in scrape response"
        ):
            self._scrape(
                [
                    (_connect_response(transaction_id=1, connection_id=9), None),
                    (_scrape_response(1, seeders=5, completed=2, leechers=3), None),
                ]
            )

    def test_default_timeout_is_15_seconds(self):
        fake_sock = unittest.mock.create_autospec(socket.socket, instance=True)
        fake_sock.recvfrom.side_effect = TimeoutError("timed out")

        with (
            unittest.mock.patch.object(ts.socket, "socket", return_value=fake_sock),
            self.assertRaisesRegex(socket.timeout, "timed out"),
        ):
            ts.scrape_udp_tracker(
                *self.ADDR, self.INFO_HASH, new_transaction_id=lambda: 1
            )

        fake_sock.settimeout.assert_called_once_with(15)

    def test_connect_transaction_mismatch_raises_and_closes_socket(self):
        fake_sock = unittest.mock.create_autospec(socket.socket, instance=True)
        fake_sock.recvfrom.side_effect = [
            (_connect_response(transaction_id=2, connection_id=1), None)
        ]

        with (
            unittest.mock.patch.object(ts.socket, "socket", return_value=fake_sock),
            self.assertRaisesRegex(
                ts.UdpTrackerError, "Transaction ID mismatch in connect response"
            ),
        ):
            ts.scrape_udp_tracker(
                *self.ADDR, self.INFO_HASH, new_transaction_id=lambda: 1
            )

        fake_sock.close.assert_called_once()

    def test_socket_timeout_propagates_and_closes_socket(self):
        fake_sock = unittest.mock.create_autospec(socket.socket, instance=True)
        fake_sock.recvfrom.side_effect = TimeoutError("timed out")

        with (
            unittest.mock.patch.object(ts.socket, "socket", return_value=fake_sock),
            self.assertRaisesRegex(socket.timeout, "timed out"),
        ):
            ts.scrape_udp_tracker(*self.ADDR, self.INFO_HASH, timeout=5)

        fake_sock.close.assert_called_once()

    def test_opens_a_udp_socket(self):
        fake_sock = unittest.mock.create_autospec(socket.socket, instance=True)
        fake_sock.recvfrom.side_effect = TimeoutError("timed out")

        with (
            unittest.mock.patch.object(
                ts.socket, "socket", return_value=fake_sock
            ) as make_socket,
            self.assertRaises(socket.timeout),
        ):
            ts.scrape_udp_tracker(*self.ADDR, self.INFO_HASH)

        make_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)


class RandomTransactionIdTests(unittest.TestCase):
    def test_is_four_random_bytes_read_big_endian(self):
        with unittest.mock.patch.object(
            ts.os, "urandom", return_value=b"\x01\x02\x03\x04"
        ) as urandom:
            self.assertEqual(ts._random_transaction_id(), 0x01020304)

        urandom.assert_called_once_with(4)

    def test_is_the_default_id_source(self):
        default = (
            inspect.signature(ts.scrape_udp_tracker)
            .parameters["new_transaction_id"]
            .default
        )

        self.assertIs(default, ts._random_transaction_id)


class IsDisallowedIpTests(unittest.TestCase):
    def test_public_ipv4_is_allowed(self):
        self.assertFalse(ts._is_disallowed_ip("93.184.216.34"))

    def test_private_ipv4_ranges_are_disallowed(self):
        for ip in ("10.0.0.1", "172.16.0.1", "192.168.1.1"):
            with self.subTest(ip=ip):
                self.assertTrue(ts._is_disallowed_ip(ip))

    def test_loopback_is_disallowed(self):
        self.assertTrue(ts._is_disallowed_ip("127.0.0.1"))
        self.assertTrue(ts._is_disallowed_ip("::1"))

    def test_link_local_is_disallowed(self):
        # Cloud metadata endpoint (AWS/GCP/Azure) lives here.
        self.assertTrue(ts._is_disallowed_ip("169.254.169.254"))

    def test_public_ipv6_is_allowed(self):
        self.assertFalse(ts._is_disallowed_ip("2001:4860:4860::8888"))

    def test_multicast_is_disallowed(self):
        for ip in ("224.0.0.1", "239.255.255.250", "ff02::1"):
            with self.subTest(ip=ip):
                self.assertTrue(ts._is_disallowed_ip(ip))

    def test_unspecified_address_is_disallowed(self):
        # Connecting to 0.0.0.0 / :: reaches this host on most systems.
        for ip in ("0.0.0.0", "::"):
            with self.subTest(ip=ip):
                self.assertTrue(ts._is_disallowed_ip(ip))

    def test_ipv4_mapped_internal_addresses_are_disallowed(self):
        # The Docker build runs this suite under Alpine's Python too, so
        # this also holds there, not only on a developer's interpreter.
        for ip in ("::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254"):
            with self.subTest(ip=ip):
                self.assertTrue(ts._is_disallowed_ip(ip))

    def test_ipv4_mapped_public_address_is_allowed(self):
        self.assertFalse(ts._is_disallowed_ip("::ffff:93.184.216.34"))


class ResolveAddressesTests(unittest.TestCase):
    def test_returns_the_ip_of_every_getaddrinfo_entry(self):
        infos = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800::1", 0, 0, 0)),
        ]
        with unittest.mock.patch.object(
            ts.socket, "getaddrinfo", return_value=infos
        ) as getaddrinfo:
            addresses = ts._resolve_addresses("tracker.example.com")

        self.assertEqual(addresses, ["93.184.216.34", "2606:2800::1"])
        getaddrinfo.assert_called_once_with("tracker.example.com", None)


class IsSafeScrapeHostTests(unittest.TestCase):
    def _is_safe(self, hostname, addresses):
        """_is_safe_scrape_host with hostname resolving to `addresses` (or
        raising them, if an exception)."""

        def resolve(_hostname):
            if isinstance(addresses, Exception):
                raise addresses
            return addresses

        return ts._is_safe_scrape_host(hostname, resolve)

    def test_public_address_is_safe(self):
        self.assertTrue(self._is_safe("tracker.example.com", ["93.184.216.34"]))

    def test_private_address_is_unsafe(self):
        self.assertFalse(self._is_safe("tracker.internal", ["10.1.2.3"]))

    def test_any_disallowed_address_among_several_makes_host_unsafe(self):
        self.assertFalse(
            self._is_safe("multi-homed.example.com", ["93.184.216.34", "127.0.0.1"])
        )

    def test_resolving_to_no_addresses_is_unsafe(self):
        self.assertFalse(self._is_safe("tracker.example.com", []))

    def test_resolution_failure_is_unsafe(self):
        self.assertFalse(self._is_safe("nonexistent.invalid", OSError("not known")))

    def test_empty_hostname_is_unsafe(self):
        self.assertFalse(self._is_safe(None, [PUBLIC_IP]))
        self.assertFalse(self._is_safe("", [PUBLIC_IP]))


PUBLIC_IP = "93.184.216.34"


def resolve_private(*private_hosts):
    """A resolve= stand-in: loopback for private_hosts, a public
    address for every other host."""

    def resolve(hostname):
        return ["127.0.0.1"] if hostname in private_hosts else [PUBLIC_IP]

    return resolve


def percent_encoded(raw):
    """RFC 3986 percent-encoding of raw bytes, written independently of
    urllib so it serves as an oracle for build_scrape_request_url()."""
    unreserved = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    return "".join(chr(b) if b in unreserved else f"%{b:02X}" for b in raw)


def tracker_response(info_hash, seeders, leechers, completed=0):
    """A real HTTP response carrying a bencoded scrape for info_hash."""
    return helpers.fake_response(
        b"d5:filesd"
        + bstr(info_hash)
        + b"d8:complete"
        + bint(seeders)
        + b"10:incomplete"
        + bint(leechers)
        + b"10:downloaded"
        + bint(completed)
        + b"eee"
    )


OTHER_HASH = b"\x01" * 20


UDP_STATS = {"seeders": 5, "leechers": 7, "completed": 1}


def write_torrent(testcase, announce_urls):
    """Writes a .torrent with these trackers, removed after `testcase`;
    returns (path, info_hash)."""
    tiers = b"".join(b"l" + bstr(u) + b"e" for u in announce_urls)
    info_bytes = b"d6:lengthi1e4:name4:teste"
    torrent_bytes = (
        b"d"
        + bstr("announce")
        + bstr(announce_urls[0])
        + bstr("announce-list")
        + b"l"
        + tiers
        + b"e"
        + bstr("info")
        + info_bytes
        + b"e"
    )
    fd, path = tempfile.mkstemp(suffix=".torrent")
    testcase.addCleanup(os.remove, path)
    with os.fdopen(fd, "wb") as f:
        f.write(torrent_bytes)
    return path, hashlib.sha1(info_bytes, usedforsecurity=False).digest()


class ScrapeTorrentTests(unittest.TestCase):
    """scrape_torrent()'s tracker selection, with DNS and the UDP round trip
    injected (resolve=, udp_scrape=) and requests.get doubled. The real
    defaults are exercised by ScrapeTorrentUdpWireTests."""

    def _scrape(self, path, *, private=(), udp=UDP_STATS, **kwargs):
        """Runs scrape_torrent(path) with every host resolving publicly
        except `private`, and every UDP tracker answering `udp` (stats, or
        an exception to raise). The default answers, so a test expecting a
        UDP tracker to be skipped sees it in the result if it wasn't."""

        def udp_scrape(host, port, info_hash, timeout):
            if isinstance(udp, Exception):
                raise udp
            return udp

        return ts.scrape_torrent(
            path, resolve=resolve_private(*private), udp_scrape=udp_scrape, **kwargs
        )

    def test_resolves_and_udp_scrapes_through_the_injected_seams(self):
        path, info_hash = write_torrent(self, ["udp://tracker.example.com:80/announce"])
        resolved, scraped = [], []

        def resolve(hostname):
            resolved.append(hostname)
            return [PUBLIC_IP]

        def udp_scrape(host, port, scraped_hash, timeout):
            scraped.append((host, port, scraped_hash, timeout))
            return {"seeders": 5, "leechers": 7, "completed": 1}

        result = ts.scrape_torrent(
            path, timeout=3, resolve=resolve, udp_scrape=udp_scrape
        )

        self.assertEqual(resolved, ["tracker.example.com"])
        self.assertEqual(scraped, [("tracker.example.com", 80, info_hash, 3)])
        self.assertEqual(
            result,
            {
                "tracker": "udp://tracker.example.com:80",
                "seeders": 5,
                "leechers": 7,
                "completed": 1,
            },
        )

    def test_uses_udp_tracker_when_it_succeeds(self):
        path, _info_hash = write_torrent(
            self,
            [
                "udp://tracker.example.com:80/announce",
                "http://tracker.example.com:6969/announce",
            ],
        )
        with unittest.mock.patch.object(ts.requests, "get") as mock_get:
            result = self._scrape(path)

        mock_get.assert_not_called()
        self.assertEqual(
            result, {"tracker": "udp://tracker.example.com:80", **UDP_STATS}
        )

    def test_falls_through_from_failing_udp_tracker_to_http_tracker(self):
        path, info_hash = write_torrent(
            self,
            [
                "udp://tracker.example.com:80/announce",
                "http://tracker.example.com:6969/announce",
            ],
        )
        with unittest.mock.patch.object(
            ts.requests,
            "get",
            return_value=tracker_response(info_hash, 5, 7, completed=2),
        ) as mock_get:
            result = self._scrape(path, udp=OSError("unreachable"), timeout=3)

        self.assertEqual(
            mock_get.call_args_list,
            [
                unittest.mock.call(
                    "http://tracker.example.com:6969/scrape?info_hash="
                    + percent_encoded(info_hash),
                    timeout=3,
                )
            ],
        )
        self.assertEqual(
            result,
            {
                "tracker": "http://tracker.example.com:6969/scrape",
                "seeders": 5,
                "leechers": 7,
                "completed": 2,
            },
        )

    def test_skips_udp_tracker_with_no_port(self):
        """BEP 15 requires an explicit port; an announce URL without one
        can't be dialed, so it should be skipped like any other unusable
        tracker rather than raising."""
        path, info_hash = write_torrent(
            self,
            [
                "udp://tracker.example.com/announce",
                "http://tracker.example.com:6969/announce",
            ],
        )
        with unittest.mock.patch.object(
            ts.requests, "get", return_value=tracker_response(info_hash, 3, 4)
        ):
            result = self._scrape(path)

        self.assertEqual(result["tracker"], "http://tracker.example.com:6969/scrape")

    def test_falls_through_to_the_next_http_tracker(self):
        """Tracker A is unusable in each way scrape_torrent() tolerates;
        tracker B answers. A's failure must not end the search."""
        good = "http://good.example.com/announce"
        dead = "http://dead.example.com/announce"
        # case -> (A's announce URL, A's answer: a response or an exception
        # to raise, and the trackers requested, in order)
        cases = {
            "connection error": (dead, ConnectionError("nope"), ("A", "B")),
            "HTTP status error": (dead, helpers.fake_response(status=500), ("A", "B")),
            "failure reason": (
                dead,
                helpers.fake_response(b"d14:failure reason11:not allowede"),
                ("A", "B"),
            ),
            "no stats for this hash": (
                dead,
                tracker_response(OTHER_HASH, 9, 9),
                ("A", "B"),
            ),
            "no announce segment": ("http://dead.example.com/tracker", None, ("B",)),
        }
        for case, (announce, dead_answer, requested) in cases.items():
            with self.subTest(case):
                path, info_hash = write_torrent(self, [announce, good])
                query = "/scrape?info_hash=" + percent_encoded(info_hash)
                urls = {
                    "A": "http://dead.example.com" + query,
                    "B": "http://good.example.com" + query,
                }
                http = helpers.FakeHttp(
                    {
                        urls["A"]: dead_answer,
                        urls["B"]: tracker_response(info_hash, 1, 2, completed=3),
                    }
                )

                with unittest.mock.patch.object(ts.requests, "get", http.get):
                    result = self._scrape(path, timeout=3)

                self.assertEqual(
                    http.requests, [(urls[tracker], 3) for tracker in requested]
                )
                self.assertEqual(
                    result,
                    {
                        "tracker": "http://good.example.com/scrape",
                        "seeders": 1,
                        "leechers": 2,
                        "completed": 3,
                    },
                )

    def test_default_http_timeout_is_15_seconds(self):
        path, info_hash = write_torrent(self, ["http://good.example.com/announce"])
        with unittest.mock.patch.object(
            ts.requests, "get", return_value=tracker_response(info_hash, 1, 2)
        ) as mock_get:
            self._scrape(path)

        self.assertEqual(mock_get.call_args.kwargs, {"timeout": 15})

    def test_returns_none_when_no_tracker_usable(self):
        path, _info_hash = write_torrent(self, ["udp://only.example.com:1337/announce"])
        with unittest.mock.patch.object(ts.requests, "get") as mock_get:
            result = self._scrape(path, udp=OSError("unreachable"))
        mock_get.assert_not_called()
        self.assertIsNone(result)

    def test_returns_none_when_no_tracker_has_stats_for_the_hash(self):
        path, _info_hash = write_torrent(self, ["http://good.example.com/announce"])
        with unittest.mock.patch.object(
            ts.requests, "get", return_value=tracker_response(OTHER_HASH, 9, 9)
        ):
            self.assertIsNone(self._scrape(path))

    def test_skips_udp_tracker_resolving_to_a_private_address(self):
        path, info_hash = write_torrent(
            self,
            [
                "udp://internal.example.com:1337/announce",
                "http://real-tracker.example.com/announce",
            ],
        )
        with unittest.mock.patch.object(
            ts.requests, "get", return_value=tracker_response(info_hash, 3, 4)
        ):
            result = self._scrape(path, private=("internal.example.com",))

        self.assertEqual(
            result,
            {
                "tracker": "http://real-tracker.example.com/scrape",
                "seeders": 3,
                "leechers": 4,
                "completed": 0,
            },
        )

    def test_skips_tracker_resolving_to_a_private_address(self):
        """A .torrent whose announce URL resolves to an internal address
        (e.g. a compromised upstream mirror pointing at cloud metadata or
        this container's own services) must never be scraped - no request
        should go out to it at all."""
        path, info_hash = write_torrent(
            self,
            [
                "http://internal.example.com/announce",
                "http://real-tracker.example.com/announce",
            ],
        )
        with unittest.mock.patch.object(
            ts.requests, "get", return_value=tracker_response(info_hash, 3, 4)
        ) as mock_get:
            result = self._scrape(path, private=("internal.example.com",))

        self.assertEqual(
            mock_get.call_args_list,
            [
                unittest.mock.call(
                    "http://real-tracker.example.com/scrape?info_hash="
                    + percent_encoded(info_hash),
                    timeout=15,
                )
            ],
        )
        self.assertEqual(result["tracker"], "http://real-tracker.example.com/scrape")

    def test_returns_none_when_every_tracker_resolves_privately(self):
        path, _info_hash = write_torrent(self, ["http://internal.example.com/announce"])
        with unittest.mock.patch.object(ts.requests, "get") as mock_get:
            result = ts.scrape_torrent(
                path,
                resolve=lambda _hostname: ["169.254.169.254"],
            )
        mock_get.assert_not_called()
        self.assertIsNone(result)


class ScrapeTorrentUdpWireTests(unittest.TestCase):
    """scrape_torrent() with its real resolve=/udp_scrape= defaults, down to
    socket.getaddrinfo and an autospec'd UDP socket: what goes on the wire
    for a public tracker, and that nothing does for a private one."""

    ANNOUNCE = "udp://tracker.example.com:80/announce"

    def _scrape(self, address, replies=()):
        """Runs scrape_torrent on a one-UDP-tracker .torrent whose host
        resolves to `address`, with `replies` as what recvfrom returns and
        transaction ids 1, 2. Returns (result, info_hash, fake socket)."""
        path, info_hash = write_torrent(self, [self.ANNOUNCE])
        fake_sock = unittest.mock.create_autospec(socket.socket, instance=True)
        fake_sock.recvfrom.side_effect = replies
        infos = [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", (address, 0))]
        ids = [(1).to_bytes(4, "big"), (2).to_bytes(4, "big")]
        with (
            unittest.mock.patch.object(ts.socket, "getaddrinfo", return_value=infos),
            unittest.mock.patch.object(ts.socket, "socket", return_value=fake_sock),
            unittest.mock.patch.object(ts.os, "urandom", side_effect=ids),
        ):
            result = ts.scrape_torrent(path)
        return result, info_hash, fake_sock

    def test_public_tracker_is_scraped_over_bep15(self):
        result, info_hash, fake_sock = self._scrape(
            PUBLIC_IP,
            [
                (_connect_response(transaction_id=1, connection_id=0xCAFEBABE), None),
                (_scrape_response(2, seeders=5, completed=2, leechers=3), None),
            ],
        )

        addr = ("tracker.example.com", 80)
        self.assertEqual(
            fake_sock.sendto.call_args_list,
            [
                unittest.mock.call(struct.pack(">QII", 0x41727101980, 0, 1), addr),
                unittest.mock.call(
                    struct.pack(">QII", 0xCAFEBABE, 2, 2) + info_hash, addr
                ),
            ],
        )
        fake_sock.settimeout.assert_called_once_with(15)
        self.assertEqual(
            result,
            {
                "tracker": "udp://tracker.example.com:80",
                "seeders": 5,
                "leechers": 3,
                "completed": 2,
            },
        )

    def test_private_tracker_gets_no_packet(self):
        result, _info_hash, fake_sock = self._scrape("127.0.0.1")

        fake_sock.sendto.assert_not_called()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
