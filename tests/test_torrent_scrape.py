"""Tests for torrent_scrape.py: bencode parsing and tracker "scrape" support.

Unlike fetch_torrents.py, this module has no apk-only or container-specific
imports (just requests + stdlib), so it can be imported directly in a plain
test environment.

Run with: python -m unittest discover -s tests
"""
import hashlib
import os
import socket
import struct
import sys
import tempfile
import unittest
import unittest.mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import torrent_scrape as ts


def bstr(s):
    """Hand-rolled bencode byte-string, independent of ts.bencode(), so it
    serves as an oracle rather than testing the implementation against
    itself."""
    b = s if isinstance(s, bytes) else s.encode('utf-8')
    return str(len(b)).encode() + b':' + b


def bint(n):
    return b'i' + str(n).encode() + b'e'


class BdecodeBencodeTests(unittest.TestCase):
    def test_bdecode_integer(self):
        value, index = ts.bdecode(b'i12345e')
        self.assertEqual(value, 12345)
        self.assertEqual(index, 7)

    def test_bdecode_negative_integer(self):
        value, index = ts.bdecode(b'i-42e')
        self.assertEqual(value, -42)

    def test_bdecode_bytestring(self):
        value, index = ts.bdecode(b'4:spam trailing')
        self.assertEqual(value, b'spam')
        self.assertEqual(index, 6)

    def test_bdecode_empty_bytestring(self):
        value, index = ts.bdecode(b'0:')
        self.assertEqual(value, b'')
        self.assertEqual(index, 2)

    def test_bdecode_list(self):
        value, index = ts.bdecode(b'l4:spam4:eggse')
        self.assertEqual(value, [b'spam', b'eggs'])

    def test_bdecode_dict(self):
        value, index = ts.bdecode(b'd3:cow3:moo4:spam4:eggse')
        self.assertEqual(value, {b'cow': b'moo', b'spam': b'eggs'})

    def test_bdecode_nested(self):
        data = b'd4:infod4:name4:test6:lengthi10eee'
        value, _ = ts.bdecode(data)
        self.assertEqual(value, {b'info': {b'name': b'test', b'length': 10}})

    def test_bdecode_invalid_prefix_raises(self):
        with self.assertRaises(ts.BencodeError):
            ts.bdecode(b'x123')

    def test_bencode_roundtrip(self):
        for value in (0, -5, 12345, b'', b'hello', [b'a', b'b'], {b'a': 1, b'b': b'x'}):
            encoded = ts.bencode(value)
            decoded, index = ts.bdecode(encoded)
            self.assertEqual(index, len(encoded))
            self.assertEqual(decoded, value)

    def test_bencode_dict_sorts_keys(self):
        # Insertion order deliberately reversed vs. bencode's required sort order.
        encoded = ts.bencode({b'zebra': 1, b'apple': 2})
        self.assertEqual(encoded, b'd5:applei2e5:zebrai1ee')


class ComputeInfoHashTests(unittest.TestCase):
    def test_matches_sha1_of_raw_info_bytes(self):
        info_bytes = (
            b'd6:lengthi12345e4:name8:test.iso12:piece lengthi16384e'
            b'6:pieces20:' + b'A' * 20 + b'e'
        )
        torrent_bytes = b'd' + bstr('announce') + bstr('http://tracker.example.com:6969/announce') \
            + bstr('info') + info_bytes + b'e'

        expected = hashlib.sha1(info_bytes).digest()
        self.assertEqual(ts.compute_info_hash(torrent_bytes), expected)

    def test_raises_when_info_missing(self):
        torrent_bytes = b'd' + bstr('announce') + bstr('http://tracker.example.com/announce') + b'e'
        with self.assertRaises(ts.BencodeError):
            ts.compute_info_hash(torrent_bytes)


