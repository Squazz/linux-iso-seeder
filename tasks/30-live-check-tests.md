# 30 — Test `scripts/live_check.py` beyond `problems()`

**Priority**: P2 · **Class**: REFACTOR_REQUIRED · **Depends on**: —

## Evidence
- `tests/test_live_check.py` covers only `problems()` and `distro_of()`. Untested:
  - `is_reachable` (`scripts/live_check.py:65`): HEAD 405 → GET fallback, status handling
  - `check_scrapers` (`:76`): failure aggregation, `MAY_BE_EMPTY`, "one reachable is enough"
  - `check_tracker` (`:104`): the for/else, integer validation
  - `main` (`:127`): exit codes 0/1/2 and usage
- The weekly drift job (`.github/workflows/drift.yml`) trusts these, so a bug here gives false OKs (or false alarms) while the suite stays green.
- `main()` builds `checks` locally, and the check functions call module globals (`requests`, `ft.fetch_*`, `torrent_scrape`), so they can't be tested without patching module names.

## Acceptance criteria
- Inject the collaborators with defaults:
  - `check_scrapers(fetchers=FETCHERS, reachable=is_reachable)`
  - `check_tracker(fetch=ft.fetch_ubuntu_lts, get=requests.get, scrape=torrent_scrape.scrape_torrent)`
  - `main(argv, checks=CHECKS)`
- Tests (using `helpers.fake_response`) for each branch:
  - HEAD 405 then GET 200 → reachable
  - a fetcher returning nothing (and the `MAY_BE_EMPTY` exception)
  - every candidate unreachable vs one reachable
  - a tracker with no integer seeders/leechers
  - `main` exit codes: all OK → 0, a problem → 1, bad usage → 2
- The `sys.path.insert` in `test_live_check.py:13` is undone after the module (or comes from `helpers.REPO_ROOT`).
