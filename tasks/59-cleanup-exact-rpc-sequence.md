# 59 — Cleanup tests that pin the exact RPC call sequence

**Priority**: P4 (optional) · **Class**: NO_REFACTOR · **Depends on**: —

## Evidence
- `tests/test_cleanup.py:782` (`test_cleanup_stagnant_torrents_deletes_the_downloaded_data`) and `:1072` (`EnforceDiskUsageLimitTests.test_removal_deletes_the_downloaded_data`) assert `transmission.calls == ["get_torrents", ("remove_torrent", N, True)]`.
- What they mean to pin is "torrent N was removed with its data". Comparing the whole list also pins that no other RPC call happened. One extra harmless read, such as `get_session()` or a second `get_torrents()` with different fields, fails them even though nothing about removal changed.
- `:666` already uses the sturdier form, `assertIn(("remove_torrent", 2, True), transmission.calls)`.
- Both tests are named in `docs/seeding-policy.md` ("A removal deletes the downloaded data…"). If you rename either one, rename it there too (`tests/test_repo_hygiene.py` checks this).
- Found in the same 2026-10-22 coupling review as task 56.

## Acceptance criteria
1. Assert on the removals only: e.g. `[c for c in transmission.calls if c[0] == "remove_torrent"] == [("remove_torrent", N, True)]`, or a small `FakeTransmission.removals` property (tested in `tests/test_helpers.py`) if more tests would use it.
2. Check that nothing else in the suite compares the whole of `transmission.calls`. Where a test really needs "no other calls" (e.g. `test_disabled_threshold_never_touches_disk_or_rpc`), keep that and say so in the test.
3. Full suite, ruff, ruff format, mypy and the coverage gate are green.

## Result
- Both tests assert `transmission.removals == [(N, True)]`, using the property `FakeTransmission` already had (tested in `tests/test_helpers.py`). Names unchanged, so `docs/seeding-policy.md` still matches.
- No other test compares the whole of `transmission.calls` (`:666` already used `assertIn`). `test_disabled_threshold_never_touches_disk_or_rpc` pins "no RPC at all" through the connection count, not `calls`, so it stays as it is.
- Proved by temporarily adding a second `tc.get_torrents()` read to `cleanup_stagnant_torrents()` and `enforce_disk_usage_limit()`: the rewritten tests pass, the old ones fail. Reverted.
