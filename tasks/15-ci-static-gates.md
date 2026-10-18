# 15 — Add ruff + mypy to CI

**Priority**: P2 · **Class**: CI (no test-first) · **Depends on**: —

## Problem
`.claude/CLAUDE.md` lists `ruff check .` and `mypy …` as project commands, but CI
(`.github/workflows/docker-image.yml`, `test` job) runs only unittest. Current state on 84761d3:
- `ruff check .`: **42 errors** (6 auto-fixable).
- `mypy fetch_torrents.py torrent_scrape.py configure_transmission.py`: **2 errors**, both in `fetch_torrents.py`. One is a missing-stubs note for an import at L14. The other is at L1048, where the `json=` argument to `requests.post` has type `dict[str, Collection[str]]`.

## Acceptance criteria
- `ruff check .` and the mypy command both exit 0 locally.
  - Fix the code where the finding is real. Where it's noise, use a targeted `# noqa` / `# type: ignore[code]` with a reason, or a rule exclusion in config.
  - Missing stubs for `transmission_rpc`: use `ignore_missing_imports` scoped to that module only.
- Ruff and mypy settings live in config (`pyproject.toml` or `ruff.toml` + `mypy.ini`), so CI and local runs agree.
- The `test` job installs `requirements-dev.txt` and runs `ruff check .` and mypy before unittest. The build job is still gated on `test`.
- Don't run `ruff format` as part of this task, so the diff stays reviewable. Add a `ruff format --check` step in a separate PR if it's wanted.

## Notes
`requirements-dev.txt` doesn't pin versions. Pin `ruff` and `mypy` so new upstream rules don't
break CI without warning.
