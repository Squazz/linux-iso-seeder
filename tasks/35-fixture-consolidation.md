# 35 — Consolidate fixtures and the module-global path seam

**Priority**: P3 · **Class**: NO_REFACTOR (helpers), then REFACTOR_REQUIRED (watch dir env var) · **Depends on**: 34

## Evidence
- Eight `setUp`s copy the same `patch.object(ft, "watch_dir" / "<state>_file", ...)` plus `addCleanup` dance:
  - `test_fetchers.py` (3)
  - `test_cleanup.py` (2)
  - `test_old_release_demand.py` (2)
  - `test_daily_run.py` (1)

  Renaming one of these module globals touches 4 files. That is the suite's one rung-1 maintainability pocket.
- `watch_dir = "/watch"` (`fetch_torrents.py:169`) is hard-coded, unlike `log_dir`. `MainWiringTests` (the runpy test) can't redirect it; it stays safe only because no route is registered that would make it write to `/watch` (C:\watch on Windows).
- There are two RPC doubles with different rules. `test_logging`'s `LogSeedRatiosViaHttpTests` hand-builds the 409 handshake, while `test_daily_run.FakeWorld.post` (now strict) has its own. They should be one helper.
- Repeated fixture boilerplate:
  - `HasUnmetDemandTests` spells out all three thresholds in every test
  - about 14 `removed_history` literals carry fields the gate ignores
  - `RunTests` repeats the same two-torrent setup 5 times
- `ShouldFetchTorrentRatioKeyTests` has 10 near-identical tests. Kali and Arch have no high-ratio case.
- `get_rpc_credentials()` (`fetch_torrents.py:172`) duplicates `Config.rpc_auth`.

## Acceptance criteria
- `helpers.use_watch_dir(testcase)` and `helpers.use_state_files(testcase)` return the temp paths; all 8 setUps use them.
- `FETCH_TORRENTS_WATCH_DIR` (default `/watch`) is read once like `log_dir`, written test-first. `MainWiringTests` points it at a temp dir. Document it in the README.
- One strict Transmission-RPC HTTP fake lives in helpers (409 plus session id, records auth), used by both `test_logging` and `FakeWorld`.
- Creation Methods:
  - `demand(scrape, **overrides)` in `test_old_release_demand`
  - `removed(name, ratio=None)` for removed-history entries
  - a `world.hold_current_and_superseded_ubuntu()` helper
- The ratio-key tests become one parameterised table, including the missing Kali and Arch high-ratio rows.
- `get_rpc_credentials` folds into `Config` (one credential rule), with `log_seed_ratios_via_http`'s fallback kept working.
