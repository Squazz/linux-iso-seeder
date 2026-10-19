# 36 — Remaining `fetch_torrents.py` mutation survivors

**Priority**: P3 · **Class**: NO_REFACTOR · **Depends on**: —

Full mutmut 2.5.1 run at aa81ef3, with every test module except `test_live_check` as the runner: 1027/1076 (95.4%) honest, critical set 258/258. Of the 49 survivors, the 6 in `wait_for_transmission_rpc` are task 28. The rest are listed below. Mutant ids and line numbers are from that run; rerun `mutmut run` and `mutmut results` to refresh them.

## To kill
- **Fetcher request timeouts never asserted** (`timeout=30` → `31`):
  - `download_torrent` #324
  - `fetch_ubuntu_lts` #336
  - `fetch_debian_stable` #368
  - `fetch_kali_latest` #406
  - `fetch_kali_old_versions` #429
  - `fetch_arch_latest` #458
  - `fetch_devuan_latest` #494
  - `fetch_linuxmint_cinnamon` #511
  - `fetch_fedora_workstation` #530
  - `fetch_fedora_workstation_old_versions` #566

  One table test over the fetchers, with a recording `requests.get` that asserts every call passes `timeout=30`, kills all ten. It also pins that no provider can hang the run.
- **Ordering and selection in scrapers:**
  - `fetch_arch_latest` #476 (`continue` → `break` on a non-available row): needs an unavailable row *before* an available one.
  - `fetch_arch_latest` #484 (`max` by href instead of version): needs a page where href order differs from version order.
  - `fetch_fedora_workstation` #547 (`>` → `>=`): needs the same version listed twice for one arch, with different URLs.
  - `fetch_fedora_workstation_old_versions` #584 (sort by url instead of version): same idea.
  - `fetch_kali_latest` #424 (`return False` → `True` on no versions): assert `assertIs(result, False)`.
  - `fetch_kali_old_versions` #445 (`versions[:-1]` → `[:+1]`): needs 3+ versions on the page.
- **`cleanup_old_versions`:**
  - #814: the default `min_ratio=1.0` is never relied on. Call it without `min_ratio`, with a 1.5-ratio superseded torrent, which is removed under 1.0 and kept under 2.0.
  - #824: `or 0.0` → `or 1.0` on the recorded ratio. Remove a zero-ratio torrent and assert history `ratio == 0.0`.
- **`log_seed_ratios_via_http` #739** (`and` → `or` in the credential fallback): a username without a password must send `auth=None`.
- **`parse_bool` #20** (default `False` → `True`): call it once without `default`.
- **`parse_supported_distros` #163/#164:** assert the "contains unknown distributions: …" warning (`assertLogs`) lists exactly the unknown entries. This also covers task 34's warning item.
- **`record_removal` #658** (`round(…, 3)` → `4`): record a ratio like `0.12345` and assert `0.123`.
- **`RunSummary` #1046/#1047** (default `elapsed`): assert `ft.RunSummary()` equals `RunSummary(elapsed=0.0, added=0, existing=0, not_found=0, failed=0, old_added=None, old_skipped=None)`.
- **`Config` #943** (`frozen=True` → `False`): assert assigning to a `Config` field raises `dataclasses.FrozenInstanceError`, if immutability is meant to be a contract. Otherwise document it as accepted.
- **Module path globals #10/#12/#84** (`ratio_history_file`, `old_release_check_state_file`, `watch_dir` → `None`): every test patches them, so their real values are never checked. Assert the defaults: `os.path.join(log_dir, …)` names and `"/watch"`, or the env-var default once task 35 adds `FETCH_TORRENTS_WATCH_DIR`.

## Decide, then kill or accept
- **`save_old_release_check_state` / `save_ratio_history` / `save_removed_history`** (#635/#636, #881/#882, #652/#653: `indent`, `sort_keys`): the state files are only ever read back by this code. Either pin one golden file text in the `JsonStoreContract` mixin (`tests/test_persistence.py`), or list these as accepted equivalents in the README.
- **`enforce_disk_usage_limit` #858** (in-loop `total == 0` fallback): unreachable unless the disk's total drops to 0 mid-loop. Accept.
- **`enforce_disk_usage_limit` #861** (`break` → `continue` once under the threshold): only adds extra disk checks. Accept, or assert `len(disk.paths)`.

## Accepted equivalents (record in the README)
- **#715, #729:** `.get("seeders", 0)` default. A scrape result always carries `seeders`.
- **#82:** `logger.propagate = None`, which logging treats as `False`.
- **#823, #863, #929:** the `getattr(torrent, "ratio", 0.0)` default. A real `transmission_rpc.Torrent` always has `.ratio`.

## Acceptance criteria
- Every "To kill" item has a test that fails against the mutant (check with `mutmut apply <id>` or a hand edit) and passes on the real code.
- The "decide" items are either killed or added to the accepted list in `tasks/README.md`.
- A full mutmut rerun leaves only the accepted list, plus whatever task 28 hasn't handled yet.
