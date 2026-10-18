# 11 — Test `get_previous_ratios` in-process

**Priority**: P1 · **Class**: NO_REFACTOR · **Depends on**: —

## Problem
`get_previous_ratios(log_file)` (`fetch_torrents.py:163–195`) parses the previous run's ratio log.
Its output is the `ratios` input to the ratio gate (task 10). Only `RatioLogSurvivesRestartTests`
reaches it, and that runs in a subprocess, so coverage records L164–195 as unexecuted and only the
happy path is checked. The segment-selection logic is untested: last START wins, START without END,
and an END before START.

## Acceptance criteria
In-process tests, each writing a temp log file and calling `ft.get_previous_ratios(path)`:
- Missing file → `{}`.
- No markers at all → every `[ratio] name → x.yyy` line in the file is parsed.
- Two complete START/END segments → only the **last** segment's ratios are returned. An entry that exists only in the first segment must be absent.
- Last START with no END after it (a crashed run) → everything after that START is parsed.
- An END that appears before the last START is ignored.
- Names with internal spaces/padding are stripped. A ratio without a decimal point (`→ 1`) is not matched, so the current regex behavior is pinned.
- Duplicate names inside a segment → the last one wins.
- Coverage of L164–195 is 100% in the normal `unittest` run.

## Approach
Add a `GetPreviousRatiosTests` class next to `RatioLogSurvivesRestartTests`, and keep the subprocess
test as-is, since it guards the import-time truncation bug. Write the log lines in the real format
(`2026-08-01 00:00:00,000 INFO: [ratio] … → 0.664`).
