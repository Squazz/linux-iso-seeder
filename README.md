# linux-iso-seeder

> **Automated Linux ISO torrent seeder in a single container.**
>
> Helps the open-source community by seeding official ISOs for multiple Linux distributions, with **no manual intervention after deployment**.

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
✅ Automatically cleans up old torrents and their data  
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
| `/logs` | Persistent logs for fetch script runs |

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

---

## ❤️ **Why?**

Seeding Linux ISOs improves global availability, helps users download faster, and strengthens the open-source ecosystem. This project makes it **easy to contribute without daily maintenance**.

---

## 💡 **Contributing**

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow, ideas
for contribution, and guidance on modifying the fetch logic.
