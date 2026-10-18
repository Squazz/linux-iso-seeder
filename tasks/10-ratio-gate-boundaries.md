# 10 — Ratio gate boundaries and branches

**Priority**: P1 · **Class**: NO_REFACTOR · **Depends on**: — (do it alongside 12; the tests here must pin `SKIP_RATIO_CHECK`)

## Problem
`should_fetch_torrent` / `_should_fetch_devuan` are the project's core business rule: don't fetch
a new release until the previous one has reached ratio 1.0. Every line of them runs in tests, but
mutation testing shows the tests don't pin the outcomes. Only 67% of `should_fetch_torrent` mutants
are killed, and one branch never runs at all.

## Evidence (mutmut survivors, `fetch_torrents.py`)
- `:434` and `:374`: `>= 1.0` → `> 1.0` survives. No test has a previous ratio of exactly 1.0.
- `:432`: `return True  # no previous version` → `False` survives, and coverage shows the line is never executed.
- `:430`: `v < version` → `v <= version` survives.
- `:364`: `n != name and DEVUAN_NAME_PATTERN.match(n)` → `or` survives. A non-Devuan ratio can count as the "prior Devuan" ratio.
- `:386–399`: the `SKIP_RATIO_CHECK`, unknown-distro and unparseable-name branches can all be flipped to `return False` without a test failing.
- `:416`: the documented rule that a live ratio beats the removed-history ratio for the same name is never asserted.

## Acceptance criteria
- Prior version ratio exactly `1.0` → fetch (`True`); `0.999` → don't fetch (`False`). Do this for both a standard distro and Devuan.
- Only *newer* versions in `ratios` (no older one) → `True`. This must execute L432.
- `ratios` contains the *same* version as `name` only → behavior asserted explicitly. The `<` vs `<=` boundary at L430 must be killed.
- Devuan: `ratios` mixing a low-ratio non-Devuan torrent with a high-ratio Devuan one → the decision uses only the Devuan ratio.
- Name in both `ratios` (live) and `removed_history` with different ratios → the live value decides.
- `SKIP_RATIO_CHECK=true` → `True` even with a low prior ratio. Unknown distro → `True`. Unparseable name of a known distro → `True` (and logs an error).
- Re-running mutmut on `should_fetch_torrent` / `_should_fetch_devuan`: all the survivors listed above are killed.

## Approach
1. Add the cases to the existing `ShouldFetchTorrent*` classes in `tests/test_fetch_torrents.py`. Wrap each class in `patch.dict(os.environ, {'SKIP_RATIO_CHECK': 'false'})` in `setUp`, so the developer's shell can't flip them (see task 12).
2. Each new test should fail when the corresponding mutant is applied by hand. Confirm this for at least the `>=` and L432 cases.
3. No production change is expected. If a test exposes a real bug, fix it test-first in this task.
