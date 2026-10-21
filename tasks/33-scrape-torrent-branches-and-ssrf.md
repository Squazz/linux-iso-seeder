# 33 — `scrape_torrent` fall-through branches and SSRF guard edges

**Priority**: P2 · **Class**: NO_REFACTOR · **Depends on**: —

## Evidence
- `torrent_scrape.py:351` `scrape_torrent`. In `ScrapeTorrentTests`:
  - only the default timeout is asserted; the HTTP call's `timeout` kwarg is never checked
  - UDP call args are `assert_called_once()` only
  - request URLs are matched with `assertIn` substrings
  - results are compared field by field, so `completed` is never asserted
- No test covers falling through to the next tracker on:
  - an HTTP status error (`raise_for_status`)
  - a `failure reason` response
  - a response that lacks the info hash (stats `None`)
  - an announce URL with no `announce` segment (`derive_scrape_url → None`)
- `_is_safe_scrape_host` (`:311`) returns `bool(addresses) and not any(...)`, but no test resolves to `[]`, so treating an empty resolution as safe would pass. `IsDisallowedIpTests` has no multicast case (`224.0.0.1`, `ff02::1`) and no IPv4-mapped loopback (`::ffff:127.0.0.1`).
- Five tests hand-build `Mock()` HTTP responses instead of `helpers.fake_response()`, and `fake_resolve` is duplicated.

## Acceptance criteria
- Parametrised fall-through tests: tracker A fails in each of the four ways above, tracker B is good. Each asserts the whole result dict, and `mock_get.call_args == call(<exact scrape url with %-encoded info_hash>, timeout=3)` with `scrape_torrent(..., timeout=3)`.
- The UDP path asserts `(host, port, info_hash)` exactly.
- SSRF: `_resolve_addresses → []` is unsafe. Decide and pin the multicast, `0.0.0.0` and `::ffff:127.0.0.1` cases; if any is wrongly allowed today, fixing it is a behaviour change, so test first.
- Mock responses replaced by a `_tracker_response(info_hash, seeders, leechers)` helper over `helpers.fake_response`, and one shared `resolve_private()` fake.
