# linux-iso-seeder — dev-team project config

Testing rules and the import-stubbing pattern live in the root [CLAUDE.md](../CLAUDE.md); this file only records dev-team toolchain conventions.

## Stack
- Python 3 (runs in an Alpine container; `transmission_rpc` comes from apk there, pinned from PyPI for tests)
- Docker (`Dockerfile`, `entrypoint.sh`)
- Tests: stdlib `unittest` (`tests/`)

## Commands
- Test: `python -m unittest discover -s tests -v` (Windows: `py -m unittest discover -s tests -v`)
- Lint/format: `ruff check .` / `ruff format .`
- Typecheck: `mypy` (files and settings in `pyproject.toml`)
- CI's `test` job runs ruff check (defaults + bandit `S`), ruff format --check, mypy, shellcheck and hadolint before the tests; Python versions are pinned in `requirements-dev.txt`, the shellcheck/hadolint images in `.github/workflows/docker-image.yml` (commands in CONTRIBUTING.md)
- Coverage: `coverage run -m unittest discover -s tests` then `coverage report` (branch coverage; config in `pyproject.toml`, which also sets the `fail_under` ratchet CI enforces)
- Mutation: `mutmut run` (mutmut<3; config in `pyproject.toml`, see CONTRIBUTING.md)
- Dev deps: `pip install -r requirements-dev.txt` (includes `requirements-test.txt`)

## Active agent templates
- `.claude/agents/python-quality.md`
- `.claude/agents/twelve-factor-audit.md` (Dockerfile present)
