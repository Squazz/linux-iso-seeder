# linux-iso-seeder — dev-team project config

Testing rules and the import-stubbing pattern live in the root [CLAUDE.md](../CLAUDE.md); this file only records dev-team toolchain conventions.

## Stack
- Python 3 (runs in an Alpine container; `transmission_rpc` is apk-only)
- Docker (`Dockerfile`, `entrypoint.sh`)
- Tests: stdlib `unittest` (`tests/`)

## Commands
- Test: `python -m unittest discover -s tests -v` (Windows: `py -m unittest discover -s tests -v`)
- Lint/format: `ruff check .` / `ruff format .`
- Typecheck: `mypy fetch_torrents.py torrent_scrape.py configure_transmission.py`
- Mutation: `mutmut run` (mutmut<3)
- Dev deps: `pip install -r requirements-dev.txt` (includes `requirements-test.txt`)

## Active agent templates
- `.claude/agents/python-quality.md`
- `.claude/agents/twelve-factor-audit.md` (Dockerfile present)
