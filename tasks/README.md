# Test-health remediation tasks

Source: `.dev-team-reports/test-health-2026-10-18.md` (local, gitignored), plus the
`cd-test-architecture` and `test-design` reports it links to.

Baseline at 84761d3: 229 tests green, 80% branch coverage, Farley 8.5. Critical-logic
mutation scores: `fetch_torrents.py` 70.9%, `torrent_scrape.py` 82.6%, `configure_transmission.py` 89.8%.

Every task with testable behavior follows the CLAUDE.md rule: write the failing test first,
confirm it fails for the expected reason, implement, then run
`python -m unittest discover -s tests -v` until it is green. Line numbers are as of 84761d3,
so search for the function name if they have drifted.

## Targets ("a better place")

Re-measured on 2026-10-21 at 6d38346 after round 3 (task 50): 522 tests
green (515 at 6d38346 plus the 7 task 50 added). A timeout counts as a
kill. The scores come from full mutmut 2.5.1 runs over all three modules,
with the whole suite as the runner. The task 27 and task 38 numbers are
kept for comparison.

Since task 41 only literals inside log calls and exception messages are
excluded. Any other literal survivor (a URL scheme, a separator, a codec
error handler, a default value) is triaged like a behavioural one: test it,
simplify the code, or accept it below as an equivalent with a reason. The
task 27 and 38 columns used the older, wider rule (every string-literal
survivor excluded), so the round-3 scores are stricter, not worse: every
survivor they count is an accepted equivalent.

`fetch_torrents.py` was measured with task 50's tests and its two
simplifications on top of 6d38346. The other two modules didn't change, so
their runs are at 6d38346.

| Metric | Baseline (84761d3) | Target | Task 27 | Task 38 (209292c) | Now (6d38346, 2026-10-21) |
| --- | --- | --- | --- | --- | --- |
| Mutation score, critical `fetch_torrents.py` functions¹ | 70.9% | ≥ 90% | 100% (258/258) | 100% | **99.2%** (259/261) |
| Mutation score, critical `torrent_scrape.py` functions | 82.6% | ≥ 90% | 100% (247/247) | 100% | **99.2%** (252/254, the whole module) |
| Mutation score, all of `fetch_torrents.py` | — | — | 88.6% (915/1033) | 99.3% (1040/1047) | **99.0%** (1063/1074) |
| Mutation score, all of `torrent_scrape.py` | — | — | — | 99.6% (248/249) | **99.2%** (252/254) |
| Mutation score, `configure_transmission.py` | 89.8% | — | 96.7% (87/90) | 96.8% (90/93) | **91.8%** (90/98) |
| Branch coverage, total | — | — | 96.8% | 99.1% (CI `fail_under = 97`) | **100%** (CI `fail_under = 99`) |
| Branch coverage, `fetch_torrents.py` | 75% | ≥ 90% | 96% | 99.2% | **100%** |
| Tests / Farley Score | 229 / 8.5 | — | 383 / 8.41 | 493 / 8.33 (at 01b77ce) | **522** / **8.40** (515 tests, at 6d38346) |
| CI gates | unittest only | unittest + ruff + mypy + container smoke | met | met, plus ruff `S`, shellcheck, hadolint, a smoke check that the daily fetch run starts, and CI Python and deps pinned to Alpine's | **met**, plus actionlint; the pushed image is the tested one |
| Scraper drift detection | none | recorded pages in the merge check + a scheduled live job | met | met; `scripts/live_check.py` itself is tested offline | **met**; the drift jobs' Python is pinned |

¹ The ratio gate, the cleanup planners and the parsers they rely on:
`should_fetch_torrent`, `_should_fetch_devuan`, `parse_version_type`,
`version_to_tuple`, `get_previous_ratios`, `plan_cleanup`,
`_old_version_candidates`, `_devuan_sort_key`, `plan_stagnation_cleanup`,
`update_ratio_history`, `plan_disk_pressure_cleanup`, `has_unmet_demand`,
`should_recheck_old_release`, `_safe_watch_path`, `filter_low_demand`.

Every survivor counted above is an accepted equivalent (listed under
"Accepted equivalent mutants" below):
- `fetch_torrents.py` (11): `logger.propagate = None`, the two
  `.get("seeders", 0)` defaults, the three `getattr(torrent, "ratio", 0.0)`
  defaults, `break` → `continue` in `enforce_disk_usage_limit`, and (new
  under the narrowed rule) the `""` defaults in `parse_log_level` and
  `parse_int` and the two halves of `_old_version_candidates`' Devuan group
  key. The last two are the critical-set survivors.
