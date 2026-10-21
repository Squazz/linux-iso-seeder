# 37 — Toolchain hardening: smoke test, shell/Dockerfile linting, ruff S, pinned versions

**Priority**: P2 · **Class**: CI · **Depends on**: —

From `.dev-team-reports/cd-test-architecture-linux-iso-seeder.md` (migration steps 4–6).

## Evidence
- `scripts/smoke_test.sh` asserts the container starts, but not that the daily `fetch_torrents.py` run began. A script that crashes on import would pass.
- No `shellcheck` (`entrypoint.sh`, `scripts/*.sh`) or `hadolint` (`Dockerfile`) in CI. `su-exec` and quoting bugs show up only at runtime.
- ruff enables only 3 `S` (bandit) rules.
- `.github/workflows/docker-image.yml:40` uses `python-version: "3.x"`, and `requirements-test.txt` leaves `requests`/`beautifulsoup4` unpinned. The pip job can change behaviour with no code change; the in-image run on apk versions only partly mitigates this.

## Acceptance criteria
- `smoke_test.sh` waits for `/logs/fetch_torrents.log` to contain `Starting torrent fetch run.` in both the root and `RUN_AS_NON_ROOT` variants. Fetch errors from `--network none` are expected and fine.
- The `test` job runs `shellcheck entrypoint.sh scripts/*.sh` and `hadolint Dockerfile` (pinned versions), with any ignores justified inline.
- ruff's `select` gains the `S` family, with per-rule ignores justified in `pyproject.toml` (e.g. `S101` in tests, the `S310`/`S603` cases that are intended).
- CI Python is pinned to the Alpine minor (e.g. `"3.14"`). `requests` and `beautifulsoup4` are pinned in `requirements-test.txt` to the apk versions, with a comment to bump them alongside `transmission-rpc`.
