# 34 — Mechanical test tidy-up

**Priority**: P3 · **Class**: NO_REFACTOR · **Depends on**: —

From `.dev-team-reports/test-design-2026-10-19.md`. None of these change production code.

## Checklist
- [x] **Circular oracles → literals.** These expected values come from production code; use literals instead (the Kali URL list is already pinned in `test_scrapers.py`):
  - `test_fetchers.py` `FetchKaliOldVersionsTests.test_returns_only_the_non_newest_versions` builds its expected value from `ft._kali_torrent_urls`
  - `test_fetchers.py` default-distros test uses `ft.DEFAULT_DISTROS`
  - `test_daily_run.py` uses `ft.ALL_DISTROS`
- [x] **CPython error wording.** Three `test_daily_run.py` config tests embed CPython's `ValueError` text (`could not convert string to float: ...`, `invalid literal for int() ...`). Assert only the project-owned `ENV_VAR: ` prefix.
- [x] **Subprocess warnings.** `test_logging.ImportOpensNoFilesTests`: run the subprocess with `-W ignore` so an import-time warning from a dependency can't fail `stderr == ''`.
- [x] **Dead code.**
  - Delete the duplicate `if __name__ == "__main__"` block at the end of `test_cleanup.py`.
  - Delete the unused `helpers.fixed_date`, or use it for a `check_old_releases_for_demand(today=None)` default test.
  - Delete `helpers.use_isolated_env` unless task 35 adopts it.
  - Hoist the duplicated `_rpc_port_open` stub (`test_daily_run.py`) into helpers.
- [x] **Duplicates of stricter recorded-page tests.** Delete these `test_fetchers.py` tests, each of which a `test_scrapers` test covers more strictly:
  - `FetchDevuanLatestNamingTests.test_returns_false_when_no_torrent_link_found`
  - `FetchArchLatestNamingTests.test_no_available_releases_returns_false`
  - the Kali single-version test
- [x] **Duplicate timeout test.** Delete `test_logging.LogSeedRatiosViaHttpTests.test_session_id_request_has_a_timeout`, which duplicates `test_requests_follow_the_transmission_rpc_protocol`.
- [x] **`test_scrapers.FailurePathTests`.**
  - Merge `test_http_404` into `test_http_500` (same branch).
  - Assert "an error was logged naming the cause" instead of exact per-fetcher prefixes.
  - Rename `LATEST_FETCHERS`, since it also holds the `*_old_versions` fetchers.
- [x] **`ScraperTestCase.fetch()`.** Return a small result object instead of stashing `self.pages`, and drop the dummy `logger.debug('fetch start')` hack.
- [x] **`test_cleanup.test_selects_older_version_per_distro_and_type`.** Turn it into a subTest table per distro and delete the redundant `assertNotIn` loop.
- [x] **Count-only asserts.** Assert names and the absence of `remove_torrent` calls instead (`test_daily_run` `len(transmission.torrents) == 2`, `test_cleanup` `test_missing_added_date_does_not_crash`, `test_cleanup_old_versions_keeps_versions_below_min_ratio`).
- [x] **Weak boolean asserts.**
  - Replace `assertTrue(x.startswith(...))` / `assertTrue(any(...))` with `assertRegex` or an exact value where one is known (e.g. `test_torrent_scrape` `test_adds_query_param_with_no_existing_query`).
  - `test_fetchers.py` remove-watch-file test: assert the file's contents.
- [x] **`parse_supported_distros`.** Wrap the unknown-entry and fallback cases in `assertLogs` and assert the warning text. Assert the default list as a literal.
- [x] **Misfiled tests.** Move each beside the function it tests:
  - flavour/lubuntu tests out of `ParseVersionTypeTests`
  - `distro_of` into its own class
  - `NetworkGuardTests` plus `test_transmission_double.py` into a `test_helpers.py`
  - `LoadConfig`/`FormatRunSummary`/`MakeClientFactory` into `test_config.py`; update the module list in CLAUDE.md
- [x] **Old-release clock.** `CheckOldReleasesForDemandTests` call `check_old_releases_for_demand` without `today`; pass it explicitly.
