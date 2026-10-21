# 47 — Consolidate tests: oversized scenarios, conditional logic, duplicate HTTP fakes

**Priority**: P3 · **Class**: NO_REFACTOR · **Depends on**: 43 (it removes some of the duplicates first)

From `test-design-2026-10-19-r2.md` rows 12–16, 19, 23, 33 and 35. Rows 16, 33 and 35 were already open in round 1.

## Acceptance criteria
1. **One HTTP fake.** The routes-dict `requests.get` fake with a 404 default is written 4× (`FakeWorld` in `tests/test_daily_run.py:89`, `OldReleaseTracker` at `:733`, `tests/test_live_check.py:309`, `RecordedPages`). Make it a single `helpers.FakeHttp`, and move `OldReleaseTracker`/`swarm()` into `helpers.py`. Add a `test_helpers.py` test for the new double.
2. **Split the eager twin scenarios.** `test_daily_run.py:687` `test_config_and_saved_state_drive_the_check` should keep one wiring assertion per Config field. `test_old_release_demand.py:902` (11 candidates, Farley 5.74) should split counts, saved state and logs over a shared Creation Method.
3. **No conditional test logic** in `test_torrent_scrape.py:937`: put the expected requests in the cases table instead of computing them with `if` at `:951`.
4. **`MainWiringTests`** (`test_daily_run.py:772`): `addCleanup` instead of try/finally. Drop the facts `RunTests` already pins (`rpc.auths` at `:832` duplicates `:494`).
5. **Mystery Guest.** `route_ubuntu()` (`test_daily_run.py:114`) hides the 404 default and a pre-existing watch file that `test_counts_each_download_outcome` depends on. Inline that setup, or use named per-outcome routes.
6. **Logging reset.** Replace the hand save/restore of the private `ft._configured_handlers` (`test_logging.py:30`) with a public `reset_logging()` in `fetch_torrents.py` (test-first).
7. **Delete duplicates:**
   - the mid-range twins that the boundary tests now cover (`test_cleanup.py:103`, `:392` and the others listed in the test-design scratch tables)
   - the hand-written page tests in `test_fetchers.py` that repeat `RecordedSnapshotTests`. Keep only cases a recording can't express: unsorted rows, 99 vs 100, duplicates
8. Mutation scores don't drop. Re-run mutmut on any module whose tests were deleted.
