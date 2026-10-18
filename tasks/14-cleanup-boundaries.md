# 14 — Cleanup planning boundary tests

**Priority**: P2 · **Class**: NO_REFACTOR · **Depends on**: 12

## Problem
The cleanup planners decide what gets **deleted from disk**, and they're pure functions. Mutation
shows boundaries and loop control that no test pins down: `plan_stagnation_cleanup` 60%,
`_devuan_sort_key` 60%, `plan_cleanup` 67%, `_old_version_candidates` 68%.

## Evidence (mutmut survivors, `fetch_torrents.py`)
- `:1140` `plan_cleanup`: `ratio <= min_ratio` boundary. No test has ratio exactly equal to `min_ratio`.
- `:1305` `plan_stagnation_cleanup`: the ratio-delta comparison isn't tested at exactly `min_ratio_delta`.
- `:1283` `_stagnation_anchor`: an anchor sample exactly `window_days` old isn't tested.
- `:1270` / `:1274` `update_ratio_history`: the sample-interval gate and the pruning age aren't tested at their edges.
- `:1096–1112` `_old_version_candidates` and `:1303`: `continue` → `break` survives. No input list puts an unparseable, Devuan or no-anchor torrent **before** valid candidates.
- `_devuan_sort_key`: ordering ties on `added_date` aren't exercised.

## Acceptance criteria
- For each boundary, add a test at the edge value and one on each side of it, with the expected keep/remove asserted per torrent. Assert the actual lists, not only their length.
- For each `continue`, add a test whose list starts with the item that should be skipped, followed by valid candidates. All the valid candidates must still be planned.
- Re-running mutmut on these functions: ≥ 90% killed, with any remaining survivors documented as equivalent.

## Approach
Extend `PlanCleanupTests`, `PlanCleanupDevuanGroupingTests`, `PlanStagnationCleanupTests` and
`UpdateRatioHistoryTests`. Each test needs one fixed `today`, not `date.today()`.
