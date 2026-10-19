# 21 — Recorded-page scraper contract tests (+ `fetch_kali_latest`)

**Priority**: P2 · **Class**: NO_REFACTOR · **Depends on**: —

## Problem
The likeliest production failure is a distro site changing its page layout, but each `Fetch*NamingTests`
feeds a hand-written HTML/text snippet of about 5 lines into the scraper. Those snippets encode what the
author *thinks* the page looks like, so drift can't be detected. Also, `fetch_kali_latest`
(`fetch_torrents.py:576–601`) has **no test at all**, and the error paths of
`fetch_devuan_latest`, `fetch_linuxmint_cinnamon`, `fetch_fedora_workstation` and
`fetch_arch_latest` are uncovered (`:660–760`).

## Acceptance criteria
- `tests/fixtures/pages/<distro>/<date>.html|txt`: one **real** captured response per upstream endpoint each fetcher hits. Capture them with a small script (`scripts/record_fixtures.py`, run by hand or by task 23's job) that writes the fixture plus a `.meta.json` with the URL and capture date.
- A shared `fake_response(fixture_path_or_text, status=200)` helper, replacing the ~17 ad-hoc `FakeResponse` classes (shared with task 26).
- For each fetcher, a test that replays the recorded pages and asserts the **exact** candidate names and URLs expected for that snapshot.
- `fetch_kali_latest`: happy path plus "page has no recognizable version" → empty result, no exception.
- Each fetcher's failure paths: HTTP 404/500, a connection error, and a page with the expected element missing. Each returns empty and logs. This covers the uncovered `except` branches.
- No network access in the merge check (a socket guard like the one cd-test-architecture used is a good addition).

## Notes
VCR.py/`responses` aren't needed; `patch.object(ft.requests, 'get', side_effect=url_router)` reading fixtures
by URL is enough and adds no dependency. The fixtures are only snapshots, so task 23 refreshes them and
compares against the live sites on a schedule.
