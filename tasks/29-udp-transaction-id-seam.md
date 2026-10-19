# 29 — Inject the UDP transaction id and assert what goes on the wire

**Priority**: P3 · **Class**: REFACTOR_REQUIRED · **Depends on**: —

## Evidence
- `torrent_scrape.py:256` `_random_transaction_id()` reads `os.urandom` directly. `ScrapeUdpTrackerTests` (`tests/test_torrent_scrape.py`, about lines 505–570) patches `ts.os.urandom` process-wide with a finite `side_effect` list, so any other `urandom` call in that window raises `StopIteration`.
- `test_full_round_trip_returns_stats` never inspects the first `sendto` payload, or the scrape request's transaction id and info_hash. It only reads `call_args_list[1][0][0]`. The socket is a bare `Mock()`, so a mistyped socket method would also pass.
- `torrent_scrape.py` is at 100% mutation, so this is about clarity and robustness (Farley Maintainable 5), not killing survivors.

## Acceptance criteria
- `scrape_udp_tracker(host, port, info_hash, timeout=15, *, new_transaction_id=_random_transaction_id)`. `scrape_torrent` keeps its signature.
- Tests pass a deterministic id source instead of patching `os.urandom`. The socket is `unittest.mock.create_autospec(socket.socket, instance=True)`, or a small `FakeUdpTracker` that records datagrams.
- The round-trip test asserts both payloads exactly: `struct.pack(">QII", 0x41727101980, 0, tid1)`, and `struct.pack(">QII", connection_id, 2, tid2) + info_hash`.
- The test named `test_scrape_response_echoing_the_connect_id_raises` says what it guards (the scrape uses a fresh transaction id). Use `assertRaisesRegex` on the mismatch message.
- Bare `assertRaises` in `test_torrent_scrape.py` (about 12) become `assertRaisesRegex` on a message fragment. Fold the duplicate short-response tests together (`BuildParseUdpConnectRequestTests.test_short_response_raises` vs `test_short_response_reports_its_length`; the same pair in the scrape-request tests).
