# 16 — Dev tooling: coverage + mutmut in requirements-dev

**Priority**: P2 · **Class**: CI/config · **Depends on**: —

## Problem
The test-health audit had to install `coverage` and `mutmut` 2.5.1 ad hoc. `.claude/CLAUDE.md`
mentions `mutmut run` (mutmut<3), but neither tool is in `requirements-dev.txt` and there's no mutmut
config. That makes the baseline in `tasks/README.md` hard to reproduce.

## Acceptance criteria
- `requirements-dev.txt` includes pinned `coverage` and `mutmut<3`.
- Coverage config (`[tool.coverage]` or `.coveragerc`): `branch = true`, `source` = the three modules, omit `tests/`.
- Mutmut config: `paths_to_mutate` = the three modules, `runner = python -m unittest discover -s tests`, `tests_dir = tests/`.
- `.gitignore` covers `.mutmut-cache`, `mutants/`, `.coverage`, `htmlcov/`.
- CI `test` job: run unittest under `coverage run --branch` and print `coverage report`. Report only; don't add a fail-under threshold yet (task 27 sets one).
- `.claude/CLAUDE.md` Commands section lists the coverage command.

## Notes
Mutmut doesn't belong in the per-push merge check: the full run takes about 40 minutes on Windows. If
a scheduled mutation job is wanted, it fits in task 23's scheduled workflow.
