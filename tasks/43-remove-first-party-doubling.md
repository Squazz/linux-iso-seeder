# 43 — Remove first-party doubling the sociable tests already cover; drop the LOW_VALUE test

**Priority**: P2 · **Class**: NO_REFACTOR · **Depends on**: —

From `.dev-team-reports/test-design-2026-10-19-r2.md`: error rows 1, 2, 3 and 5, warnings 9 and 11. These rows are why test-review fails.

## Evidence
- `tests/test_old_release_demand.py:285`: 11 tests patch our own `evaluate_old_release_demand` (with a branching `fake_evaluate` at `:266`) and `ft._write_watch_file` (`:691`). `CheckOldReleasesSociableTests` (from `:869`) already runs the real path with only the network faked.
- `ft.OLD_RELEASE_DISCOVERY` is replaced with `patch.dict` 13× in that file, plus `tests/test_daily_run.py:607` and `:658`.
- `scrape_torrent` is doubled at `test_old_release_demand.py:135`, `:173`, `:201`, `:231`, `:752` and `test_daily_run.py:630`. That is a legitimate boundary (it opens sockets) but it carries no waiver comment.
- `EvaluateOldReleaseDemandTests` (`:129-251`) repeats `HasUnmetDemandTests` and the boundary tests (`:768-862`) through a patched `scrape_torrent`.
- `tests/test_logging.py:378` `test_fallback_applies_the_config_credential_rule` patches the pure `Config.rpc_auth` with a `PropertyMock`. `tests/test_config.py:187` already pins the rule through real objects.
- **LOW_VALUE:** `tests/test_config.py:227` `test_passes_configured_credentials` has no branching in the code under test and only asserts a mock call. `tests/test_daily_run.py:829` asserts the same `Client(...)` call one layer up.

## Acceptance criteria
1. Before deleting anything, list each patched old-release test and the sociable or boundary test that covers its behaviour. Move any case with no cover onto `OldReleaseTracker` (real `evaluate_old_release_demand`, faked `requests.get`/tracker), asserting outcomes, not calls. Fail writes at the leaf (`helpers.disk_full_open`), not by patching `_write_watch_file`.
2. Then delete the superseded patched tests and `fake_evaluate`.
3. `OLD_RELEASE_DISCOVERY`: serve the kali/fedora pages through the existing `requests.get` fake, or add a `discovery=` parameter to `check_old_releases_for_demand` (test-first, like `run(fetchers=)`).
4. Every remaining `scrape_torrent` double has a one-line reason comment (`# boundary double: opens UDP/HTTP tracker sockets`).
5. Delete `test_logging.py:378` and `test_config.py:227`. Optionally fold `test_config.py:240`/`:247` into one table test.
6. Run mutmut on `fetch_torrents.py` afterwards: the score must not drop (99.3%, critical set 100%). A survivor that appears was only killed by a deleted test; restore a sociable test for it.
