# linux-iso-seeder

[![Docker Image CI](https://github.com/Squazz/linux-iso-seeder/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Squazz/linux-iso-seeder/actions/workflows/docker-image.yml)
[![Latest Release](https://img.shields.io/github/v/release/Squazz/linux-iso-seeder)](https://github.com/Squazz/linux-iso-seeder/releases)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Container Image](https://img.shields.io/badge/ghcr.io-linux--iso--seeder-blue?logo=docker)](https://github.com/Squazz/linux-iso-seeder/pkgs/container/linux-iso-seeder)

> **Automated Linux ISO torrent seeder in a single container.**
>
> Helps the open-source community by seeding official ISOs for multiple Linux distributions, with **no manual intervention after deployment**.

---

## ❤️ **Why?**

Seeding Linux ISOs improves global availability, helps users download faster, and strengthens the open-source ecosystem. This project makes it **easy to contribute without daily maintenance**.

---

## 🚀 **Features**

✅ Automatically fetches the latest torrent files for:

- Ubuntu (All LTS & ESM, including Lubuntu & Xubuntu)
- Debian (latest stable, DVD and netinst/CD images, amd64 + arm64)
- Kali Linux (latest installer, netInstaller & everything ISO)
- Arch Linux (All available ISOs)
- Linux Mint (latest Cinnamon edition, 64-bit)
- Fedora Workstation (latest Live ISO, x86_64 + aarch64)

✅ Daily updates with minimal resource usage  
✅ Uses **Transmission-daemon** (lightweight torrent client)  
✅ **Logs and metrics** for transparency and future monitoring  
✅ Automatically cleans up superseded torrents once they go stagnant (no ratio growth in 30 days by default) - still-active old versions keep seeding, only truly dead ones are removed. Space-constrained? `CLEANUP_KEEP_ONLY_LATEST_VERSION=true` keeps just one version per ISO type at all times instead. A disk-usage safety valve (`CLEANUP_DISK_USAGE_THRESHOLD_PERCENT`, default `95`) removes lowest-ratio superseded versions anyway if `/downloads` is nearly full, regardless of ratio or stagnation status.  
✅ **Smart fetching**: Only downloads new versions of specific ISO types if the previous version of that same ISO type has achieved a seed ratio of at least 1.0, ensuring contribution to torrent health. Can be disabled via environment variable.  
✅ Designed as a **single-container, deploy-and-forget solution**  
✅ **No telemetry or phone-home of any kind** - the container only ever talks to the official distro download/tracker sites it fetches from and the BitTorrent peers/trackers it seeds to

---

## 🔍 **How it works**

1. **On container startup:**
   - Updates packages and Transmission to the latest version.
   - Starts `fetch_torrents.py` in the background.

2. **Daily:**
   - Fetches torrent files for configured distros.
   - Downloads them to `/watch` for Transmission to seed.
   - Logs results and disk usage to `/logs/fetch_torrents.log`.

3. **Transmission-daemon runs continuously**, seeding all loaded torrents.

---

## 📦 **Volumes**

| Container Path | Purpose |
|---|---|
| `/config` | Transmission configuration files |
| `/downloads` | Downloaded ISO files (seeding storage) |
| `/watch` | Torrent watch folder |
| `/logs` | Persistent logs for fetch script runs, plus `fetch_torrents_ratio_history.json` - a small, bounded per-torrent ratio history used to detect stagnant (no-traction) torrents. Deleting it just resets stagnation tracking; it's not required for anything else. `fetch_torrents.log` itself is size-bounded (rotated, see `FETCH_TORRENTS_LOG_MAX_BYTES`/`FETCH_TORRENTS_LOG_BACKUP_COUNT`), so this volume won't grow without limit even if left running indefinitely. |

---

## 💾 **Resource expectations**

- **CPU/RAM:** minimal - the fetch script runs once a day for a few seconds; Transmission itself is lightweight and idles between transfers.
- **Disk:** the main variable cost. `/downloads` holds every seeded ISO and grows as new distro releases come out; budget at least a few tens of GB and expect steady, open-ended growth over months of uptime unless you set `CLEANUP_KEEP_ONLY_LATEST_VERSION=true`. The `CLEANUP_DISK_USAGE_THRESHOLD_PERCENT` safety valve (default `95`) exists specifically so a deployment nobody comes back to doesn't fill its disk outright, but it's a last resort, not a substitute for provisioning enough space up front.
- **Network:** no way to bound this - it's a seedbox, and by design it uploads to other peers as well as downloading new releases. Set `TRANSMISSION_RPC_WHITELIST`/the web UI's own speed limits if you need to cap bandwidth.

---

## 🔄 **Updates**

This image auto-updates its OS packages (Alpine, Transmission, Python, etc.)
on every container start/restart via `apk upgrade` - see
[Security considerations](#-security-considerations). That does **not**
cover this project's own logic (`fetch_torrents.py`,
`configure_transmission.py`, the scraping/cleanup behavior) - that code is
baked into the image at build time and only changes when you pull a newer
image tag and recreate the container. All examples below use
`ghcr.io/squazz/linux-iso-seeder:latest`; pin to a specific released version
instead (see the repo's tags/releases) if you want reproducible behavior
between deployments, and re-pull `:latest` periodically if you want fetch
logic fixes and improvements as they're released. Restarting an existing
container does not by itself pull a new image - `docker pull` the image,
then `docker stop`/`docker rm` and re-run your `docker run` command (or
recreate it, if you're managing it some other way) to actually update it.

**If an update ever breaks a working deployment:** `apk upgrade` runs on
every start/restart of an *existing* container too, not just when you
recreate one from a new image - Docker's container filesystem persists
across restarts, so packages can keep drifting forward on their own even if
you never touch the image tag. To get back to a known-good state: recreate
the container from a pinned, previously-working image tag (see above), then
set `SKIP_PACKAGE_UPDATES=true` so it stays frozen there instead of
upgrading itself into the same broken state again on the next restart. Unset
it once you're ready to resume auto-patching.

---

## 🛑 **Stopping / uninstalling**

`docker stop <container>` stops seeding; `docker rm <container>` removes the
container itself. Both are safe at any time - Transmission checkpoints its
state to `/config` as it runs, so nothing is lost by stopping abruptly.
Neither touches your bind-mounted `/config`, `/downloads`, `/watch`, `/logs`
directories; delete those yourself (they hold the ISOs and configuration) if
you want a clean removal. If you forwarded port `51413` on your router (see
below), remember to remove that forwarding rule too.

---

## 🌍 **Environment Variables**

| Variable | Default | Description |
|---|---|---|
| `SKIP_RATIO_CHECK` | `false` | Set to `true` to disable the smart ratio checking and download all available torrents regardless of previous seeding performance. |
| `LOG_LEVEL` | `INFO` | Set the minimum log level for the fetch script. Supported values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `FETCH_TORRENTS_LOG_LEVEL` | `INFO` | Overrides `LOG_LEVEL` when both are set. |
| `FETCH_TORRENTS_ALWAYS_LOG` | `true` | If `true`, always logs a small set of important run-status messages even when the effective level is `ERROR`. Set to `false` to only log messages at or above the configured level. |
| `FETCH_TORRENTS_DISTROS` | `ubuntu,debian,kali,arch,mint,fedora` | Comma-separated list of distributions to fetch. Valid values: `ubuntu`, `debian`, `kali`, `arch`, `mint`, `fedora`. |
| `FETCH_TORRENTS_INCLUDE_LOW_DEMAND` | `false` | By default, `cloud-genericcloud` images and Kali's `netinst` installer are skipped — these image families see very few peers over BitTorrent and chronically end up with a seed ratio well below 1.0 regardless of architecture or how recent the release is (see `fetch_torrents_ratios.log`), leaving this seeder as a leecher. Set to `true` to fetch and seed these low-demand variants too. |
| `FETCH_TORRENTS_CHECK_OLD_RELEASES` | `false` | Set to `true` to also look for unmet demand on older, non-latest releases (currently: Kali's previous release still on `cdimage.kali.org`, and non-latest Fedora Workstation images — Ubuntu and Arch already surface old releases through their normal fetch, since their upstream feeds list more than just the newest one). Each candidate's `.torrent` is downloaded and its tracker(s) queried via BitTorrent's "scrape" convention for live seeder/leecher counts *without joining the swarm* — it's only added to seed if that shows real, currently-unmet demand (see `FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHERS`/`FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHER_RATIO`). |
| `FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHERS` | `10` | Only used when `FETCH_TORRENTS_CHECK_OLD_RELEASES=true`. Minimum leecher count, in absolute terms, a live tracker scrape must show before an old release is even considered — a single leecher shouldn't justify a download on its own. |
| `FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHER_RATIO` | `0.1` | Only used when `FETCH_TORRENTS_CHECK_OLD_RELEASES=true`. Leechers must reach at least this fraction of the seeder count (e.g. `0.1` = leechers only need to reach 10% of seeders — 10 leechers on 100 seeders, or 100 on 1000, both count) before an old release counts as unmet demand. Deliberately low: scrape data can't tell us whether existing seeders have spare upload capacity or are bandwidth-constrained, so leechers don't need to approach or outnumber seeders — this mainly guards against the extreme case of a handful of leechers on a vastly larger, clearly-already-served swarm. Doesn't apply to a swarm with zero seeders — see `FETCH_TORRENTS_OLD_RELEASE_ALLOW_ZERO_SEEDERS`. |
| `FETCH_TORRENTS_OLD_RELEASE_ALLOW_ZERO_SEEDERS` | `false` | Only used when `FETCH_TORRENTS_CHECK_OLD_RELEASES=true`. A scrape showing zero seeders means there's no verified-complete copy anywhere in the swarm — the leechers present may not collectively hold every piece, so the download could stall short of 100% forever, leaving us leeching something we can never actually seed back. Excluded by default for that reason, regardless of leecher count. Set to `true` to gamble on reviving such swarms anyway (the absolute leecher floor above still applies) — for the official, well-seeded Linux ISO trackers this project currently targets this is mostly theoretical, but may matter more if this project expands to less centrally-seeded content in the future. |
| `FETCH_TORRENTS_OLD_RELEASE_RECHECK_DAYS` | `7` | Only used when `FETCH_TORRENTS_CHECK_OLD_RELEASES=true`. A candidate that scraped to no demand is remembered (`fetch_torrents_old_release_check_state.json`) and skipped without any network call until this many days have passed, instead of being re-downloaded and re-scraped on every daily run. |
| `FETCH_TORRENTS_OLD_RELEASE_SKIP_REMOVED` | `true` | Only used when `FETCH_TORRENTS_CHECK_OLD_RELEASES=true`. Once cleanup removes a torrent for going stagnant (see `CLEANUP_STAGNATION_*`), it's remembered (`fetch_torrents_removed_history.json`) and never automatically re-added by the old-release check — a torrent that took weeks of flat ratio to justify removing shouldn't come back from one day's momentary leecher blip, since the ratio might not be recouped before it goes stagnant again. Set to `false` to allow re-adding previously-removed old releases. |
| `SKIP_PACKAGE_UPDATES` | `false` | Set to `true` to skip the `apk update && apk upgrade` that otherwise runs on every container start/restart - see [Updates](#-updates). Useful as an "out" if an upstream package update ever breaks a working deployment: recreate the container from a known-good pinned image tag, then set this so it stays frozen there instead of drifting forward again on the next restart. |
| `RUN_AS_NON_ROOT` | `false` | Set to `true` to run Transmission and the fetch script as a dedicated non-root `seeder` user instead of root. See [Security considerations](#-security-considerations). |
| `PUID` | `1000` | Only used when `RUN_AS_NON_ROOT=true`. Uid the `seeder` user runs as - set this to match the uid that owns your bind-mounted `/config`, `/downloads`, `/watch`, `/logs` directories on the host. |
| `PGID` | `1000` | Only used when `RUN_AS_NON_ROOT=true`. Gid the `seeder` user runs as - set this to match the gid that owns your bind-mounted directories on the host. |
| `CLEANUP_KEEP_ONLY_LATEST_VERSION` | `false` | Set to `true` if you're space-constrained and only want one version of each ISO type kept at a time: superseded versions are removed as soon as they clear `CLEANUP_MIN_RATIO`, regardless of whether anyone's still downloading them. When `false` (default), superseded versions are instead kept until they go stagnant - see `CLEANUP_STAGNATION_*` below. |
| `CLEANUP_MIN_RATIO` | `1.0` | Only used when `CLEANUP_KEEP_ONLY_LATEST_VERSION=true`. Minimum seed ratio a superseded version must reach before it's removed. |
| `CLEANUP_SKIP_RATIO_CHECK` | `false` | Only used when `CLEANUP_KEEP_ONLY_LATEST_VERSION=true`. Set to `true` to remove superseded versions immediately, ignoring `CLEANUP_MIN_RATIO`. |
| `CLEANUP_STAGNATION_WINDOW_DAYS` | `30` | Default cleanup path (`CLEANUP_KEEP_ONLY_LATEST_VERSION=false`). A superseded version is only eligible for removal once we've tracked its ratio for at least this many days - it needs enough history before we judge it as dead. |
| `CLEANUP_STAGNATION_MIN_RATIO_DELTA` | `0.02` | Default cleanup path. A superseded version is removed once its ratio has grown by less than this over `CLEANUP_STAGNATION_WINDOW_DAYS` - i.e. nobody's downloading it anymore. Versions still gaining ratio are left seeding no matter how old they are. The current/latest version of each ISO type is never removed this way, regardless of its ratio - see `fetch_torrents_ratio_history.json` below. |
| `CLEANUP_DISK_USAGE_THRESHOLD_PERCENT` | `95` | Safety valve on top of the two cleanup paths above: if `/downloads` usage is still at or above this percentage after normal cleanup runs, superseded versions are removed anyway - lowest seed ratio first - regardless of ratio floor or stagnation status, until usage drops back below the threshold or none are left. This is what protects a deployment nobody comes back to from silently filling its disk. Set to `0` to disable entirely. |
| `TRANSMISSION_RPC_WHITELIST` | *(unset)* | Comma-separated IPs/wildcards (e.g. `10.0.0.*`, or `*` for any) to allow into Transmission's RPC/web UI, beyond its own `127.0.0.1`-only default. Needed if you're getting a `403: Forbidden` accessing the web UI from another host - see [Security considerations](#-security-considerations) before opening this up. |
| `TRANSMISSION_RPC_USERNAME` / `TRANSMISSION_RPC_PASSWORD` | *(unset)* | Set **both** to require a login for the RPC/web UI. Opt-in and off by default, matching Transmission's own default - required if you set `TRANSMISSION_RPC_WHITELIST` to anything beyond localhost, since Transmission has no read-only RPC mode. Also used to authenticate the fetch script's own RPC connection (cleanup, ratio logging), so it keeps working once this is set. |
| `FETCH_TORRENTS_LOG_MAX_BYTES` | `5242880` (5 MB) | Maximum size of `fetch_torrents.log` before it's rotated. |
| `FETCH_TORRENTS_LOG_BACKUP_COUNT` | `3` | Number of rotated `fetch_torrents.log.N` backups kept before the oldest is deleted. |

---

## 🌐 **Peer port forwarding (optional)**

Transmission accepts incoming connections from other peers on `51413`
(`tcp` and `udp`), separate from the `9091` web UI port used in the examples
below. The image exposes it, but none of the example commands publish it
with `-p` - add that yourself if you want it (see the first example below).

- **What it does:** lets peers that don't already have an open port of their
  own connect *to you*. Without it, Transmission still works - it downloads
  and seeds fine to peers who do have an open port, and finds them via
  trackers/DHT/PEX - but a large share of BitTorrent peers are behind NAT
  with a closed port too, and two closed-port peers generally can't connect
  to each other. So forwarding this port measurably increases how much of
  the swarm you can seed to.
- **It's optional.** If you don't want to touch your router, leave it as-is
  - the container still seeds, just somewhat less effectively.
- **The tradeoff:** forwarding it exposes this port from your router
  straight to the container, reachable from the internet. The BitTorrent
  peer-wire protocol isn't a management/admin interface (no auth, no shell),
  and the container already updates Transmission on every start, but it's
  still more surface than a fully closed port. If that matters to you,
  combine it with `RUN_AS_NON_ROOT=true` (see
  [Security considerations](#-security-considerations)) for defense in
  depth.
- **How:** forward `51413` `tcp`+`udp` on your router to the host running
  this container, and publish the same port when starting the container
  (`-p 51413:51413 -p 51413:51413/udp`, as in the first example below).
  Leave Transmission's "randomize port on launch" option off (its default)
  so the forwarded port keeps matching what Transmission actually listens
  on.

---

```bash
# Pull the published, auto-built image (recommended) ...
docker pull ghcr.io/squazz/linux-iso-seeder:latest
# ... or build from source instead:
#   docker build -t linux-iso-seeder .
# (substitute your own tag for ghcr.io/squazz/linux-iso-seeder below if you do)
#
# :latest tracks the main branch. For reproducible behavior between
# deployments, pin to a specific released version instead, e.g.
# ghcr.io/squazz/linux-iso-seeder:1.9.1 - see
# https://github.com/squazz/linux-iso-seeder/tags for available versions.

# With ratio checking enabled (default)
docker run -d \
  --restart=unless-stopped \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  -p 51413:51413 -p 51413:51413/udp \
  ghcr.io/squazz/linux-iso-seeder:latest

# To disable ratio checking and download all torrents
docker run -d \
  --restart=unless-stopped \
  -e SKIP_RATIO_CHECK=true \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  ghcr.io/squazz/linux-iso-seeder:latest

# Opt in to also seeding low-demand image families (cloud images, Kali netinst)
docker run -d \
  --restart=unless-stopped \
  -e FETCH_TORRENTS_INCLUDE_LOW_DEMAND=true \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  ghcr.io/squazz/linux-iso-seeder:latest

# Opt in to running as a non-root user (see Security considerations)
docker run -d \
  --restart=unless-stopped \
  -e RUN_AS_NON_ROOT=true \
  -e PUID=1000 -e PGID=1000 \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  ghcr.io/squazz/linux-iso-seeder:latest

# Open the web UI to your LAN, with a login required (see Security considerations)
docker run -d \
  --restart=unless-stopped \
  -e TRANSMISSION_RPC_WHITELIST=10.0.0.* \
  -e TRANSMISSION_RPC_USERNAME=admin \
  -e TRANSMISSION_RPC_PASSWORD=changeme \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  ghcr.io/squazz/linux-iso-seeder:latest
```

`--restart=unless-stopped` is included in every example above so the
container (and seeding) comes back automatically after a host reboot or an
unexpected crash - this is a "deploy and forget" tool, so nothing restarts
it for you otherwise. Omit it, or use a different policy, if you're managing
restarts some other way (e.g. an external orchestrator).

---

## 🔒 **Security considerations**

- Always review container scripts before deployment.  
- This project installs the latest packages on container start for updated clients and security patches. This is a deliberate tradeoff: it keeps every deployment auto-patched against CVEs without anyone needing to re-pull the image, but it also means a breaking change in an upstream Alpine/Transmission package could affect every running deployment simultaneously on its next restart, with no version pin to roll back to. Set `SKIP_PACKAGE_UPDATES=true` if you'd rather have fully unchanging package versions (see [Updates](#-updates) for how to combine this with a pinned image tag), or build your own image from a pinned `FROM alpine:<version>` for a fully reproducible build.
- By default, transmission-daemon and the fetch script run as root, as in
  every previous release, so nothing changes for existing deployments -
  including ones sharing `/config`, `/downloads`, `/watch`, `/logs` with
  other containers or host processes that expect root/a specific uid.
  Set `RUN_AS_NON_ROOT=true` (with `PUID`/`PGID` if needed) to instead run
  those processes as a dedicated non-root `seeder` user, for defense in
  depth against bugs in code that handles untrusted input (scraped HTML,
  downloaded `.torrent` files, Transmission's RPC/peer-wire parsing).
  Enabling it recursively `chown`s the working directories to that user on
  every start, so only turn it on for volumes you're sure aren't relied on
  by anything else expecting a different owner.
- By default, Transmission's RPC/web UI only accepts connections from
  `127.0.0.1` (its own built-in default) - a fresh deploy stays private even
  though port 9091 is exposed. Setting `TRANSMISSION_RPC_WHITELIST` opens it
  up to whatever you allow, but Transmission has no read-only RPC mode:
  anyone who can reach it can add, remove, and delete data, not just view
  state. Always set `TRANSMISSION_RPC_USERNAME`/`TRANSMISSION_RPC_PASSWORD`
  alongside it unless the whitelist is already tightly scoped to hosts you
  trust - the container logs a warning on startup if you don't.

---

## 💡 **Contributing**

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow, ideas
for contribution, and guidance on modifying the fetch logic.
