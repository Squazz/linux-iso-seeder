# 57 — HTTP scrape tests: assert on the requested URL, not `requests.get`'s arguments

**Priority**: P4 (optional) · **Class**: NO_REFACTOR · **Depends on**: —

## Evidence
- `tests/test_torrent_scrape.py` `ScrapeTorrentTests` patches `ts.requests.get` with a bare `MagicMock` and compares its arguments exactly:
  - `test_falls_through_from_failing_udp_tracker_to_http_tracker` (`:903`) and `test_skips_tracker_resolving_to_a_private_address` (`:1055`) check `mock_get.call_args_list == [call(url_with_query, timeout=N)]`.
  - `test_default_http_timeout_is_15_seconds` (`:1009`) checks `mock_get.call_args.kwargs == {"timeout": 15}`.
- These refactors send the same request on the wire but fail the tests: passing `info_hash` via `params=`, adding `headers=` (e.g. a User-Agent), or moving to a `requests.Session`.
- The rest of the suite already serves HTTP through `helpers.FakeHttp`, which records `(url, timeout)` and ignores other kwargs. However, `FakeHttp.get` (`tests/helpers.py`) currently drops `params=`, so it would need to fold them into the URL before it can stand in here.
- Found in the same 2026-10-22 coupling review as task 56.

## Acceptance criteria
1. Make `FakeHttp.get` record the URL as it would actually be sent, with any `params=` merged in (e.g. via `requests.Request("GET", url, params=params).prepare().url`). Cover this in `tests/test_helpers.py`.
2. Move the `ScrapeTorrentTests` cases that use `mock.patch.object(ts.requests, "get")` onto `FakeHttp`. Assert on `http.requested`, the timeout, and the result. `assert_not_called()` becomes `http.requests == []`.
3. Prove the change works: temporarily switch the HTTP scrape to `params=` plus an extra `headers=` kwarg. The suite stays green. Revert.
4. The `torrent_scrape.py` mutation score doesn't drop.
5. Full suite, ruff, ruff format, mypy and the coverage gate are green.

## Result
- `FakeHttp.get` takes `params=` and records the URL as requests would send it (merged into any existing query via `requests.Request(...).prepare()`, only when params are given, so other routed URLs aren't normalised). Covered in `tests/test_helpers.py`.
- `ScrapeTorrentTests` serves HTTP from one `FakeHttp` set up in `setUp`, routed by `_serve(tracker, info_hash, answer)`. Tests assert on `http.requests` (URL and timeout) and the result; `assert_not_called()` became `http.requests == []`.
- Proved by switching the HTTP scrape to `requests.get(scrape_url, params={"info_hash": ...}, headers={"User-Agent": ...}, timeout=...)`: the new suite stayed green, the old `tests/test_torrent_scrape.py` failed 8 tests. Reverted. (Such a switch isn't byte-identical for every hash: requests form-encodes a `0x20` byte as `+`. FakeHttp would record that, so a test hash containing one would catch it.)
- Mutation: `torrent_scrape.py` at e1d1329 (after tasks 56–58) is 99.2% (252/254), the same as task 50. The two survivors are the accepted `usedforsecurity` and `safe=` equivalents; the other 16 are exception-message literals, excluded under task 41's rule.
