# 19 — Inject `today` / client / config into the `cleanup_*` functions

**Priority**: P2 · **Class**: REFACTOR_REQUIRED · **Depends on**: 17 (can go before or with 18)

## Problem
The I/O wrappers `cleanup_old_versions` (`:1147`), `enforce_disk_usage_limit` (`:1196`),
`cleanup_stagnant_torrents` (`:1312`) and `should_fetch_torrent` (`:386`) each reach out for their
inputs, which makes their tests patch-heavy and fragile:
- each builds its own `Client(host='localhost', …)`
- they read `CLEANUP_*` / `SKIP_RATIO_CHECK` from `os.environ`
- they call `date.today()`

The test-design review found:
- a spec-less `MagicMock` client verified by call arguments
- a `disk_usage` side-effect list that hard-codes how many times production calls it (`tests/test_fetch_torrents.py:1959`)
- an internal function patched out (`evaluate_old_release_demand`, `:1404`+)

`check_old_releases_for_demand(today=…)` already shows the target pattern.

## Acceptance criteria
- `should_fetch_torrent(name, ratios, removed_history=None, *, skip_ratio_check=False)`. The env read moves to the caller, i.e. `load_config` from task 18 or `__main__`.
- `cleanup_old_versions(client, *, today, skip_ratio_check, min_ratio)`
- `cleanup_stagnant_torrents(client, *, today, window_days, min_ratio_delta)`
- `enforce_disk_usage_limit(client_factory, threshold_percent, *, today, disk_usage=shutil.disk_usage, download_path=…)`, which still only connects once the threshold is exceeded.
- Tests pass a fake client with real `get_torrents()`/`remove_torrent()` behavior: an in-memory list that records removals. Assert the resulting state rather than `assert_called_once_with`.
- The `disk_usage` fake is driven by the fake client's removals (used space drops as torrents are removed), not by a fixed side-effect list.
- The task-17 lock-in tests stay green.
