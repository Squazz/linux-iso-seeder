# 24 — Parser gaps: bencode str, UDP parsers, `parse_version_type`

**Priority**: P3 · **Class**: NO_REFACTOR · **Depends on**: 13

## Evidence (mutmut survivors / coverage)
- `torrent_scrape.py:89–90`: `bencode(str)` is never exercised. `:95`: str dict keys (`key_bytes`) are never exercised. `bencode` is at 73% killed.
- `parse_udp_connect_response` 60%, `_check_for_udp_error_action` 67%. Short-packet and error-action payload branches aren't asserted precisely.
- `ScrapeUdpTrackerTests` patches `os.urandom` to a constant (`tests/test_torrent_scrape.py:315`), so the connect and scrape transaction IDs are identical. A mixed-up ID check would still pass.
- `fetch_torrents.py:320`, `:327–329`, `:333` `parse_version_type`: the returned `type_` is never asserted directly, and no test uses two architectures (amd64/arm64) of the same release, so they could be grouped together.

## Acceptance criteria
- `bencode('abc') == b'3:abc'`. Dicts with str keys encode identically to bytes keys and are sorted by byte value. Unsupported types raise.
- UDP: a connect response shorter than 16 bytes raises. An error-action packet raises `UdpTrackerError` containing the tracker's message. A response with the wrong action raises. Scrape responses shorter than 8+12 bytes raise.
- `ScrapeUdpTrackerTests` gives `urandom` two **different** IDs (`side_effect=[b'\x00\x00\x00\x01', b'\x00\x00\x00\x02']`). Add a test where the scrape response echoes the *connect* ID, which must raise.
- `parse_version_type` table test: for each distro pattern, assert `(version, type_)` exactly, including amd64 vs arm64 Debian/Ubuntu names producing **different** `type_` values.
- Re-running mutmut on these functions: ≥ 90%, with any remaining survivors documented as equivalent.
