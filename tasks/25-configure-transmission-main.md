# 25 — `configure_transmission.main` end-to-end test

**Priority**: P3 · **Class**: NO_REFACTOR · **Depends on**: —

## Problem
`configure_transmission.main()` (`configure_transmission.py:131–152`) is the only uncovered part of
the module. It runs at every container start, before the daemon, and connects the env to the builders
and to `load_settings`/`save_settings`. If it breaks, the container fails at startup. Its builders are
well tested (89.8% mutation).

## Acceptance criteria
With `TRANSMISSION_SETTINGS_FILE` pointing at a temp path, under `patch.dict(os.environ, …, clear=True)`:
- No settings file + `TRANSMISSION_RPC_USERNAME`/`PASSWORD` set → a file is created that contains exactly the expected overrides, and `port-forwarding-enabled` is `false` (the first-run default from commit 40f36cd).
- Existing settings file with unrelated keys → those keys are preserved and only the overridden keys change. `port-forwarding-enabled` is **not** forced when the file already exists and `TRANSMISSION_PORT_FORWARDING` is unset.
- `TRANSMISSION_RPC_WHITELIST` set with no username/password → `WARNING: …` goes to stderr. Capture it with `contextlib.redirect_stderr` and assert the message.
- Invalid `TRANSMISSION_PEER_LIMIT_GLOBAL=abc` / `0` → silently dropped (no `peer-limit-global` key), and the file is still written. Pin this current behavior; whether it *should* warn is a separate product decision.
- Unreadable or corrupt existing settings file → "starting fresh" on stderr, and a valid file is written.
- Coverage of `configure_transmission.py` is 100% lines.
