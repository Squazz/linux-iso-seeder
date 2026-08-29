# linux-iso-seeder

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
✅ Automatically cleans up superseded torrents once they go stagnant (no ratio growth in 30 days by default) - still-active old versions keep seeding, only truly dead ones are removed. Space-constrained? `CLEANUP_KEEP_ONLY_LATEST_VERSION=true` keeps just one version per ISO type at all times instead.  
✅ **Smart fetching**: Only downloads new versions of specific ISO types if the previous version of that same ISO type has achieved a seed ratio of at least 1.0, ensuring contribution to torrent health. Can be disabled via environment variable.  
✅ Designed as a **single-container, deploy-and-forget solution**

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
| `/logs` | Persistent logs for fetch script runs, plus `fetch_torrents_ratio_history.json` - a small, bounded per-torrent ratio history used to detect stagnant (no-traction) torrents. Deleting it just resets stagnation tracking; it's not required for anything else. |

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
| `RUN_AS_NON_ROOT` | `false` | Set to `true` to run Transmission and the fetch script as a dedicated non-root `seeder` user instead of root. See [Security considerations](#-security-considerations). |
| `PUID` | `1000` | Only used when `RUN_AS_NON_ROOT=true`. Uid the `seeder` user runs as - set this to match the uid that owns your bind-mounted `/config`, `/downloads`, `/watch`, `/logs` directories on the host. |
| `PGID` | `1000` | Only used when `RUN_AS_NON_ROOT=true`. Gid the `seeder` user runs as - set this to match the gid that owns your bind-mounted directories on the host. |
| `CLEANUP_KEEP_ONLY_LATEST_VERSION` | `false` | Set to `true` if you're space-constrained and only want one version of each ISO type kept at a time: superseded versions are removed as soon as they clear `CLEANUP_MIN_RATIO`, regardless of whether anyone's still downloading them. When `false` (default), superseded versions are instead kept until they go stagnant - see `CLEANUP_STAGNATION_*` below. |
| `CLEANUP_MIN_RATIO` | `1.0` | Only used when `CLEANUP_KEEP_ONLY_LATEST_VERSION=true`. Minimum seed ratio a superseded version must reach before it's removed. |
| `CLEANUP_SKIP_RATIO_CHECK` | `false` | Only used when `CLEANUP_KEEP_ONLY_LATEST_VERSION=true`. Set to `true` to remove superseded versions immediately, ignoring `CLEANUP_MIN_RATIO`. |
| `CLEANUP_STAGNATION_WINDOW_DAYS` | `30` | Default cleanup path (`CLEANUP_KEEP_ONLY_LATEST_VERSION=false`). A superseded version is only eligible for removal once we've tracked its ratio for at least this many days - it needs enough history before we judge it as dead. |
| `CLEANUP_STAGNATION_MIN_RATIO_DELTA` | `0.02` | Default cleanup path. A superseded version is removed once its ratio has grown by less than this over `CLEANUP_STAGNATION_WINDOW_DAYS` - i.e. nobody's downloading it anymore. Versions still gaining ratio are left seeding no matter how old they are. The current/latest version of each ISO type is never removed this way, regardless of its ratio - see `fetch_torrents_ratio_history.json` below. |
| `TRANSMISSION_RPC_WHITELIST` | *(unset)* | Comma-separated IPs/wildcards (e.g. `10.0.0.*`, or `*` for any) to allow into Transmission's RPC/web UI, beyond its own `127.0.0.1`-only default. Needed if you're getting a `403: Forbidden` accessing the web UI from another host - see [Security considerations](#-security-considerations) before opening this up. |
| `TRANSMISSION_RPC_USERNAME` / `TRANSMISSION_RPC_PASSWORD` | *(unset)* | Set **both** to require a login for the RPC/web UI. Opt-in and off by default, matching Transmission's own default - required if you set `TRANSMISSION_RPC_WHITELIST` to anything beyond localhost, since Transmission has no read-only RPC mode. |

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
docker build -t linux-iso-seeder .

# With ratio checking enabled (default)
docker run -d \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  -p 51413:51413 -p 51413:51413/udp \
  linux-iso-seeder

# To disable ratio checking and download all torrents
docker run -d \
  -e SKIP_RATIO_CHECK=true \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  linux-iso-seeder

# Opt in to also seeding low-demand image families (cloud images, Kali netinst)
docker run -d \
  -e FETCH_TORRENTS_INCLUDE_LOW_DEMAND=true \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  linux-iso-seeder

# Opt in to running as a non-root user (see Security considerations)
docker run -d \
  -e RUN_AS_NON_ROOT=true \
  -e PUID=1000 -e PGID=1000 \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  linux-iso-seeder

# Open the web UI to your LAN, with a login required (see Security considerations)
docker run -d \
  -e TRANSMISSION_RPC_WHITELIST=10.0.0.* \
  -e TRANSMISSION_RPC_USERNAME=admin \
  -e TRANSMISSION_RPC_PASSWORD=changeme \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -p 9091:9091 \
  linux-iso-seeder
```

---

## 🔒 **Security considerations**

- Always review container scripts before deployment.  
- This project installs the latest packages on container start for updated clients and security patches.
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
