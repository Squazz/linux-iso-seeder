# 22 — Container smoke test in the build job

**Priority**: P2 · **Class**: CI · **Depends on**: —

## Problem
The image is built and pushed without ever being started:
- `entrypoint.sh` (apk upgrade, the `RUN_AS_NON_ROOT` user/chown dance, `configure_transmission.py`, the daemon start, the daily loop) has no test.
- `Dockerfile` installs Python deps from apk, while CI's `test` job uses pip versions on Ubuntu. Version skew between the two is never exercised.

## Acceptance criteria
In `.github/workflows/docker-image.yml` `build` job, after building and **before** push, a step that:
- Runs the built image with `--network none -e SKIP_PACKAGE_UPDATES=true` and temp volumes, waits for "Starting linux-iso-seeder container", and checks that `transmission-daemon` is running and `configure_transmission.py` exited 0.
- Does the same with `RUN_AS_NON_ROOT=true PUID=1234 PGID=1234`, and checks that `/config` is owned by 1234.
- Runs `docker run --rm --entrypoint python3 <image> -c "import fetch_torrents, torrent_scrape, transmission_rpc, requests, bs4"` with `FETCH_TORRENTS_LOG_DIR=/tmp`, which catches apk/pip import skew.
- Optional: runs the unit suite inside the image (`python3 -m unittest discover -s tests`) to test against the real apk package versions. This requires copying `tests/` into a test stage, not the final image.
- Fails the job (no push) on any of these failing. Stays under about 60 s.

## Notes
`--network none` keeps the check deterministic. The daily fetch loop will log network errors, which
is expected; the smoke test only asserts startup.
