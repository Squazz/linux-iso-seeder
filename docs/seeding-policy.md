# Seeding policy

When the daily run fetches, keeps, removes or re-seeds an ISO, with the
defaults from the [README](../README.md#-environment-variables). Each rule
names the test that pins it, so the policy can be reviewed without reading
the code. Tests are `tests/<file>.py`, `Class.test_name`.

An *ISO type* is one distro image family on one architecture, e.g. Debian
`netinst` on `amd64`. A *superseded* version is any version of an ISO type
that is not the newest one being seeded.

## Fetching new releases

| Rule | Pinned by |
| --- | --- |
| Only the distros in `FETCH_TORRENTS_DISTROS` are fetched (Arch and Devuan only when listed). | `test_daily_run`: `RunTests.test_distros_not_selected_are_never_fetched` |
| A new version is fetched only if the previous version of the same ISO type reached a seed ratio of at least 1.0. | `test_daily_run`: `RunTests.test_low_previous_ratio_blocks_the_new_release`, `RunTests.test_previous_ratio_at_the_floor_allows_the_new_release` |
| Exactly 1.0 is enough; 0.999 is not. | `test_ratio_gate`: `ShouldFetchTorrentBoundaryTests.test_previous_ratio_exactly_at_floor_allows_fetch`, `ShouldFetchTorrentBoundaryTests.test_previous_ratio_just_below_floor_blocks_fetch` |
| Each architecture and each Ubuntu flavour is gated on its own previous version, never another one's. | `test_ratio_gate`: `ShouldFetchTorrentBoundaryTests.test_other_architecture_ratio_is_not_consulted`, `ShouldFetchTorrentRatioKeyTests.test_lubuntu_is_ratio_gated_on_its_own_previous_release` |
| If the previous version was already removed, its ratio at removal time is used instead; a live ratio always wins. | `test_ratio_gate`: `ShouldFetchTorrentRemovedHistoryFallbackTests.test_falls_back_to_removed_history_ratio_when_not_live`, `ShouldFetchTorrentRemovedHistoryFallbackTests.test_live_ratio_takes_priority_over_removed_history` |
| With no previous version on record, the release is fetched. | `test_ratio_gate`: `ShouldFetchTorrentBoundaryTests.test_only_newer_versions_on_record_fetches`, `ShouldFetchTorrentDevuanRatioGateTests.test_no_previous_devuan_release_fetches` |
| `SKIP_RATIO_CHECK=true` fetches every release regardless of ratio. | `test_daily_run`: `RunTests.test_skip_ratio_check_fetches_despite_a_low_previous_ratio` |
| Low-demand images (cloud images, Kali netinst) are skipped unless `FETCH_TORRENTS_INCLUDE_LOW_DEMAND=true`. | `test_daily_run`: `RunTests.test_low_demand_images_are_skipped_by_default`, `RunTests.test_include_low_demand_fetches_low_demand_images` |
| One distro's site failing doesn't stop the others being fetched. | `test_daily_run`: `RunTests.test_a_failing_distro_does_not_stop_the_others` |

## Keeping and removing superseded versions

| Rule | Pinned by |
| --- | --- |
| By default a superseded version is removed only once it stagnates: its ratio grew by less than 0.02 over the last 30 days. | `test_daily_run`: `RunTests.test_default_cleanup_is_stagnation_based`; `test_cleanup`: `PlanStagnationCleanupTests.test_defaults_are_a_30_day_window_and_0_02_delta` |
| Growth of exactly 0.02 keeps it; anything less removes it. | `test_cleanup`: `PlanStagnationCleanupTests.test_delta_exactly_at_min_ratio_delta_is_kept`, `PlanStagnationCleanupTests.test_delta_just_below_min_ratio_delta_is_removed` |
| A version tracked for less than the full 30 days is too new to judge and is kept. | `test_cleanup`: `PlanStagnationCleanupTests.test_anchor_one_day_short_of_window_is_too_new_to_judge` |
| The newest version of an ISO type is never removed, however flat its ratio. | `test_cleanup`: `PlanStagnationCleanupTests.test_latest_or_only_version_is_never_removed_even_if_flat` |
| With `CLEANUP_KEEP_ONLY_LATEST_VERSION=true`, a superseded version is removed as soon as its ratio reaches `CLEANUP_MIN_RATIO` (default 1.0, inclusive). | `test_daily_run`: `RunTests.test_keep_only_latest_selects_the_old_version_cleanup`; `test_cleanup`: `PlanCleanupTests.test_ratio_exactly_at_min_ratio_is_removed`, `PlanCleanupTests.test_ratio_just_below_min_ratio_is_kept` |
| ...or straight away with `CLEANUP_SKIP_RATIO_CHECK=true`. | `test_cleanup`: `PlanCleanupTests.test_skip_ratio_check_removes_regardless_of_ratio` |
| A removal deletes the downloaded data and the `.torrent` in `/watch`. | `test_cleanup`: `CleanupRemovesWatchFileTests.test_cleanup_stagnant_torrents_deletes_the_downloaded_data`, `CleanupRemovesWatchFileTests.test_cleanup_stagnant_torrents_removes_the_watch_file` |
| A cleanup setting that doesn't parse skips cleanup for that run; nothing is removed. | `test_daily_run`: `RunTests.test_invalid_cleanup_setting_skips_cleanup_and_continues` |

## Disk-pressure safety valve

| Rule | Pinned by |
| --- | --- |
| If `/downloads` is at or above 95% full after cleanup, superseded versions are removed lowest ratio first until usage is below 95%. | `test_cleanup`: `EnforceDiskUsageLimitTests.test_usage_exactly_at_threshold_triggers_cleanup`, `EnforceDiskUsageLimitTests.test_stops_once_usage_is_just_below_threshold`, `PlanDiskPressureCleanupTests.test_at_or_above_threshold_returns_candidates_lowest_ratio_first` |
| The newest version of an ISO type is never removed for disk space. | `test_cleanup`: `EnforceDiskUsageLimitTests.test_never_removes_the_latest_version` |
| `CLEANUP_DISK_USAGE_THRESHOLD_PERCENT=0` turns the valve off. | `test_cleanup`: `EnforceDiskUsageLimitTests.test_disabled_threshold_never_touches_disk_or_rpc` |

## Re-seeding old releases (opt-in)

| Rule | Pinned by |
| --- | --- |
| Old releases are only checked with `FETCH_TORRENTS_CHECK_OLD_RELEASES=true`; it is off by default. | `test_daily_run`: `RunTests.test_old_release_check_is_off_by_default` |
| An old release is added only if a tracker scrape shows at least 10 leechers and at least 0.1 leechers per seeder. | `test_old_release_demand`: `HasUnmetDemandTests.test_below_absolute_threshold_is_no_demand`, `HasUnmetDemandTests.test_meets_absolute_but_not_ratio_is_no_demand`, `HasUnmetDemandTests.test_exactly_at_ratio_threshold_is_demand` |
| A swarm with no seeders is not joined unless `FETCH_TORRENTS_OLD_RELEASE_ALLOW_ZERO_SEEDERS=true`. | `test_old_release_demand`: `HasUnmetDemandTests.test_zero_seeders_is_excluded_by_default`, `HasUnmetDemandTests.test_zero_seeders_counts_as_demand_when_explicitly_allowed` |
| A failed scrape counts as no demand. | `test_old_release_demand`: `EvaluateOldReleaseDemandBoundaryTests.test_scrape_error_counts_as_unknown_demand_and_cleans_up` |
| A release with no demand is not checked again for 7 days. | `test_old_release_demand`: `ShouldRecheckOldReleaseTests.test_checked_recently_is_not_due`, `ShouldRecheckOldReleaseTests.test_checked_exactly_at_interval_is_due` |
| A release that cleanup removed as stagnant is never re-added, unless `FETCH_TORRENTS_OLD_RELEASE_SKIP_REMOVED=false`. | `test_daily_run`: `OldReleaseRunTests.test_previously_removed_release_is_skipped_by_default`, `OldReleaseRunTests.test_previously_removed_release_is_rechecked_when_skip_removed_is_off` |
| Low-demand image families are skipped here too. | `test_daily_run`: `OldReleaseRunTests.test_low_demand_old_releases_are_skipped_by_default` |
