# 45 — `scrape_torrent` seams for address resolution and the UDP scrape

**Priority**: P3 · **Class**: REFACTOR_REQUIRED · **Depends on**: 42

From `test-design-2026-10-19-r2.md` error row 4.

## Evidence
- `tests/test_torrent_scrape.py:779` onwards patches our own `ts._resolve_addresses` (9 sites) and `ts.scrape_udp_tracker` (`:815`…`:1007`). The latter is verified only by `assert_called_once_with`/`assert_not_called`.
- `new_transaction_id=` (task 29) already shows the injection style.

## Acceptance criteria
1. `scrape_torrent` takes keyword-only `resolve=` and `udp_scrape=` parameters, defaulting to the real functions. Add a test first that passes a fake for each and fails before the parameters exist.
2. The patching tests switch to the parameters, and assert the returned outcome dict instead of call counts. Where the wire matters, keep one test per path that goes through the autospec socket and asserts `sendto`.
3. No `mock.patch.object(ts, "_resolve_addresses" | "scrape_udp_tracker")` is left in `tests/`.
4. The `torrent_scrape.py` mutation score stays at 100% excluding message literals (task 41's rule).
