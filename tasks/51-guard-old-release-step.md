# 51 — A failing old-release check must not abort the daily run

**Priority**: P2 (bug) · **Class**: NO_REFACTOR · **Depends on**: —

## Evidence
- `fetch_torrents.py:1827`: `run()` calls `_check_old_releases()` with no `try`. Every later step does have one: ratio logging (`Could not query Transmission: ...`), cleanup (`Could not clean up old versions: ...`) and the disk limit (`Could not enforce disk usage limit: ...`).
- With `FETCH_TORRENTS_CHECK_OLD_RELEASES=true`, an unparseable `FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHERS`, `_MIN_LEECHER_RATIO` or `_RECHECK_DAYS` makes `config.require()` (`:1742`) raise `ValueError` out of `run()`. The same happens with any other exception from the step, for example an `OSError` from `save_old_release_check_state()`. The run then skips ratio logging, cleanup, the disk-usage limit and the run summary.
- `entrypoint.sh:59-62` reruns the script every 24 hours with the same environment, so a single bad value disables cleanup and the disk-usage limit on every run. Nothing is logged by this script's own logger. The traceback only goes to the container's stderr, and `/downloads` can fill up.
- The behavior predates the task 18 refactor, which kept it on purpose. `tests/test_daily_run.py:754` `test_invalid_old_release_setting_aborts_the_run` pins it, and its comment says the step "has never been guarded".

## Acceptance criteria
1. Test first: replace `test_invalid_old_release_setting_aborts_the_run` with `test_invalid_old_release_setting_skips_the_check_and_continues`, modelled on `test_invalid_cleanup_setting_skips_cleanup_and_continues` (`:412`). With `FETCH_TORRENTS_OLD_RELEASE_RECHECK_DAYS="weekly"`, `run()` returns normally. It logs `Could not check old releases: FETCH_TORRENTS_OLD_RELEASE_RECHECK_DAYS: ...`, still logs seed ratios, still runs cleanup (a superseded torrent is removed) and still logs the run summary. Confirm the test fails today because the `ValueError` escapes.
2. A second test where the step fails partway through (for example, the check-state file can't be written; fail it at the leaf with `helpers.disk_full_open`, not by patching our own function). The run continues the same way, and the summary still reports the counts that were set. Decide and pin what `old_added`/`old_skipped` show when the step fails before producing counts (probably `None`, which `format_run_summary` already treats as "check not run").
3. Wrap the `_check_old_releases()` call in `run()` in the same `try`/`except Exception` + `logger.error(...)` pattern as the other steps. Update `run()`'s docstring so it says every step logs its own failure and lets the rest carry on.
4. Full suite, ruff, ruff format and mypy are green. Coverage stays at or above `fail_under`.
