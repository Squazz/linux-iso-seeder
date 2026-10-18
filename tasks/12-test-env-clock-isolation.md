# 12 — Isolate tests from env vars and the clock

**Priority**: P1 · **Class**: NO_REFACTOR (test-side only; the production seams are task 19) · **Depends on**: —

## Problem
Some tests pass only because the developer's shell and the wall clock happen to cooperate:
- `should_fetch_torrent` reads `SKIP_RATIO_CHECK` directly (`fetch_torrents.py:386`). With `SKIP_RATIO_CHECK=true` exported, the `ShouldFetchTorrent*` tests at `tests/test_fetch_torrents.py:241–385` fail. This is confirmed.
- `cleanup_*` reads `CLEANUP_*`. `get_rpc_credentials` reads `TRANSMISSION_RPC_*`, which affects the tests around `:1663–1712` and `:1777–1866`.
- `CleanupRemovesWatchFileTests` builds its history from `date.today()` (`:1855`) while production calls `date.today()` again. A run that crosses midnight shifts the 32-day offset.
- Temp dirs from `tempfile.mkdtemp` are never removed, in all three test files.

## Acceptance criteria
- Every test class that runs code reading these env vars patches the environment with `patch.dict(os.environ, {...}, clear=False)` and explicitly sets **or deletes** the keys it depends on. Add a small helper, e.g. `isolated_env(**overrides)`, that removes `SKIP_RATIO_CHECK`, `CLEANUP_*`, `TRANSMISSION_RPC_*` and `FETCH_TORRENTS_*` (except `FETCH_TORRENTS_LOG_DIR`) unless they're overridden.
- Running the whole suite with `SKIP_RATIO_CHECK=true CLEANUP_MIN_RATIO=5 CLEANUP_SKIP_RATIO_CHECK=true TRANSMISSION_RPC_USERNAME=x TRANSMISSION_RPC_PASSWORD=y` exported is green.
- The stagnation integration test patches `ft.date` (or uses an injected `today` once task 19 lands) to a fixed date. No `date.today()` remains in `tests/`.
- Each `mkdtemp` is paired with `self.addCleanup(shutil.rmtree, path, ignore_errors=True)`, or uses `tempfile.TemporaryDirectory`.

## Approach
1. First, run the suite with the hostile env above and record which tests fail. Those failures are the "red" for this task.
2. Add the helper and apply it, then re-run with the hostile env until green.
3. Optional: add a CI step that runs the suite a second time with that hostile env, so regressions are caught.
