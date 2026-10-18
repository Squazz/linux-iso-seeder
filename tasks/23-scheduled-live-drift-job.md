# 23 — Scheduled live-drift job

**Priority**: P3 · **Class**: CI · **Depends on**: 21, 22

## Problem
Tests in the merge check are deterministic by design, but the outside world they depend on keeps moving:
- distro sites change layout
- trackers change behavior
- `alpine:latest` + `apk upgrade` at container start change the runtime **after** deploy

Today nothing checks the published image or the live sites until a user notices missing torrents.

## Acceptance criteria
New workflow `.github/workflows/drift.yml`, run on `schedule` (weekly) + `workflow_dispatch`, and **not** part of the PR check:
- **Live scrapers:** run each fetcher against the real site and assert it returns ≥ 1 well-formed candidate (name matches the distro pattern, URL ends in `.torrent`, HEAD returns 200). On failure, re-record fixtures with task 21's script and upload them as an artifact for comparison.
- **Live tracker scrape:** run `scrape_torrent` on one current Ubuntu torrent and assert it returns integer seeders/leechers.
- **Real Transmission:** start the published `ghcr.io/squazz/linux-iso-seeder:latest` (with network), wait for RPC, and run a short script that uses `transmission_rpc.Client` to add a known small torrent from `/watch`, list it, and remove it.
- **Published image smoke:** task 22's checks against `:latest`, without `SKIP_PACKAGE_UPDATES`.
- Optional: a mutation run (`mutmut run` per task 16) that uploads its results, for trend tracking.
- A failure opens or updates a single GitHub issue labelled `drift` (via `actions/github-script`) and doesn't block anything.