- `torrent_scrape.py` (2): `usedforsecurity=False` → `True` on the info-hash
  SHA-1, which only differs on a FIPS-restricted OpenSSL build, and
  `safe=""` → `safe="XXXX"` in `build_scrape_request_url`.
- `configure_transmission.py` (8): `save_settings`' `indent` and
  `sort_keys`, the five `""` defaults (task 41), and the `__main__` guard on
  the last line, which mutmut leaves untested.

The narrowed rule's re-measure (task 50) found 18 non-message literal
survivors in `fetch_torrents.py`. 14 were real gaps, now tested: which
fetcher and old-release discovery each distro is wired to, the field name
each invalid numeric setting is reported and enforced under, no warning for
an unset `FETCH_TORRENTS_DISTROS`, the `/logs` default and the logger's
name. Two were removed by simplifying the code: the temp file's unused
`.torrent` suffix and `enforce_disk_usage_limit`'s `download_path` default,
which `run()` always overrides. The other four are the new equivalents
above. The other two modules had no new survivors beyond message text.

Farley Score is 8.40 across 515 tests at 6d38346 (from the `/test-health`
re-run, `.dev-team-reports/test-health-2026-10-21-r3.md`, local).

The survivor list is in a scratch run, not the repo: rerun `mutmut run` and
`mutmut results` to see the current set. Run it with
`PYTHONDONTWRITEBYTECODE=1` (mutmut rewrites files in place, and a mutant
that keeps the file size can otherwise run from a stale `.pyc`), and on
Windows with `PYTHONUTF8=1` if output is redirected to a file.

## Order

