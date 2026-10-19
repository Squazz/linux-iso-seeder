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

Re-measured on 2026-10-19 after tasks 10–26 (task 27): 383 tests green.
Mutation scores are honest (string-literal-only survivors excluded). They
come from full mutmut 2.5.1 runs with the whole suite as the runner.

| Metric | Baseline (84761d3) | Target | Now |
| --- | --- | --- | --- |
| Mutation score, critical `fetch_torrents.py` functions¹ | 70.9% | ≥ 90% | **100%** (258/258) |
| Mutation score, critical `torrent_scrape.py` functions | 82.6% | ≥ 90% | **100%** (247/247, every function) |
| Mutation score, `configure_transmission.py` | 89.8% | — | 96.7% (87/90) |
| Mutation score, all of `fetch_torrents.py` | — | — | 88.6% (915/1033) |
| Branch coverage, `fetch_torrents.py` | 75% | ≥ 90% | **96%** (total 96.8%; CI `fail_under = 94`) |
| CI gates | unittest only | unittest + ruff + mypy + container smoke | **met**: also the in-image unit suite, hostile env, coverage ratchet |
| Scraper drift detection | none | recorded pages in the merge check + a scheduled live job | **met**: `tests/test_scrapers.py` + `.github/workflows/drift.yml` |

¹ The ratio gate, the cleanup planners and the parsers they rely on:
`should_fetch_torrent`, `_should_fetch_devuan`, `parse_version_type`,
`version_to_tuple`, `get_previous_ratios`, `plan_cleanup`,
`_old_version_candidates`, `_devuan_sort_key`, `plan_stagnation_cleanup`,
`update_ratio_history`, `plan_disk_pressure_cleanup`, `has_unmet_demand`,
`should_recheck_old_release`, `_safe_watch_path`, `filter_low_demand`.

Remaining survivors (not critical logic, left as follow-ups) are mostly in
the I/O and orchestration layer:
- `run` (9), `_fetch_latest` (5), `_check_old_releases` (2)
- `check_old_releases_for_demand` (21), `evaluate_old_release_demand` (7)
- `enforce_disk_usage_limit` (10), `cleanup_stagnant_torrents` (5),
  `cleanup_old_versions` (3)
- `configure_logging` (6), `parse_log_level` (3), `wait_for_transmission_rpc` (6)
- the `save_*` temp-file handling (2 each)

The list is in a scratch run, not the repo: rerun `mutmut run` and
`mutmut results` to see the current set.

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
| 29 | [Inject the UDP transaction id; assert wire payloads](29-udp-transaction-id-seam.md) | P3 | REFACTOR_REQUIRED | — | open |
| 30 | [Test `scripts/live_check.py` beyond `problems()`](30-live-check-tests.md) | P2 | REFACTOR_REQUIRED | — | open |
| 31 | [`configure_transmission`: hermetic default path, boundaries](31-configure-transmission-gaps.md) | P3 | NO_REFACTOR | — | open |
| 32 | [Atomic `.torrent` writes](32-atomic-torrent-writes.md) | P2 (bug) | NO_REFACTOR | — | done |
| 33 | [`scrape_torrent` fall-through branches and SSRF edges](33-scrape-torrent-branches-and-ssrf.md) | P2 | NO_REFACTOR | — | open |
| 34 | [Mechanical test tidy-up](34-mechanical-test-tidy-up.md) | P3 | NO_REFACTOR | — | open |
| 35 | [Consolidate fixtures and the path-global seam](35-fixture-consolidation.md) | P3 | NO_REFACTOR → REFACTOR_REQUIRED | 34 | open |
| 36 | [Remaining `fetch_torrents.py` mutation survivors](36-remaining-mutation-survivors.md) | P3 | NO_REFACTOR | — | open |
| 37 | [Toolchain: smoke test, shellcheck/hadolint, ruff S, pins](37-toolchain-and-q4.md) | P2 | CI | — | open |
| 38 | [Re-measure, raise the coverage ratchet, record the baseline](38-remeasure-and-ratchet.md) | P3 | — | 28–37 | open |

Suggested order: 32 (a real bug), then 28, 30 and 33 (resilience and drift-job trust),
then 37, then 36, then the clean-up tasks 29, 31, 34 and 35, and finally 38.
