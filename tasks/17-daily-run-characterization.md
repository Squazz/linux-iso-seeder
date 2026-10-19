# 17 — Lock in daily-run behavior with a `runpy` test

**Priority**: P2 · **Class**: NO_REFACTOR (test only) · **Depends on**: 12

## Problem
The `if __name__ == "__main__":` block (`fetch_torrents.py:1351–1457`, about 100 lines) is the whole
daily run. It's untested, and it's where all the parts get wired together:
- the ratio log feeds `should_fetch_torrent`
- `removed_history`
- the per-distro fetch loop and its success/existing/not-found/failure counting
- the old-release demand check
- `log_seed_ratios_via_http`, then the cleanup branches selected by env vars
- `enforce_disk_usage_limit`
- the summary line

Before task 18 can refactor this block, a behavior lock-in test has to pin down what it does now.

## Acceptance criteria
A test class, e.g. `DailyRunCharacterizationTests`, runs the module as `__main__` via
`runpy.run_path(fetch_torrents.py, run_name='__main__')`. It runs:
- with `transmission_rpc.Client` stubbed (reusing the `sys.modules` stub)
- with `requests.get`/`requests.post` patched to canned responses for each distro
- with the watch dir, log dir and state files in a temp dir
- with `shutil.disk_usage` patched and the env pinned via the task-12 helper

At minimum it asserts:
- Distros not in `FETCH_TORRENTS_DISTROS` are never fetched.
- A candidate whose predecessor has ratio < 1.0 is **not** downloaded, and one at ≥ 1.0 is. The ratio log is pre-written in the temp log dir.
- An exception in one distro's fetcher doesn't stop the others, and it's counted as a failure.
- Each cleanup function is called only when its env flag is set.
- Disk-usage enforcement runs after cleanup, and an exception there is logged, not raised.
- The summary line reports the right counts.

The tests make no network calls and complete in under 2 s total.

## Notes
Because the module runs again under `runpy`, its import-time logging setup runs again too. Point
`FETCH_TORRENTS_LOG_DIR` at the temp dir, and close the handlers in `addCleanup`. If this gets too
awkward, that's evidence for task 18. Don't change production code here.
