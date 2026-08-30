#!/usr/bin/env python3
"""Bencode parsing and BitTorrent tracker "scrape" support.

Scrape is a separate endpoint from announce: it returns aggregate
seeder/leecher/completed counts for one or more info-hashes without
registering the caller as a peer or joining the swarm at all. This lets a
seeder check whether a torrent has any real demand before ever downloading
or seeding it - no artificial demand required.

Only HTTP(S) trackers are supported. UDP-only trackers use a different
(binary, BEP 15) protocol that isn't implemented here; callers should just
move on to the torrent's next tracker.
"""
import hashlib
from urllib.parse import urlsplit, urlunsplit, quote_from_bytes

import requests


class BencodeError(ValueError):
    pass


def bdecode(data, index=0):
    """Decode a single bencoded value starting at index. Returns (value,
    next_index). Byte strings decode to bytes, dict keys must be byte
    strings (per spec) and dicts decode with keys as bytes."""
    if index >= len(data):
        raise BencodeError("Unexpected end of data")

    prefix = data[index:index + 1]

    if prefix == b'i':
        end = data.index(b'e', index)
        return int(data[index + 1:end]), end + 1

    if prefix.isdigit():
        colon = data.index(b':', index)
        length = int(data[index:colon])
        start = colon + 1
        end = start + length
        return data[start:end], end

    if prefix == b'l':
        index += 1
        items = []
        while data[index:index + 1] != b'e':
            item, index = bdecode(data, index)
            items.append(item)
        return items, index + 1

    if prefix == b'd':
        index += 1
        result = {}
        while data[index:index + 1] != b'e':
            key, index = bdecode(data, index)
            if not isinstance(key, bytes):
                raise BencodeError("Dict keys must be byte strings")
            value, index = bdecode(data, index)
            result[key] = value
        return result, index + 1

    raise BencodeError(f"Invalid bencode prefix {prefix!r} at index {index}")


def bencode(value):
    """Canonical bencode of value. Dict keys are sorted, matching the only
    valid encoding for a given decoded value - so re-encoding a bdecode()
    result reproduces the original bytes."""
    if isinstance(value, bool):
        raise BencodeError("bool is not a bencode type")
    if isinstance(value, int):
        return b'i' + str(value).encode() + b'e'
    if isinstance(value, (bytes, bytearray)):
        return str(len(value)).encode() + b':' + bytes(value)
    if isinstance(value, str):
        encoded = value.encode('utf-8')
        return str(len(encoded)).encode() + b':' + encoded
    if isinstance(value, list):
        return b'l' + b''.join(bencode(v) for v in value) + b'e'
    if isinstance(value, dict):
        def key_bytes(k):
            return k if isinstance(k, bytes) else k.encode('utf-8')
        items = sorted(value.items(), key=lambda kv: key_bytes(kv[0]))
        parts = [b'd']
        for k, v in items:
            parts.append(bencode(key_bytes(k)))
            parts.append(bencode(v))
        parts.append(b'e')
        return b''.join(parts)
    raise BencodeError(f"Cannot bencode type {type(value)}")


def compute_info_hash(torrent_bytes):
    """The 20-byte SHA-1 hash that identifies a torrent, computed from the
    raw bytes of its 'info' dict."""
    metainfo, _ = bdecode(torrent_bytes)
    if not isinstance(metainfo, dict) or b'info' not in metainfo:
        raise BencodeError("Not a valid .torrent file: missing 'info' dictionary")
    return hashlib.sha1(bencode(metainfo[b'info'])).digest()


def get_announce_urls(torrent_bytes):
    """All tracker URLs from a .torrent file, announce-list first (in tier
    order) then the primary 'announce' if not already present, de-duped."""
    metainfo, _ = bdecode(torrent_bytes)
    urls = []
    for tier in metainfo.get(b'announce-list', []):
        for url in tier:
            decoded = url.decode('utf-8')
            if decoded not in urls:
                urls.append(decoded)

    primary = metainfo.get(b'announce')
    if primary is not None:
        decoded = primary.decode('utf-8')
        if decoded not in urls:
            urls.insert(0, decoded)

    return urls


def derive_scrape_url(announce_url):
    """Per the (unofficial) scrape convention: substitute 'announce' with
    'scrape' in the last path segment of an HTTP(S) tracker URL. Returns
    None if the tracker doesn't support scrape (no 'announce' in its last
    path segment) or isn't HTTP(S)."""
    parts = urlsplit(announce_url)
    if parts.scheme not in ('http', 'https'):
        return None

    last_slash = parts.path.rfind('/')
    segment = parts.path[last_slash + 1:]
    if 'announce' not in segment:
        return None

    new_segment = segment.replace('announce', 'scrape', 1)
    new_path = parts.path[:last_slash + 1] + new_segment
    return urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, parts.fragment))


def build_scrape_request_url(scrape_url, info_hash):
    encoded_hash = quote_from_bytes(info_hash, safe='')
    separator = '&' if '?' in scrape_url else '?'
    return f"{scrape_url}{separator}info_hash={encoded_hash}"


def parse_scrape_response(data, info_hash):
    """Parse a bencoded scrape response. Returns {'seeders', 'leechers',
    'completed'} for info_hash, or None if the tracker's response doesn't
    include stats for it."""
    parsed, _ = bdecode(data)
    if b'failure reason' in parsed:
        raise BencodeError(parsed[b'failure reason'].decode('utf-8', 'replace'))

    stats = parsed.get(b'files', {}).get(info_hash)
    if stats is None:
        return None

    return {
        'seeders': stats.get(b'complete', 0),
        'leechers': stats.get(b'incomplete', 0),
        'completed': stats.get(b'downloaded', 0),
    }


def scrape_torrent(torrent_path, timeout=15):
    """Reads a .torrent file and queries its trackers for seeder/leecher
    counts without joining the swarm. Tries each HTTP(S) tracker in order
    until one returns usable stats. Returns {'tracker', 'seeders',
    'leechers', 'completed'}, or None if no tracker could be scraped
    (all UDP-only, all unreachable, or none had stats for this hash)."""
    with open(torrent_path, 'rb') as f:
        torrent_bytes = f.read()

    info_hash = compute_info_hash(torrent_bytes)

    for announce_url in get_announce_urls(torrent_bytes):
        scrape_url = derive_scrape_url(announce_url)
        if not scrape_url:
            continue

        request_url = build_scrape_request_url(scrape_url, info_hash)
        try:
            response = requests.get(request_url, timeout=timeout)
            response.raise_for_status()
            stats = parse_scrape_response(response.content, info_hash)
        except Exception:
            continue

        if stats is not None:
            return {'tracker': scrape_url, **stats}

    return None
