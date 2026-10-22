# 56 — UDP scrape tests: assert on datagrams, not socket method calls

**Priority**: P4 (optional) · **Class**: NO_REFACTOR · **Depends on**: —

## Evidence
- `tests/test_torrent_scrape.py` `ScrapeUdpTrackerTests` (`:549-662`) and `ScrapeTorrentUdpWireTests` (`:1095-`) patch `ts.socket.socket` with `create_autospec(socket.socket, instance=True)` and assert on its method calls: `settimeout.assert_called_once_with(5)` / `(15)`, `close.assert_called_once()`, `socket(AF_INET, SOCK_DGRAM)` (`test_opens_a_udp_socket`) and `sendto.call_args_list`.
- The datagram bytes are the BEP 15 protocol and are right to pin. The method calls are how `scrape_udp_tracker()` (`torrent_scrape.py:260`) happens to use the socket today. These refactors keep the behaviour the same but fail the tests:
  - `with socket.socket(...) as sock:` instead of `try/finally: sock.close()`. The autospec `__exit__` doesn't call `close()`, and `__enter__` returns a different mock, so the `sendto` assertions see nothing.
  - `sock.connect(addr)` + `sock.send(...)` instead of `sendto(..., addr)`.
  - Choosing `AF_INET6` from the resolved address so IPv6 trackers work. That one would be a new feature rather than a pure refactor, but `test_opens_a_udp_socket` pins IPv4 as if it were a contract.
- Found in a 2026-10-22 review of whether the suite is coupled to implementation. The rest of the suite fakes at the I/O boundary and was judged fine. This file is the main exception.

## Acceptance criteria
1. Add a `FakeUdpSocket` in `tests/helpers.py`. It records each datagram sent (`sendto` and `connect`+`send` alike) as `(payload, addr)`, serves scripted `recvfrom` replies or exceptions, records the timeout it was given, and has a `closed` flag set by `close()` and by leaving a `with` block. Test it in `tests/test_helpers.py`, like the other doubles.
2. Move the UDP tests onto it. Assert on the datagrams sent, the result or exception, `closed` after both success and failure, and the effective timeout (not the `settimeout` call itself).
3. Decide whether `test_opens_a_udp_socket` pins anything worth keeping. "It's UDP" is already implied by the datagram assertions, so it can probably go.
4. Prove the change works: temporarily rewrite `scrape_udp_tracker()` to use `with socket.socket(...)` and `connect`/`send`. The suite stays green. Revert the rewrite.
5. The `torrent_scrape.py` mutation score doesn't drop (task 50: 252/254).
6. Full suite, ruff, ruff format, mypy and the coverage gate are green.
