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

| Metric | Now | Target |
| --- | --- | --- |
| Mutation score, critical `fetch_torrents.py` functions | 70.9% | ≥ 90% |
| Mutation score, critical `torrent_scrape.py` functions | 82.6% | ≥ 90% |
| Branch coverage, `fetch_torrents.py` | 75% | ≥ 90% (once `run()` exists) |
| CI gates | unittest only | unittest + ruff + mypy + container smoke |
| Scraper drift detection | none | recorded pages in the merge check + a scheduled live job |

## Order

| # | Task | Priority | Class | Depends on |
| --- | --- | --- | --- | --- |
| 10 | [Ratio gate boundaries and branches](10-ratio-gate-boundaries.md) | P1 | NO_REFACTOR | — |
| 11 | [Test `get_previous_ratios` in-process](11-get-previous-ratios-tests.md) | P1 | NO_REFACTOR | — |
| 12 | [Isolate tests from env vars and the clock](12-test-env-clock-isolation.md) | P1 | NO_REFACTOR | — |
| 13 | [Fix `bdecode` accepting/mis-reporting truncated input](13-bdecode-truncated-input.md) | P1 (bug) | NO_REFACTOR | — |
| 14 | [Cleanup planning boundary tests](14-cleanup-boundaries.md) | P2 | NO_REFACTOR | 12 |
| 15 | [Add ruff + mypy to CI](15-ci-static-gates.md) | P2 | CI | — |
| 16 | [Dev tooling: coverage + mutmut in requirements-dev](16-dev-tooling-coverage-mutation.md) | P2 | CI | — |
| 17 | [Lock in daily-run behavior with a `runpy` test](17-daily-run-characterization.md) | P2 | NO_REFACTOR | 12 |
| 18 | [Extract `run()` and `configure_logging()`](18-extract-run-and-logging.md) | P2 | REFACTOR_REQUIRED | 17 |
| 19 | [Inject `today` / client / config into the `cleanup_*` functions](19-inject-cleanup-seams.md) | P2 | REFACTOR_REQUIRED | 17 |
| 20 | [Transmission client double that can't drift](20-transmission-double-fidelity.md) | P3 | REFACTOR_REQUIRED | 19 |
| 21 | [Recorded-page scraper contract tests (+ `fetch_kali_latest`)](21-scraper-contract-tests.md) | P2 | NO_REFACTOR | — |
| 22 | [Container smoke test in the build job](22-container-smoke-test.md) | P2 | CI | — |
| 23 | [Scheduled live-drift job](23-scheduled-live-drift-job.md) | P3 | CI | 21, 22 |
| 24 | [Parser gaps: bencode str, UDP parsers, `parse_version_type`](24-parser-gaps.md) | P3 | NO_REFACTOR | 13 |
| 25 | [`configure_transmission.main` end-to-end test](25-configure-transmission-main.md) | P3 | NO_REFACTOR | — |
| 26 | [Tighten weak assertions and consolidate fixtures](26-assertions-and-fixtures.md) | P3 | NO_REFACTOR | 10, 14 |
| 27 | [Re-measure and record the new baseline](27-remeasure-baseline.md) | P3 | — | all |

Tasks 10–13 are independent and can run in parallel. Any task that touches
`tests/test_fetch_torrents.py` can conflict with task 26's file split, so do 26 after the
test-adding tasks rather than before.
