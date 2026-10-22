---
name: pr
description: Verify and open a pull request for linux-iso-seeder — runs lint, typecheck, and the full unittest suite before `gh pr create`. Use when the user says "open a PR", "create a PR", or "ship this branch".
---

# Create PR (linux-iso-seeder)

1. Refuse if on `main`; branch first.
2. Run, in order, and stop on the first failure (report its output; do not open the PR):
   - `ruff check .`
   - `ruff format --check .`
   - `mypy` (files and settings come from `pyproject.toml`)
   - `python -m unittest discover -s tests -v` (Windows: `.venv/Scripts/python -m unittest discover -s tests -v`; the system `py` lacks the test deps) — must pass; CI gates the Docker build on this.
3. Push the branch and run `gh pr create --base main` with a summary of the change and the test result.
