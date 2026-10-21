# 46 — The last untested error paths; raise the ratchet

**Priority**: P3 · **Class**: NO_REFACTOR · **Depends on**: —

## Evidence
Branch coverage at 01b77ce is 99% (9 lines and 5 partial branches missed):
- `fetch_torrents.py:1833-1834`: `run()` logs `Could not query Transmission: ...` when `log_seed_ratios_via_http` raises (401/500, or no session header → `KeyError`). No test covers it.
- `fetch_torrents.py:458`, `:475-478` (`get_previous_ratios`): the parse-error warnings for stored and removed-history ratio entries, and the other-distro branch in the removed-history loop.
- `fetch_torrents.py:543-544`: cleaning up the temp file itself fails after a failed atomic write.
- `fetch_torrents.py:1290-1291`: `_remove_watch_file` hits an `OSError` other than `FileNotFoundError` (e.g. a directory with the torrent's name).
- `torrent_scrape.py:91`: a bencoded dict with a non-bytes key. `:147->145` and `:151->156`: duplicate announce-list URLs and a primary `announce` already in the list.
- The four JSON stores' `OSError` branch (`tests/test_persistence.py:60`; test-design row 29).

## Acceptance criteria
1. A `RunTests` case where `FakeTransmissionRpc` returns 500 (or raises): the error is logged with that message, and cleanup and the run summary still happen.
2. One test per remaining path above, asserting the observable outcome (return value, log message, file state), not just that the line ran.
3. `coverage report` shows 100% on all three modules, or each remaining miss has a `# pragma: no cover` with its reason.
4. Raise `fail_under` in `pyproject.toml` to about 1 point under the CI-measured total. Check the CI number first, as in task 38.
