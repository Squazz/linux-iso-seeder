# 26 — Tighten weak assertions and consolidate fixtures

**Priority**: P3 · **Class**: NO_REFACTOR · **Depends on**: 10, 14 (do it after the test-adding tasks to avoid merge pain)

## Problem (from the test-design report, `.dev-team-reports/test-design-2026-10-18.md`)
- **Presence-only assertions** where the exact value is known:
  - `tests/test_fetch_torrents.py:504` (`assertTrue(results)` + `assertIn`), `:1119`, `:228–238`
  - `tests/test_configure_transmission.py:165`
- **Timeout test** (`:1729–1737`) checks that the `timeout` kwarg exists, not its value.
- **"Logs a warning" test** (`:1985`) never asserts the warning.
- **RPC auth tests** (`:1687`, `:1695`, `:1704`) and the not-called guards (`:890`, `:1931`, `:1939`) assert only on mock calls. Keep them (they cover real branches), but assert the observable outcome too.
- **Duplication:**
  - about 17 copy-pasted `FakeResponse` classes (`:498` and others)
  - the load/save/round-trip persistence trio, written 4 times (ratio history, removed history, old-release check state, settings)
- **One 2016-line test module.**

## Acceptance criteria
- Each assertion above is replaced with an exact-value assertion (`assertEqual` on the full dict/list, or the specific kwarg value), or with `assertLogs(...)` checking the message.
- A `tests/helpers.py` with `fake_response()`, `FakeTorrent`, `isolated_env()` (from task 12) and the `transmission_rpc` stub/import bootstrap. No `class FakeResponse` remains in the test files.
- The persistence trio is a single parameterized mixin or `subTest` loop, run over the four stores.
- `tests/test_fetch_torrents.py` is split by concern: `test_ratio_gate.py`, `test_fetchers.py`, `test_cleanup.py`, `test_persistence.py`, `test_logging.py`, `test_old_release_demand.py`. Each imports via `tests/helpers.py`.
- The test count is the same or higher, the suite is green, and the Farley Score doesn't drop. Re-run `/test-design`.
