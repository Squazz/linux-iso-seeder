# 42 — Make the network guard refuse UDP and DNS; stop the stderr leak

**Priority**: P2 · **Class**: NO_REFACTOR · **Depends on**: —

## Evidence
- `tests/helpers.py:440` `block_network()` patches only `socket.socket.connect` and `connect_ex`. A real `sendto` (UDP tracker scrape), `sendall` on an unconnected socket, or `socket.getaddrinfo` (DNS) still leaves the machine. CLAUDE.md says the guard "refuses any real network connection".
- `tests/test_helpers.py:265` `test_real_connections_are_refused` passes, but leaves an unclosed socket (ResourceWarning).
- `tests/test_logging.py:248` `test_lines_carry_a_timestamp_and_the_logger_does_not_propagate` leaves the configured StreamHandler on the real stderr, so every run prints `WARNING: plain warning`.

## Acceptance criteria
1. Test first in `NetworkGuardTests`: `sendto` on a real UDP socket and `socket.getaddrinfo("example.com", 80)` both raise the guard's `RuntimeError`. Confirm they fail before the change.
2. `block_network()` also patches `socket.socket.sendto` and `socket.getaddrinfo` (and `socket.create_connection` if it doesn't go through the patched `connect`). Mocked sockets stay unaffected.
3. Tests that already stub `ts.socket.getaddrinfo` (`test_torrent_scrape.py:686`) still pass. Their patch replaces the guard for that test, which is intended.
4. The guard test closes its sockets (`with socket.socket() as s:`). `python -W error::ResourceWarning -m unittest test_helpers` is clean.
5. The logging test points the stream handler at a `StringIO` (as `_route()` does). A full suite run prints nothing outside unittest's own output.
