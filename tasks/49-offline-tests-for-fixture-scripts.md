# 49 — Offline tests for `record_fixtures.py` and `transmission_roundtrip.py`

**Priority**: P3 · **Class**: REFACTOR_REQUIRED · **Depends on**: —

From the test-design advisor (`test-design-2026-10-19-r2.md`, "Design recommendations").

## Evidence
- `scripts/record_fixtures.py` and `scripts/transmission_roundtrip.py` have no tests. The drift job relies on both: `record_fixtures` re-records the pages when a live scraper fails, and `transmission_roundtrip` is the real-daemon check.
- Blockers:
  - `record_fixtures.record` calls `requests.get` directly and writes to a module-global directory
  - `record_fixtures.main` calls `datetime.now` directly
  - `transmission_roundtrip.wait_for` uses `time.time`/`time.sleep` and a global `TIMEOUT_SECONDS`
- Today only the drift job checks that `record_fixtures.ENDPOINTS` matches the URLs in the recorded `.meta.json` fixtures, and only after a live failure.

## Acceptance criteria
1. First, a test with no seam needed: every `ENDPOINTS` URL matches the `url` in its fixture's `.meta.json`, and every fixture has an endpoint.
2. Test-first, add `record(..., get=requests.get, out_dir=...)` and `main(..., now=...)`. Tests:
   - `record` writes the body and meta under `<distro>/<slug>.<ext>` in a temp dir, using `helpers.fake_response`
   - `record` passes HTTP errors through
   - the `main` filter calls `record` for the requested `(distro, slug)` set (spy)
3. Test-first, add `wait_for(..., clock=time.monotonic, sleep=time.sleep, timeout=...)`, the same shape as `wait_for_transmission_rpc`. Test the success, timeout and `SystemExit` paths with a fake clock that `sleep` advances.
4. `make_torrent`: assert its structure with `torrent_scrape.bdecode`.
5. `transmission_roundtrip.main` stays untested offline: it is the integration check itself.
6. Test modules follow the CLAUDE.md conventions (`import helpers`, `setUpModule` calling `helpers.isolate_module()`).
