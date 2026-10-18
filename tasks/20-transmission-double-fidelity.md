# 20 — Transmission client double that can't drift

**Priority**: P3 · **Class**: REFACTOR_REQUIRED · **Depends on**: 19

## Problem
Every test replaces `transmission_rpc` with a `types.ModuleType` stub whose `Client` is a bare
`MagicMock`. Nothing checks that `Client(host=…, port=…, username=…, password=…)`, `get_torrents()`,
`remove_torrent(id, delete_data=True)` or the torrent attributes the code reads (`name`, `id`,
`ratio`, `added_date`, …) match the real library. The container installs Alpine's
`py3-transmission-rpc`, whose version moves with `alpine:latest` + `apk upgrade`. `log_seed_ratios_via_http`
also builds the raw RPC request by hand.

CLAUDE.md says `transmission_rpc` is "apk-only, not pip-installable", but the cd-test-architecture
review reports that the PyPI package `transmission-rpc` exists. **Check this first.**

## Acceptance criteria
- Verify: find which `transmission-rpc` version current Alpine ships (`apk info py3-transmission-rpc` in the image), and whether that version is on PyPI.
- If it is:
  - pin it in `requirements-test.txt`
  - build the client double with `create_autospec(transmission_rpc.Client, instance=True)`, and torrents from the real `Torrent` shape or a validated fake
  - correct the CLAUDE.md claim
- If it isn't: introduce a thin `TransmissionAdapter` (`list_torrents() -> list[TorrentInfo]`, `remove(id)`) in production code. Then the only untested surface is the adapter itself, which task 23's scheduled job covers.
- Either way, a test fails if production calls a `Client` method or keyword that the pinned library doesn't have.
- Add a test for `log_seed_ratios_via_http` that asserts the request body matches the Transmission RPC spec fields it relies on.