| # | Task | Priority | Class | Depends on | Status |
| --- | --- | --- | --- | --- | --- |
| 10 | [Ratio gate boundaries and branches](10-ratio-gate-boundaries.md) | P1 | NO_REFACTOR | — | done |
| 11 | [Test `get_previous_ratios` in-process](11-get-previous-ratios-tests.md) | P1 | NO_REFACTOR | — | done |
| 12 | [Isolate tests from env vars and the clock](12-test-env-clock-isolation.md) | P1 | NO_REFACTOR | — | done |
| 13 | [Fix `bdecode` accepting/mis-reporting truncated input](13-bdecode-truncated-input.md) | P1 (bug) | NO_REFACTOR | — | done |
| 14 | [Cleanup planning boundary tests](14-cleanup-boundaries.md) | P2 | NO_REFACTOR | 12 | done |
| 15 | [Add ruff + mypy to CI](15-ci-static-gates.md) | P2 | CI | — | done |
| 16 | [Dev tooling: coverage + mutmut in requirements-dev](16-dev-tooling-coverage-mutation.md) | P2 | CI | — | done |
| 17 | [Lock in daily-run behavior with a `runpy` test](17-daily-run-characterization.md) | P2 | NO_REFACTOR | 12 | done |
| 18 | [Extract `run()` and `configure_logging()`](18-extract-run-and-logging.md) | P2 | REFACTOR_REQUIRED | 17 | done |
| 19 | [Inject `today` / client / config into the `cleanup_*` functions](19-inject-cleanup-seams.md) | P2 | REFACTOR_REQUIRED | 17 | done |
| 20 | [Transmission client double that can't drift](20-transmission-double-fidelity.md) | P3 | REFACTOR_REQUIRED | 19 | done |
| 21 | [Recorded-page scraper contract tests (+ `fetch_kali_latest`)](21-scraper-contract-tests.md) | P2 | NO_REFACTOR | — | done |
| 22 | [Container smoke test in the build job](22-container-smoke-test.md) | P2 | CI | — | done |
| 23 | [Scheduled live-drift job](23-scheduled-live-drift-job.md) | P3 | CI | 21, 22 | done |
| 24 | [Parser gaps: bencode str, UDP parsers, `parse_version_type`](24-parser-gaps.md) | P3 | NO_REFACTOR | 13 | done |
| 25 | [`configure_transmission.main` end-to-end test](25-configure-transmission-main.md) | P3 | NO_REFACTOR | — | done |
| 26 | [Tighten weak assertions and consolidate fixtures](26-assertions-and-fixtures.md) | P3 | NO_REFACTOR | 10, 14 | done |
| 27 | [Re-measure and record the new baseline](27-remeasure-baseline.md) | P3 | — | all | done |

All tasks are done. `tests/test_fetch_torrents.py`, which the task files refer to,
was split by concern in task 26 (see CLAUDE.md for the new module list).

## Round 2 (from the 2026-10-19 test-health review)

Source: `.dev-team-reports/test-health-2026-10-19.md` and
`.dev-team-reports/test-design-2026-10-19.md` (local, gitignored). Farley Score was 8.41
across 383 tests at 7080bbd.

The review's top five items were done straight away, without task files:

| Item | Commit |
| --- | --- |
| `FakeDisk` honours `delete_data`; disk-pressure and stagnation boundaries pinned | 90c7f8f |
| Old-release check tested sociably (real evaluation, faked network only) | db38abe |
| Daily-run counters, timing, disk report, RPC credentials | b4d010a |
| Logging routing, `parse_log_level`, always-log prefix contract | aa81ef3 |

Re-measured at aa81ef3: 423 tests green, 99% branch coverage. `fetch_torrents.py`
mutation score is 95.4% (1027/1076), up from 88.6%, with the critical set still
258/258. `torrent_scrape.py` is at 100% and `configure_transmission.py` at 96.7%
(87/90), both unchanged.

| # | Task | Priority | Class | Depends on | Status |
| --- | --- | --- | --- | --- | --- |
| 28 | [Make `wait_for_transmission_rpc` testable and test it](28-rpc-wait-seam.md) | P2 | REFACTOR_REQUIRED | — | done |
| 29 | [Inject the UDP transaction id; assert wire payloads](29-udp-transaction-id-seam.md) | P3 | REFACTOR_REQUIRED | — | done |
| 30 | [Test `scripts/live_check.py` beyond `problems()`](30-live-check-tests.md) | P2 | REFACTOR_REQUIRED | — | done |
| 31 | [`configure_transmission`: hermetic default path, boundaries](31-configure-transmission-gaps.md) | P3 | NO_REFACTOR | — | done |
| 32 | [Atomic `.torrent` writes](32-atomic-torrent-writes.md) | P2 (bug) | NO_REFACTOR | — | done |
| 33 | [`scrape_torrent` fall-through branches and SSRF edges](33-scrape-torrent-branches-and-ssrf.md) | P2 | NO_REFACTOR | — | done |
| 34 | [Mechanical test tidy-up](34-mechanical-test-tidy-up.md) | P3 | NO_REFACTOR | — | done |
| 35 | [Consolidate fixtures and the path-global seam](35-fixture-consolidation.md) | P3 | NO_REFACTOR → REFACTOR_REQUIRED | 34 | done |
| 36 | [Remaining `fetch_torrents.py` mutation survivors](36-remaining-mutation-survivors.md) | P3 | NO_REFACTOR | — | done |
| 37 | [Toolchain: smoke test, shellcheck/hadolint, ruff S, pins](37-toolchain-and-q4.md) | P2 | CI | — | done |
| 38 | [Re-measure, raise the coverage ratchet, record the baseline](38-remeasure-and-ratchet.md) | P3 | — | 28–37 | done |

### Accepted equivalent mutants (task 36)

These `fetch_torrents.py` survivors can't change behaviour, so they're accepted
rather than tested. A mutmut run that leaves only these (plus literals inside
log calls and exception messages) counts as clean:
- `.get("seeders", 0)` defaults in the old-release logging: a scrape result
  always carries `seeders`.
- `logger.propagate = False` → `None`: logging treats `None` as false.
- `getattr(torrent, "ratio", 0.0)` defaults in cleanup and disk pressure: a
  real `transmission_rpc.Torrent` always has `.ratio`.
- `break` → `continue` once `enforce_disk_usage_limit` is under the
  threshold: every later candidate fails the same check, so the only
  difference is extra disk-usage reads.
- `usedforsecurity=False` → `True` on `compute_info_hash`'s SHA-1 (task 38):
  identical except on a FIPS-restricted OpenSSL, where `True` would refuse
  SHA-1. The flag just says the hash isn't a security control.
- `safe=""` → `safe="XXXX"` in `torrent_scrape.py`'s
  `build_scrape_request_url` (task 41): `X` is an unreserved character that
  `quote_from_bytes` never escapes, so the URL is byte-for-byte the same
  (and a tracker would decode `%58` and `X` alike anyway).

In `configure_transmission.py` (task 31), `save_settings`'s `indent=4` and
`sort_keys=True` are accepted too. transmission-daemon owns settings.json and
rewrites it in its own layout when it saves, so ours is never relied on. The
fetch_torrents state files are different: only this code writes them, so
their layout is pinned in `tests/test_persistence.py`.

So are its `""` defaults (task 41): `value or ""` in `_parse_positive_int`
and `_parse_bool`, and the `env.get(..., "")` defaults for
`TRANSMISSION_PEER_LIMIT_GLOBAL`, `TRANSMISSION_PEER_LIMIT_PER_TORRENT` and
`TRANSMISSION_PORT_FORWARDING`. `"XXXX"` is not a positive integer or
`true`/`false`, so it is ignored exactly as `""` is.

Task 50 added four `fetch_torrents.py` equivalents under the narrowed rule:
- `env.get(env_var, "")` → `"XXXX"` in `parse_log_level` and `parse_int`:
  `"XXXX"` is neither a level name nor an integer, so both fall back to the
  default exactly as `""` does. (`parse_bool`'s and
  `parse_supported_distros`' are not equivalent and are tested.)
- `("devuan", "")` → `("XXdevuanXX", "")` or `("devuan", "XXXX")` as
  `_old_version_candidates`' Devuan group key: the key only collects the
  Devuan releases into one group and is never read back. Devuan torrents
  skip the per-distro grouping, so no other group can share it.

Task 36 removed three other equivalents by simplifying the code, so mutmut
no longer generates them: Arch's `max(..., key=...)` became `max()`, Fedora's
two parsers share one de-duplicating `_fedora_workstation_torrents()`, and the
duplicated zero-size-disk guard moved into `_used_percent()`. Task 50 removed
two more: the old-release check's temp file lost its unused `.torrent`
suffix, and `enforce_disk_usage_limit`'s `download_path` became a required
keyword, since `run()` always passes it.

Suggested order: 32 (a real bug), then 28, 30 and 33 (resilience and drift-job trust),
then 37, then 36, then the clean-up tasks 29, 31, 34 and 35, and finally 38.

## Round 3 (from the second 2026-10-19 test-health review)

Source: `.dev-team-reports/test-health-2026-10-19-r2.md`, plus the updated
`cd-test-architecture-linux-iso-seeder.md` and `test-design-2026-10-19-r2.md`
(local, gitignored). At 01b77ce: 493 tests green, 99.1% branch coverage, Farley 8.33,
and no flakiness across repeated, per-module and 8 shuffled-order runs. Re-running
mutmut on `torrent_scrape.py` and `configure_transmission.py` reproduced the
task 38 scores. It also showed that excluding *every* string-literal survivor
hides real gaps (tasks 40 and 41).

| # | Task | Priority | Class | Depends on | Status |
| --- | --- | --- | --- | --- | --- |
| 39 | [Push the image that was tested, not a rebuild](39-ship-the-tested-image.md) | P1 | CI | — | done |
| 40 | [https scrape URLs and non-UTF-8 tracker failure reasons](40-https-scrape-and-non-utf8-failures.md) | P2 | NO_REFACTOR | — | done |
| 41 | [Only exclude message-text literals from the mutation score](41-narrow-literal-exclusion-rule.md) | P3 | docs | 40 | done |
| 42 | [Network guard refuses UDP and DNS; stop the stderr leak](42-seal-the-network-guard.md) | P2 | NO_REFACTOR | — | done |
| 43 | [Remove first-party doubling; drop the LOW_VALUE test](43-remove-first-party-doubling.md) | P2 | NO_REFACTOR | — | done |
| 44 | [Make `log_seed_ratios_via_http`'s `auth` required](44-require-rpc-auth.md) | P3 | REFACTOR_REQUIRED | 43 | done |
| 45 | [`scrape_torrent` seams for resolution and UDP scrape](45-scrape-torrent-seams.md) | P3 | REFACTOR_REQUIRED | 42 | done |
| 46 | [The last untested error paths; raise the ratchet](46-remaining-error-paths.md) | P3 | NO_REFACTOR | — | done |
| 47 | [Consolidate tests: oversized scenarios, conditional logic, HTTP fakes](47-test-consolidation.md) | P3 | NO_REFACTOR | 43 | done |
| 48 | [CI leftovers: drift-job Python pin, actionlint](48-ci-leftovers.md) | P3 | CI | — | done |
| 49 | [Offline tests for `record_fixtures.py` / `transmission_roundtrip.py`](49-offline-tests-for-fixture-scripts.md) | P3 | REFACTOR_REQUIRED | — | done |
| 50 | [Re-measure round 3; optional seeding-policy table](50-remeasure-round-3.md) | P3 | — | 39–49, 51 | done |
| 51 | [A failing old-release check must not abort the daily run](51-guard-old-release-step.md) | P2 (bug) | NO_REFACTOR | — | done |

Task 51 came from a review of this branch's production changes, not from the test-health report.

Task 50 recorded the new numbers under "Targets" above. It also added
[docs/seeding-policy.md](../docs/seeding-policy.md), the business-readable
seeding policy (Q2). Each rule there names the tests that pin it, and
`tests/test_repo_hygiene.py` fails if a named test no longer exists. The
`/test-health` re-run (`.dev-team-reports/test-health-2026-10-21-r3.md`,
local) compared with r2 as follows:
- Farley Score went from 8.33 to 8.40, and Exemplary tests from 40 to 82.
- Branch coverage reached 100%, and every r2 CD-pipeline gap is closed.
- Test-design findings fell from 38 to 28, with all five r2 errors fixed.
- What's left is local hygiene: a missing `double-waiver` marker on the
  `scrape_torrent` double in `tests/helpers.py`, and `test_record_fixtures`
  patching `record` because `main()` has no `record=` seam.

Suggested order: 39 (untested bits reach users), then 51 (a bad setting silently disables cleanup), then 40 and 41 (a hidden scrape gap
and the rule that hid it), 42, 43 then 44 and 47, 45, 46, 49 and 48, and finally 50.

## Round 3 follow-ups

Issues the round-3 agents found and left alone because they were outside their tasks or need a live run.

| # | Task | Priority | Class | Depends on | Status |
| --- | --- | --- | --- | --- | --- |
| 52 | [Ratio logging must work when RPC credentials are set](52-rpc-handshake-auth.md) | P2 (suspected bug) | NO_REFACTOR | — | done |
| 53 | [Lint and test workflow-only changes in CI](53-lint-workflow-only-changes.md) | P3 | CI | — | done |
| 54 | [Verify the build-once release flow on GitHub](54-verify-release-flow-on-ci.md) | P2 | CI (manual) | 39, 48 | open |
| 55 | [Round-3 hygiene leftovers: `record=` seam, tracker double marker](55-record-fixtures-main-seam.md) | P3 | REFACTOR_REQUIRED | 49 | done |

Suggested order: 54 as soon as the round-3 PR runs, then 52 (step 1 decides whether it is a bug at all), 53, and 55.

## Optional: tests coupled to implementation

A 2026-10-22 review asked whether the suite breaks when the implementation changes but the logic doesn't. Mostly it doesn't: tests fake at the I/O boundary (HTTP, sockets, Transmission, disk, clock), the doubles are checked against the pinned library, and the logic is tested as pure functions. The spots below are the exceptions. None of them is a bug. They are known and left as they are on purpose, so pick them up only if a refactor trips over them or there's spare time.

| # | Task | Priority | Class | Depends on | Status |
| --- | --- | --- | --- | --- | --- |
| 56 | [UDP scrape tests: assert on datagrams, not socket method calls](56-udp-scrape-fake-socket.md) | P4 (optional) | NO_REFACTOR | — | done |
| 57 | [HTTP scrape tests: assert on the requested URL, not `requests.get`'s arguments](57-http-scrape-assert-on-requested-url.md) | P4 (optional) | NO_REFACTOR | — | done |
| 58 | [Tests that pin private helpers' internals](58-private-helper-tests.md) | P4 (optional) | NO_REFACTOR | 56 (soft) | done |
| 59 | [Cleanup tests that pin the exact RPC call sequence](59-cleanup-exact-rpc-sequence.md) | P4 (optional) | NO_REFACTOR | — | done |

Suggested order: 59 (smallest), then 56 and 58 together, then 57. Each task says how to prove the change worked: temporarily make the refactor the old test would have blocked, check the suite stays green, then revert it.
