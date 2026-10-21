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

Re-measured on 2026-10-19 at 209292c after round 2 (task 38): 493 tests
green. Mutation scores are honest: string-literal-only survivors (log and
error text) are excluded, and a timeout counts as a kill. They come from
full mutmut 2.5.1 runs over all three modules, with the whole suite as the
runner. The task 27 numbers are kept for comparison.

| Metric | Baseline (84761d3) | Target | Task 27 | Now (209292c) |
| --- | --- | --- | --- | --- |
| Mutation score, critical `fetch_torrents.py` functions¹ | 70.9% | ≥ 90% | 100% (258/258) | **100%** |
| Mutation score, critical `torrent_scrape.py` functions | 82.6% | ≥ 90% | 100% (247/247) | **100%** |
| Mutation score, all of `fetch_torrents.py` | — | — | 88.6% (915/1033) | **99.3%** (1040/1047) |
| Mutation score, all of `torrent_scrape.py` | — | — | — | **99.6%** (248/249) |
| Mutation score, `configure_transmission.py` | 89.8% | — | 96.7% (87/90) | **96.8%** (90/93) |
| Branch coverage, total | — | — | 96.8% | **99.1%** (CI `fail_under = 97`) |
| Branch coverage, `fetch_torrents.py` | 75% | ≥ 90% | 96% | **99.2%** |
| CI gates | unittest only | unittest + ruff + mypy + container smoke | met | **met**, plus ruff `S`, shellcheck, hadolint, a smoke check that the daily fetch run starts, and CI Python and deps pinned to Alpine's |
| Scraper drift detection | none | recorded pages in the merge check + a scheduled live job | met | **met**; `scripts/live_check.py` itself is now tested offline |

¹ The ratio gate, the cleanup planners and the parsers they rely on:
`should_fetch_torrent`, `_should_fetch_devuan`, `parse_version_type`,
`version_to_tuple`, `get_previous_ratios`, `plan_cleanup`,
`_old_version_candidates`, `_devuan_sort_key`, `plan_stagnation_cleanup`,
`update_ratio_history`, `plan_disk_pressure_cleanup`, `has_unmet_demand`,
`should_recheck_old_release`, `_safe_watch_path`, `filter_low_demand`.

Every remaining behavioural survivor is an accepted equivalent (listed under
"Accepted equivalent mutants" below):
- `fetch_torrents.py` (7): `logger.propagate = None`, the two
  `.get("seeders", 0)` defaults, the three `getattr(torrent, "ratio", 0.0)`
  defaults, and `break` → `continue` in `enforce_disk_usage_limit`.
- `torrent_scrape.py` (1): `usedforsecurity=False` → `True` on the info-hash
  SHA-1, which only differs on a FIPS-restricted OpenSSL build.
- `configure_transmission.py` (3): `save_settings`' `indent` and
  `sort_keys`, plus the `__main__` guard on the last line, which mutmut
  leaves untested.

Farley Score was not re-measured; it was 8.41 at 7080bbd. Rerun
`/test-health` for a fresh report.

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
rather than tested. A mutmut run that leaves only these (plus string-literal
mutants) counts as clean:
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

In `configure_transmission.py` (task 31), `save_settings`'s `indent=4` and
`sort_keys=True` are accepted too. transmission-daemon owns settings.json and
rewrites it in its own layout when it saves, so ours is never relied on. The
fetch_torrents state files are different: only this code writes them, so
their layout is pinned in `tests/test_persistence.py`.

Task 36 removed three other equivalents by simplifying the code, so mutmut
no longer generates them: Arch's `max(..., key=...)` became `max()`, Fedora's
two parsers share one de-duplicating `_fedora_workstation_torrents()`, and the
duplicated zero-size-disk guard moved into `_used_percent()`.

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
| 40 | [https scrape URLs and non-UTF-8 tracker failure reasons](40-https-scrape-and-non-utf8-failures.md) | P2 | NO_REFACTOR | — | open |
| 41 | [Only exclude message-text literals from the mutation score](41-narrow-literal-exclusion-rule.md) | P3 | docs | 40 | open |
| 42 | [Network guard refuses UDP and DNS; stop the stderr leak](42-seal-the-network-guard.md) | P2 | NO_REFACTOR | — | open |
| 43 | [Remove first-party doubling; drop the LOW_VALUE test](43-remove-first-party-doubling.md) | P2 | NO_REFACTOR | — | open |
| 44 | [Make `log_seed_ratios_via_http`'s `auth` required](44-require-rpc-auth.md) | P3 | REFACTOR_REQUIRED | 43 | open |
| 45 | [`scrape_torrent` seams for resolution and UDP scrape](45-scrape-torrent-seams.md) | P3 | REFACTOR_REQUIRED | 42 | open |
| 46 | [The last untested error paths; raise the ratchet](46-remaining-error-paths.md) | P3 | NO_REFACTOR | — | open |
| 47 | [Consolidate tests: oversized scenarios, conditional logic, HTTP fakes](47-test-consolidation.md) | P3 | NO_REFACTOR | 43 | open |
| 48 | [CI leftovers: drift-job Python pin, actionlint](48-ci-leftovers.md) | P3 | CI | — | open |
| 49 | [Offline tests for `record_fixtures.py` / `transmission_roundtrip.py`](49-offline-tests-for-fixture-scripts.md) | P3 | REFACTOR_REQUIRED | — | open |
| 50 | [Re-measure round 3; optional seeding-policy table](50-remeasure-round-3.md) | P3 | — | 39–49, 51 | open |
| 51 | [A failing old-release check must not abort the daily run](51-guard-old-release-step.md) | P2 (bug) | NO_REFACTOR | — | done |

Task 51 came from a review of this branch's production changes, not from the test-health report.

Suggested order: 39 (untested bits reach users), then 51 (a bad setting silently disables cleanup), then 40 and 41 (a hidden scrape gap
and the rule that hid it), 42, 43 then 44 and 47, 45, 46, 49 and 48, and finally 50.
