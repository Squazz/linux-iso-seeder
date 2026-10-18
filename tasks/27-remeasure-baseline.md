# 27 — Re-measure and record the new baseline

**Priority**: P3 · **Class**: — · **Depends on**: the other tasks (can run after any milestone)

## Acceptance criteria
- Re-run `/dev-team:test-health` and compare against the targets in `tasks/README.md`:
  - critical-function mutation ≥ 90% for `fetch_torrents.py` and `torrent_scrape.py`
  - `fetch_torrents.py` branch coverage ≥ 90%
  - ruff, mypy and container smoke in CI
- Set `coverage report --fail-under=<achieved − 2>` in CI (task 16's step), so coverage can only ratchet upward.
- Update the table in `tasks/README.md` with the new numbers and remove the finished task files, or mark them done.
