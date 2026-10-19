# 44 — Make `log_seed_ratios_via_http`'s `auth` required

**Priority**: P3 · **Class**: REFACTOR_REQUIRED · **Depends on**: 43 (row 5 deletes one fallback test)

## Evidence
- `fetch_torrents.py:1188`: `auth=None` re-reads `os.environ` through `_rpc_credentials`, so `None` can't mean "send no auth". Both callers always pass `auth=config.rpc_auth`.
- Five tests (`tests/test_logging.py:324-388`) exist only for that fallback.

## Acceptance criteria
1. Test first: `log_seed_ratios_via_http(auth=None)` sends no credentials even when `TRANSMISSION_RPC_USERNAME`/`PASSWORD` are set in the environment. It fails today.
2. Make `auth` a required keyword argument with no env fallback (or keep `None` meaning "no auth"), and remove the env read.
3. Delete the fallback-only tests. Keep the run-level credential tests (`tests/test_daily_run.py:487`, `:496`).
4. `scripts/` callers, if any, pass `auth` explicitly. mypy passes.
