# 31 — `configure_transmission`: hermetic default path, boundaries, whole-result asserts

**Priority**: P3 · **Class**: NO_REFACTOR (plus one small seam) · **Depends on**: —

## Evidence
- `test_configure_transmission.py` `test_defaults_to_config_settings_path` (about line 355): `main()` calls the real `os.path.exists('/config/settings.json')` (`configure_transmission.py:140`). On a host or container where that file exists, `main()` returns early and the test fails. It also only asserts on patched `load_settings`/`save_settings`.
- Mutation survivor #30: `_parse_positive_int` `parsed > 0` → `> 1` survives, because a limit of exactly 1 is untested.
- `_parse_bool`'s case and whitespace handling (`'TRUE'`, `' false '`) has no test. mutmut never generates "drop `.lower()`/`.strip()`" mutants, so its 100% score for `_parse_bool` doesn't cover this.
- `ApplyOverridesTests` asserts three keys one by one, and doesn't check that the input dict is left unmutated.
- `save_settings` survivors #79/#80 (`indent`, `sort_keys`): decide whether the file layout is a contract.
- `if os.path.exists(...): os.remove(...)` inside the subTest loop of `test_invalid_peer_limits_are_dropped_silently` (about line 318).

## Acceptance criteria
- `main(settings_path=None)` falls back to `TRANSMISSION_SETTINGS_FILE`, then a module constant `DEFAULT_SETTINGS_FILE = "/config/settings.json"`. The default-path test asserts the constant and runs hermetically.
- `TRANSMISSION_PEER_LIMIT_GLOBAL=1` is kept as 1.
- `TRANSMISSION_PORT_FORWARDING='TRUE'` and `' false '` parse.
- `ApplyOverridesTests` uses one `assertEqual(merged, {...})` and asserts the input is unchanged.
- Either pin the settings file text (`indent=4`, sorted keys) in one golden test, or document #79/#80 as accepted equivalents in the README targets section.
- Each subTest case gets its own temp dir, with no `if` in the test body.