class GetAnnounceUrlsTests(unittest.TestCase):
    def test_combines_announce_list_and_primary_announce(self):
        torrent_bytes = (
            b'd'
            + bstr('announce') + bstr('http://a.example.com/announce')
            + bstr('announce-list')
            + b'l'
            + b'l' + bstr('http://a.example.com/announce') + b'e'
            + b'l' + bstr('http://b.example.com/announce') + b'e'
            + b'e'
            + bstr('info') + b'de'
            + b'e'
        )
        urls = ts.get_announce_urls(torrent_bytes)
        self.assertEqual(urls, [
            'http://a.example.com/announce',
            'http://b.example.com/announce',
        ])

    def test_falls_back_to_bare_announce(self):
        torrent_bytes = b'd' + bstr('announce') + bstr('http://only.example.com/announce') \
            + bstr('info') + b'de' + b'e'
        self.assertEqual(ts.get_announce_urls(torrent_bytes), ['http://only.example.com/announce'])


class DeriveScrapeUrlTests(unittest.TestCase):
    def test_examples_from_the_scrape_convention(self):
        cases = [
            ("http://example.com/announce", "http://example.com/scrape"),
            ("http://example.com/x/announce", "http://example.com/x/scrape"),
            ("http://example.com/announce.php", "http://example.com/scrape.php"),
            ("http://example.com/a/announce?x2%0644", "http://example.com/a/scrape?x2%0644"),
            ("http://example.com/a", None),
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
        self.assertTrue(url.startswith("http://example.com/scrape?info_hash="))

    def test_appends_to_existing_query(self):
        info_hash = bytes(range(20))
        url = ts.build_scrape_request_url("http://example.com/scrape?x=1", info_hash)
        self.assertIn("?x=1&info_hash=", url)

    def test_percent_encoding_roundtrips(self):
        from urllib.parse import urlsplit, parse_qsl, unquote_to_bytes
        info_hash = bytes(range(20))
        url = ts.build_scrape_request_url("http://example.com/scrape", info_hash)
        query = urlsplit(url).query
        raw_value = query.split("info_hash=", 1)[1]
        self.assertEqual(unquote_to_bytes(raw_value), info_hash)


class ParseScrapeResponseTests(unittest.TestCase):
    def test_extracts_seeders_leechers_completed(self):
        info_hash = b'A' * 20
        response = b'd5:filesd' + bstr(info_hash) + b'd8:completei33e10:incompletei73e10:downloadedi9e' + b'ee' + b'e'
        stats = ts.parse_scrape_response(response, info_hash)
        self.assertEqual(stats, {'seeders': 33, 'leechers': 73, 'completed': 9})

    def test_returns_none_when_hash_absent(self):
        response = b'd5:filesdee' + b'e'
        self.assertIsNone(ts.parse_scrape_response(response, b'A' * 20))

    def test_raises_on_failure_reason(self):
        response = b'd14:failure reason7:blockede'
        with self.assertRaises(ts.BencodeError):
            ts.parse_scrape_response(response, b'A' * 20)


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
        self.assertIsNone(ts.parse_udp_tracker_url("udp://tracker.example.com/announce"))

    def test_non_udp_scheme_is_none(self):
        self.assertIsNone(ts.parse_udp_tracker_url("http://tracker.example.com:1337/announce"))


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
        response = _connect_response(transaction_id=42, connection_id=0x1122334455667788)
        connection_id = ts.parse_udp_connect_response(response, transaction_id=42)
        self.assertEqual(connection_id, 0x1122334455667788)

    def test_transaction_id_mismatch_raises(self):
        response = _connect_response(transaction_id=42, connection_id=1)
        with self.assertRaises(ts.UdpTrackerError):
            ts.parse_udp_connect_response(response, transaction_id=99)

    def test_wrong_action_raises(self):
        response = _connect_response(transaction_id=42, connection_id=1, action=2)
        with self.assertRaises(ts.UdpTrackerError):
            ts.parse_udp_connect_response(response, transaction_id=42)

    def test_short_response_raises(self):
        with self.assertRaises(ts.UdpTrackerError):
            ts.parse_udp_connect_response(b'\x00' * 8, transaction_id=42)

    def test_tracker_error_action_raises_with_message(self):
        response = _error_response(transaction_id=42, message="bad request")
        with self.assertRaises(ts.UdpTrackerError) as ctx:
            ts.parse_udp_connect_response(response, transaction_id=42)
        self.assertIn("bad request", str(ctx.exception))


class BuildParseUdpScrapeRequestTests(unittest.TestCase):
    def test_request_matches_bep15_layout(self):
        info_hash = bytes(range(20))
        request = ts.build_udp_scrape_request(
            connection_id=0x1122334455667788, transaction_id=7, info_hash=info_hash,
        )
        connection_id, action, transaction_id = struct.unpack(">QII", request[:16])
        self.assertEqual(connection_id, 0x1122334455667788)
        self.assertEqual(action, 2)
        self.assertEqual(transaction_id, 7)
        self.assertEqual(request[16:], info_hash)

    def test_wrong_length_info_hash_raises(self):
        with self.assertRaises(ts.UdpTrackerError):
            ts.build_udp_scrape_request(connection_id=1, transaction_id=1, info_hash=b'short')

    def test_parses_valid_response(self):
        response = _scrape_response(transaction_id=7, seeders=33, completed=9, leechers=73)
        stats = ts.parse_udp_scrape_response(response, transaction_id=7)
        self.assertEqual(stats, {'seeders': 33, 'leechers': 73, 'completed': 9})

    def test_transaction_id_mismatch_raises(self):
        response = _scrape_response(transaction_id=7, seeders=1, completed=1, leechers=1)
        with self.assertRaises(ts.UdpTrackerError):
            ts.parse_udp_scrape_response(response, transaction_id=8)

    def test_wrong_action_raises(self):
        response = _scrape_response(transaction_id=7, seeders=1, completed=1, leechers=1, action=0)
        with self.assertRaises(ts.UdpTrackerError):
            ts.parse_udp_scrape_response(response, transaction_id=7)

    def test_short_response_raises(self):
        with self.assertRaises(ts.UdpTrackerError):
            ts.parse_udp_scrape_response(b'\x00' * 4, transaction_id=7)

    def test_tracker_error_action_raises_with_message(self):
        response = _error_response(transaction_id=7, message="scrape not supported")
        with self.assertRaises(ts.UdpTrackerError) as ctx:
            ts.parse_udp_scrape_response(response, transaction_id=7)
        self.assertIn("scrape not supported", str(ctx.exception))


class ScrapeUdpTrackerTests(unittest.TestCase):
    """Exercises scrape_udp_tracker()'s socket I/O via a mocked socket, so
    no real network access is required - same spirit as ScrapeTorrentTests
    mocking ts.requests.get for the HTTP path."""

    def _make_fake_socket(self, recvfrom_side_effect):
        fake_sock = unittest.mock.Mock()
        fake_sock.recvfrom.side_effect = recvfrom_side_effect
        return fake_sock

    def test_full_round_trip_returns_stats(self):
        info_hash = b'A' * 20
        connect_resp = _connect_response(transaction_id=0x00000001, connection_id=0xCAFEBABE)
        scrape_resp = _scrape_response(transaction_id=0x00000001, seeders=5, completed=2, leechers=3)
        fake_sock = self._make_fake_socket([
            (connect_resp, ('1.2.3.4', 1337)),
            (scrape_resp, ('1.2.3.4', 1337)),
        ])

        with unittest.mock.patch.object(ts.socket, 'socket', return_value=fake_sock), \
                unittest.mock.patch.object(ts.os, 'urandom', return_value=b'\x00\x00\x00\x01'):
            stats = ts.scrape_udp_tracker('tracker.example.com', 1337, info_hash, timeout=5)

        self.assertEqual(stats, {'seeders': 5, 'leechers': 3, 'completed': 2})
        fake_sock.settimeout.assert_called_once_with(5)
        self.assertEqual(fake_sock.sendto.call_count, 2)
        # Second (scrape) request must carry the connection_id from the connect response.
        scrape_request_bytes = fake_sock.sendto.call_args_list[1][0][0]
        connection_id_sent, action_sent = struct.unpack(">QI", scrape_request_bytes[:12])
        self.assertEqual(connection_id_sent, 0xCAFEBABE)
        self.assertEqual(action_sent, 2)
        fake_sock.close.assert_called_once()

    def test_connect_transaction_mismatch_raises_and_closes_socket(self):
        info_hash = b'A' * 20
        bad_connect_resp = _connect_response(transaction_id=0x00000002, connection_id=1)
        fake_sock = self._make_fake_socket([(bad_connect_resp, ('1.2.3.4', 1337))])

        with unittest.mock.patch.object(ts.socket, 'socket', return_value=fake_sock), \
                unittest.mock.patch.object(ts.os, 'urandom', return_value=b'\x00\x00\x00\x01'):
            with self.assertRaises(ts.UdpTrackerError):
                ts.scrape_udp_tracker('tracker.example.com', 1337, info_hash, timeout=5)

        fake_sock.close.assert_called_once()

    def test_socket_timeout_propagates(self):
        info_hash = b'A' * 20
        fake_sock = unittest.mock.Mock()
        fake_sock.recvfrom.side_effect = socket.timeout("timed out")

        with unittest.mock.patch.object(ts.socket, 'socket', return_value=fake_sock):
            with self.assertRaises(socket.timeout):
                ts.scrape_udp_tracker('tracker.example.com', 1337, info_hash, timeout=5)

        fake_sock.close.assert_called_once()


class IsDisallowedIpTests(unittest.TestCase):
    def test_public_ipv4_is_allowed(self):
        self.assertFalse(ts._is_disallowed_ip('93.184.216.34'))

    def test_private_ipv4_ranges_are_disallowed(self):
        for ip in ('10.0.0.1', '172.16.0.1', '192.168.1.1'):
            with self.subTest(ip=ip):
                self.assertTrue(ts._is_disallowed_ip(ip))

    def test_loopback_is_disallowed(self):
        self.assertTrue(ts._is_disallowed_ip('127.0.0.1'))
        self.assertTrue(ts._is_disallowed_ip('::1'))

    def test_link_local_is_disallowed(self):
        # Cloud metadata endpoint (AWS/GCP/Azure) lives here.
        self.assertTrue(ts._is_disallowed_ip('169.254.169.254'))

    def test_public_ipv6_is_allowed(self):
        self.assertFalse(ts._is_disallowed_ip('2001:4860:4860::8888'))


class IsSafeScrapeHostTests(unittest.TestCase):
    def test_public_address_is_safe(self):
        with unittest.mock.patch.object(ts, '_resolve_addresses', return_value=['93.184.216.34']):
            self.assertTrue(ts._is_safe_scrape_host('tracker.example.com'))

    def test_private_address_is_unsafe(self):
        with unittest.mock.patch.object(ts, '_resolve_addresses', return_value=['10.1.2.3']):
            self.assertFalse(ts._is_safe_scrape_host('tracker.internal'))

    def test_any_disallowed_address_among_several_makes_host_unsafe(self):
        with unittest.mock.patch.object(ts, '_resolve_addresses', return_value=['93.184.216.34', '127.0.0.1']):
            self.assertFalse(ts._is_safe_scrape_host('multi-homed.example.com'))

    def test_resolution_failure_is_unsafe(self):
        with unittest.mock.patch.object(ts, '_resolve_addresses', side_effect=OSError('not known')):
            self.assertFalse(ts._is_safe_scrape_host('nonexistent.invalid'))

    def test_empty_hostname_is_unsafe(self):
        self.assertFalse(ts._is_safe_scrape_host(None))
        self.assertFalse(ts._is_safe_scrape_host(''))


class ScrapeTorrentTests(unittest.TestCase):
    def setUp(self):
        # scrape_torrent() resolves each tracker's host before ever
        # requesting it (see IsSafeScrapeHostTests) - default every test's
        # hosts to a public address so existing tracker-selection behavior
        # doesn't depend on real DNS. Tests of the SSRF guard itself override
        # this per-case.
        patcher = unittest.mock.patch.object(ts, '_resolve_addresses', return_value=['93.184.216.34'])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_torrent(self, announce_urls):
        tiers = b''.join(b'l' + bstr(u) + b'e' for u in announce_urls)
        info_bytes = b'd6:lengthi1e4:name4:teste'
        torrent_bytes = (
            b'd'
            + bstr('announce') + bstr(announce_urls[0])
            + bstr('announce-list') + b'l' + tiers + b'e'
            + bstr('info') + info_bytes
            + b'e'
        )
        fd, path = tempfile.mkstemp(suffix='.torrent')
        with os.fdopen(fd, 'wb') as f:
            f.write(torrent_bytes)
        return path

    def _scrape_response_bytes(self, info_hash, seeders, leechers):
        return b'd5:filesd' + bstr(info_hash) + \
            f'd8:completei{seeders}e10:incompletei{leechers}e10:downloadedi0ee'.encode() + b'ee' + b'e'

    def test_uses_udp_tracker_when_it_succeeds(self):
        path = self._write_torrent([
            'udp://tracker.example.com:80/announce',
            'http://tracker.example.com:6969/announce',
        ])
        with unittest.mock.patch.object(ts, 'scrape_udp_tracker', return_value={
            'seeders': 5, 'leechers': 7, 'completed': 1,
        }) as mock_udp_scrape, unittest.mock.patch.object(ts.requests, 'get') as mock_get:
            result = ts.scrape_torrent(path)

        mock_udp_scrape.assert_called_once()
        mock_get.assert_not_called()
        self.assertEqual(result['seeders'], 5)
        self.assertEqual(result['leechers'], 7)
        self.assertEqual(result['tracker'], 'udp://tracker.example.com:80')

    def test_falls_through_from_failing_udp_tracker_to_http_tracker(self):
        path = self._write_torrent([
            'udp://tracker.example.com:80/announce',
            'http://tracker.example.com:6969/announce',
        ])
        with open(path, 'rb') as f:
            info_hash = ts.compute_info_hash(f.read())
        fake_response = unittest.mock.Mock()
        fake_response.content = self._scrape_response_bytes(info_hash, 5, 7)
        fake_response.raise_for_status = lambda: None

        with unittest.mock.patch.object(ts, 'scrape_udp_tracker', side_effect=OSError("unreachable")), \
                unittest.mock.patch.object(ts.requests, 'get', return_value=fake_response) as mock_get:
            result = ts.scrape_torrent(path)

        mock_get.assert_called_once()
        self.assertIn('tracker.example.com:6969/scrape', mock_get.call_args[0][0])
        self.assertEqual(result['seeders'], 5)
        self.assertEqual(result['leechers'], 7)
        self.assertEqual(result['tracker'], 'http://tracker.example.com:6969/scrape')

    def test_skips_udp_tracker_with_no_port(self):
        """BEP 15 requires an explicit port; an announce URL without one
        can't be dialed, so it should be skipped like any other unusable
        tracker rather than raising."""
        path = self._write_torrent([
            'udp://tracker.example.com/announce',
            'http://tracker.example.com:6969/announce',
        ])
        with open(path, 'rb') as f:
            info_hash = ts.compute_info_hash(f.read())
        fake_response = unittest.mock.Mock()
        fake_response.content = self._scrape_response_bytes(info_hash, 5, 7)
        fake_response.raise_for_status = lambda: None

        with unittest.mock.patch.object(ts, 'scrape_udp_tracker') as mock_udp_scrape, \
                unittest.mock.patch.object(ts.requests, 'get', return_value=fake_response):
            result = ts.scrape_torrent(path)

        mock_udp_scrape.assert_not_called()
        self.assertEqual(result['tracker'], 'http://tracker.example.com:6969/scrape')

    def test_falls_through_to_next_tracker_on_failure(self):
        path = self._write_torrent([
            'http://dead.example.com/announce',
            'http://alive.example.com/announce',
        ])
        with open(path, 'rb') as f:
            info_hash = ts.compute_info_hash(f.read())
        fake_response = unittest.mock.Mock()
        fake_response.content = self._scrape_response_bytes(info_hash, 1, 2)
        fake_response.raise_for_status = lambda: None

        def fake_get(url, timeout=None):
            if 'dead' in url:
                raise ConnectionError("nope")
            return fake_response

        with unittest.mock.patch.object(ts.requests, 'get', side_effect=fake_get):
            result = ts.scrape_torrent(path)

        self.assertEqual(result['seeders'], 1)
        self.assertEqual(result['tracker'], 'http://alive.example.com/scrape')

    def test_returns_none_when_no_tracker_usable(self):
        path = self._write_torrent(['udp://only.example.com:1337/announce'])
        with unittest.mock.patch.object(ts, 'scrape_udp_tracker', side_effect=OSError("unreachable")), \
                unittest.mock.patch.object(ts.requests, 'get') as mock_get:
            result = ts.scrape_torrent(path)
        mock_get.assert_not_called()
        self.assertIsNone(result)

    def test_skips_udp_tracker_resolving_to_a_private_address(self):
        path = self._write_torrent([
            'udp://internal.example.com:1337/announce',
            'http://real-tracker.example.com/announce',
        ])
        with open(path, 'rb') as f:
            info_hash = ts.compute_info_hash(f.read())
        fake_response = unittest.mock.Mock()
        fake_response.content = self._scrape_response_bytes(info_hash, 3, 4)
        fake_response.raise_for_status = lambda: None

        def fake_resolve(hostname):
            if hostname == 'internal.example.com':
                return ['127.0.0.1']
            return ['93.184.216.34']

        with unittest.mock.patch.object(ts, '_resolve_addresses', side_effect=fake_resolve), \
                unittest.mock.patch.object(ts, 'scrape_udp_tracker') as mock_udp_scrape, \
                unittest.mock.patch.object(ts.requests, 'get', return_value=fake_response) as mock_get:
            result = ts.scrape_torrent(path)

        mock_udp_scrape.assert_not_called()
        mock_get.assert_called_once()
        self.assertEqual(result['tracker'], 'http://real-tracker.example.com/scrape')

    def test_skips_tracker_resolving_to_a_private_address(self):
        """A .torrent whose announce URL resolves to an internal address
        (e.g. a compromised upstream mirror pointing at cloud metadata or
        this container's own services) must never be scraped - no request
        should go out to it at all."""
        path = self._write_torrent([
            'http://internal.example.com/announce',
            'http://real-tracker.example.com/announce',
        ])
        with open(path, 'rb') as f:
            info_hash = ts.compute_info_hash(f.read())
        fake_response = unittest.mock.Mock()
        fake_response.content = self._scrape_response_bytes(info_hash, 3, 4)
        fake_response.raise_for_status = lambda: None

        def fake_resolve(hostname):
            if hostname == 'internal.example.com':
                return ['127.0.0.1']
            return ['93.184.216.34']

        with unittest.mock.patch.object(ts, '_resolve_addresses', side_effect=fake_resolve), \
                unittest.mock.patch.object(ts.requests, 'get', return_value=fake_response) as mock_get:
            result = ts.scrape_torrent(path)

        mock_get.assert_called_once()
        self.assertIn('real-tracker.example.com', mock_get.call_args[0][0])
        self.assertEqual(result['tracker'], 'http://real-tracker.example.com/scrape')

    def test_returns_none_when_every_tracker_resolves_privately(self):
        path = self._write_torrent(['http://internal.example.com/announce'])
        with unittest.mock.patch.object(ts, '_resolve_addresses', return_value=['169.254.169.254']), \
                unittest.mock.patch.object(ts.requests, 'get') as mock_get:
            result = ts.scrape_torrent(path)
        mock_get.assert_not_called()
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
