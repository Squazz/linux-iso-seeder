# 28 — Make `wait_for_transmission_rpc` testable and test it

**Priority**: P2 · **Class**: REFACTOR_REQUIRED · **Depends on**: —

## Evidence
- `fetch_torrents.py:185` `wait_for_transmission_rpc` calls `time.time()`, `time.sleep(1)` and `socket.create_connection` directly. No test calls it: 3/9 mutants killed (port, timeout, sleep and `return False → True` all survive).
- `tests/test_daily_run.py` `test_rpc_unavailable_skips_ratio_logging_but_still_cleans_up` patches the whole function because the real one would sleep for up to 30 s. The `create_connection` → `refuse()` patch next to it never runs.
- `time.time()` is wall-clock, so a clock change during the wait skews it. `time.monotonic()` is the right clock for elapsed time.

## Acceptance criteria
- `wait_for_transmission_rpc(host, port, timeout, *, connect=socket.create_connection, clock=time.monotonic, sleep=time.sleep)`. Existing callers are unchanged.
- Tests (write them first; they fail until the seam exists), all with a fake clock and a recording `sleep`, and no real sleeping:
  - connects on the first try → `True`, no sleep, `connect` called with `(("localhost", 9091), timeout=3)`
  - refused N times, then succeeds → `True`, sleeps recorded as `[1] * N`
  - always refused → `False` once the fake clock passes `timeout`; the loop condition is `< timeout` (pin the boundary)
- `run()` gets the readiness check through an injectable seam (e.g. `run(..., wait_for_rpc=wait_for_transmission_rpc)`). The daily-run test drives the "RPC unavailable" path through it and drops both patches.
- Re-run mutmut on the function: no survivors, or each one documented as equivalent.
