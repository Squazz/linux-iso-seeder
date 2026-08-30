"""Tests for torrent_scrape.py: bencode parsing and tracker "scrape" support.

Unlike fetch_torrents.py, this module has no apk-only or container-specific
imports (just requests + stdlib), so it can be imported directly in a plain
test environment.

Run with: python -m unittest discover -s tests
"""
import hashlib
import os
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


class ScrapeTorrentTests(unittest.TestCase):
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

    def test_skips_udp_tracker_and_scrapes_first_http_tracker(self):
        path = self._write_torrent([
            'udp://tracker.example.com:80/announce',
            'http://tracker.example.com:6969/announce',
        ])
        with open(path, 'rb') as f:
            info_hash = ts.compute_info_hash(f.read())
        fake_response = unittest.mock.Mock()
        fake_response.content = self._scrape_response_bytes(info_hash, 5, 7)
        fake_response.raise_for_status = lambda: None

        with unittest.mock.patch.object(ts.requests, 'get', return_value=fake_response) as mock_get:
            result = ts.scrape_torrent(path)

        mock_get.assert_called_once()
        self.assertIn('tracker.example.com:6969/scrape', mock_get.call_args[0][0])
        self.assertEqual(result['seeders'], 5)
        self.assertEqual(result['leechers'], 7)
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
        path = self._write_torrent(['udp://only.example.com/announce'])
        with unittest.mock.patch.object(ts.requests, 'get') as mock_get:
            result = ts.scrape_torrent(path)
        mock_get.assert_not_called()
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
