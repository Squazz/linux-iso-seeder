# 18 — Extract `run()` and `configure_logging()`

**Priority**: P2 · **Class**: REFACTOR_REQUIRED · **Depends on**: 17

## Problem
There are two blockers to testing `fetch_torrents.py` directly:
1. **The `__main__` orchestration can't be called.** It reads env vars inline (`:1407–1410`, `:1446`, …) and calls `date.today()`, `time.time()` and the module-level fetchers directly.
2. **Logging is configured at import time.** It opens files under `log_dir` (`:19` onward), which is why every test file must set `FETCH_TORRENTS_LOG_DIR` *before* `import fetch_torrents` (see CLAUDE.md).

## Acceptance criteria
- New `run(config, *, client_factory, today, now=time.time, fetchers=DEFAULT_FETCHERS) -> RunSummary`, where `config` is a small dataclass built by `load_config(os.environ)` from every env var `main` reads today.
- `__main__` becomes `configure_logging(log_dir); run(load_config(os.environ), ...)`.
- New `configure_logging(log_dir)`. Importing the module no longer opens files or adds handlers, and the `RatioLogSurvivesRestartTests` guarantee is preserved: ratios from the previous run are readable before the ratio handler truncates the file.
- The task-17 lock-in tests pass **unchanged** against the refactor, then are rewritten to call `run()` directly with fakes.
- `tests/test_fetch_torrents.py` no longer needs the env-before-import workaround for logging. The `transmission_rpc` stub stays until task 20.
- Update the CLAUDE.md section "Why the test setup looks the way it does" to match.
- `fetch_torrents.py` branch coverage ≥ 90%.

## Approach
Do this in small steps, with the lock-in suite green after each one. Extract `load_config` first,
then `configure_logging`, then `run`. Follow the existing `plan_cleanup()` vs `cleanup_old_versions()`
pattern: keep the decisions pure and do the I/O at the edges.
