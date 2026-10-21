# 55 — Round-3 hygiene leftovers: `record=` seam and the tracker double's marker

**Priority**: P3 · **Class**: REFACTOR_REQUIRED · **Depends on**: 49

## Evidence
- The round-3 `/test-health` re-run (task 50, `.dev-team-reports/test-health-2026-10-21-r3.md`, local) left two local hygiene findings.
- `tests/test_record_fixtures.py:133` and `:173` patch `record_fixtures.record` with `mock.patch.object` to spy on what `main()` records. That patches the module's own code, which task 43 removed everywhere else. `scripts/record_fixtures.py:89` `main(argv, *, now=None)` has no seam for it, unlike `record()`'s `get=`/`out_dir=` (task 49).
- The report also flags a missing double-waiver marker on the `scrape_torrent` double in `tests/helpers.py`. `OldReleaseTracker.patch()` (`:513-525`) carries a `# boundary double: opens UDP/HTTP tracker sockets` comment, so check what marker format the report expects before changing anything. It may have been written against a version from before task 47 moved the tracker into helpers.

## Acceptance criteria
1. `main()` takes `record=record` (keyword-only, like `now=`). The two tests pass a spy instead of patching. Confirm they still fail if `main()` ignores the distro filter: break it temporarily.
2. No `mock.patch.object(record_fixtures, ...)` is left in `tests/test_record_fixtures.py`.
3. The `scrape_torrent` double carries whatever waiver marker the other boundary doubles use, or this file records why the existing comment already satisfies it.
4. Full suite, ruff, ruff format, mypy and the coverage gate are green.
