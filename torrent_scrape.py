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
import ipaddress
import socket
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


def _is_disallowed_ip(ip_str):
    """True if ip_str is loopback/private/link-local/multicast/reserved -
    i.e. not a real public tracker, so a scrape request should never be sent
    there. Covers the cloud metadata endpoint (169.254.169.254) and this
    container's own services (127.0.0.1) alongside RFC1918 space."""
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _resolve_addresses(hostname):
    """I/O: DNS-resolves hostname to its IP address strings. Kept separate
    from _is_disallowed_ip/_is_safe_scrape_host so the safety check itself
    has no network dependency and is unit-testable; raises OSError on
    resolution failure, same as socket.getaddrinfo."""
    return [info[4][0] for info in socket.getaddrinfo(hostname, None)]


def _is_safe_scrape_host(hostname):
    """False (fail closed) if hostname is missing, fails to resolve, or
    resolves to any disallowed address. Guards against a compromised or
    malicious .torrent's announce URL pointing the scrape request at an
    internal service (e.g. cloud metadata, this container's own Transmission
    RPC) instead of a real tracker."""
    if not hostname:
        return False
    try:
        addresses = _resolve_addresses(hostname)
    except OSError:
        return False
    return bool(addresses) and not any(_is_disallowed_ip(ip) for ip in addresses)


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
        if not _is_safe_scrape_host(urlsplit(scrape_url).hostname):
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
