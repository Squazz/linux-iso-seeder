# 52 — Ratio logging must work when RPC credentials are set

**Priority**: P2 (suspected bug) · **Class**: NO_REFACTOR · **Depends on**: —

## Evidence
- `fetch_torrents.py:1209`: `log_seed_ratios_via_http()` makes its first POST, the one that fetches the session id, with no `auth`. Only the second POST (`:1215`) passes `auth=auth`.
- transmission-daemon's RPC server is believed to check credentials (401) before the session id (409). If so, with `TRANSMISSION_RPC_USERNAME`/`_PASSWORD` set, which `configure_transmission.py:28-31` turns into `rpc-authentication-required`, the first POST gets a 401 with no `X-Transmission-Session-Id` header. `r.headers[...]` at `:1210` then raises `KeyError`, and the daily run logs `Could not query Transmission: 'X-Transmission-Session-Id'` every day. This is unconfirmed: it came out of task 46 and has not been checked against a real daemon.
- No test can catch it today. `helpers.FakeTransmissionRpc.post()` (`tests/helpers.py:278`) answers 409 to any request without the session id, whatever its auth, and only records auth on the torrent-get. The drift job's round trip (`.github/workflows/drift.yml`, `transmission` job) starts the daemon with no credentials, so the real daemon never sees an authenticated request either.

## Acceptance criteria
1. Confirm the daemon's order: read transmission's `rpc-server` source for the pinned Alpine version, or run the image with credentials and `curl` the RPC without them. Record the result (status and headers) in this file. If the daemon hands out the session id before checking auth, there is no bug: close the task after doing step 2 only, so the fake pins the real order.
2. Make `FakeTransmissionRpc` as strict as the daemon about auth. Give it an optional `credentials` tuple. When it's set, any request whose `auth` doesn't match gets a 401 without the session-id header, checked before the session id if that's the daemon's order. Add a test in `tests/test_helpers.py` for it.
3. Test first: in `tests/test_logging.py`, a `log_seed_ratios_via_http(auth=...)` call against a fake with the same credentials logs the ratios. Confirm it fails today with the `KeyError`.
4. Pass `auth=auth` on the first POST too. Keep `auth=None` meaning no credentials on both requests.
5. Make the drift job cover it: start the `transmission` job's daemon with RPC credentials set, and have `scripts/transmission_roundtrip.py` read the same credentials into its config. Check its offline tests in `tests/test_transmission_roundtrip.py` still pass.
6. Full suite, ruff, ruff format, mypy and the coverage gate are green.

## Result
- Step 1, confirmed from source: Alpine v3.22 ships `transmission-daemon` 4.0.6-r4. In 4.0.6's `libtransmission/rpc-server.cc` `handle_request()`, `isAuthorized()` runs before `test_session_id()`. A request without the right Basic auth gets `401` with `WWW-Authenticate: Basic realm="Transmission"` and no `X-Transmission-Session-Id`. The session-id check (`409` carrying the id) only comes after auth passes. So the bug was real: with credentials set, the first POST got a 401 and `r.headers["X-Transmission-Session-Id"]` raised `KeyError`. (Docker wasn't available to check against a running daemon; the drift job's round trip now does that.)
- `FakeTransmissionRpc.credentials` makes the fake refuse wrong auth the same way, before the session id (`tests/test_helpers.py`).
- `log_seed_ratios_via_http()` sends `auth` on both POSTs. `test_authenticates_against_a_daemon_that_requires_credentials` failed with the `KeyError` before the fix. The daily-run credentials test now runs against a fake that requires them.
- The drift job's daemon starts with `TRANSMISSION_RPC_USERNAME`/`_PASSWORD`; the round trip reads them through `load_config(os.environ)` as before, so only the workflow changed. Verified by the next drift run.
