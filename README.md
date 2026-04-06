# linux-iso-seeder

> **Automated Linux ISO torrent seeder in a single container.**
>
> Helps the open-source community by seeding official ISOs for multiple Linux distributions, with **no manual intervention after deployment**.

---

## 🚀 **Features**

✅ Automatically fetches the latest torrent files for:

- Ubuntu (All LTS & ESM, including Lubuntu & Xubuntu)
- Debian (latest stable DVD-1)
- Kali Linux (latest installer, netInstaller & everything ISO)
- Arch Linux (All available ISOs)

✅ Daily updates with minimal resource usage  
✅ Uses **Transmission-daemon** (lightweight torrent client)  
✅ **Logs and metrics** for transparency and future monitoring  
✅ Automatically cleans up old torrents and their data  
✅ **Smart fetching**: Only downloads new versions of specific ISO types if the previous version of that same ISO type has achieved a seed ratio of at least 1.0, ensuring contribution to torrent health. Can be disabled via environment variable.  
✅ Designed as a **single-container, deploy-and-forget solution**

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
```

---

## 🛠️ **Maintenance Notes**

When making changes to the fetch logic or features:
- Update this README.md to reflect new functionality
- Test the script in a controlled environment before deployment
- Ensure log parsing works correctly for ratio checks
- Verify regex patterns match all intended torrent names (e.g., Ubuntu variants)
- Ratio checking is now per ISO type (e.g., installer-amd64) rather than per distro

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

## 💡 **Contributing**

1. Fork the repository  
2. Create a new branch (`feature/your-feature`)  
3. Commit your changes with clear messages  
4. Push to your fork and submit a pull request

**Ideas for contribution:**

- Adding more distros or mirrors  
- Implementing Prometheus metrics endpoint  
- Slack or Matrix notification integration  
- Disk cleanup or retention policies

---

## 🔒 **Security considerations**

- Always review container scripts before deployment.  
- This project installs the latest packages on container start for updated clients and security patches.

---

## ❤️ **Why?**

Seeding Linux ISOs improves global availability, helps users download faster, and strengthens the open-source ecosystem. This project makes it **easy to contribute without daily maintenance**.

