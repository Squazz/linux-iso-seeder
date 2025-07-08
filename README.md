# linux-iso-seeder

> **Automated Linux ISO torrent seeder in a single container.**
>
> Helps the open-source community by seeding official ISOs for multiple Linux distributions, with **no manual intervention after deployment**.

---

## 🚀 **Features**

✅ Automatically fetches the latest torrent files for:

- Ubuntu (latest LTS)  
- Debian (latest stable DVD-1)  
- Fedora (latest Workstation)  
- Arch Linux (latest rolling ISO)  
- Kali Linux (latest installer ISO)

✅ **Optional DistroWatch integration** to seed additional distributions  
✅ Daily updates with minimal resource usage  
✅ Uses **Transmission-daemon** (lightweight torrent client)  
✅ **Logs and metrics** for transparency and future monitoring  
✅ Configurable via environment variables  
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

## ⚙️ **Environment Variables**

| Variable | Description | Default |
|---|---|---|
| `ENABLE_DISTROWATCH` | Enable fetching torrents from DistroWatch | `false` |
| `DISTROWATCH_FILTER` | Comma-separated filters for DistroWatch torrents | *(none)* |
| `EXTRA_TORRENTS` | Comma-separated list of additional torrent URLs to fetch | *(none)* |

---

## 📝 **Usage Example**

```bash
docker build -t linux-iso-seeder .

docker run -d \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/watch:/watch \
  -v /path/to/logs:/logs \
  -e ENABLE_DISTROWATCH=true \
  -e DISTROWATCH_FILTER=ubuntu,debian,fedora \
  -p 9091:9091 \
  linux-iso-seeder
```

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

---

### **⭐️ If you find this project useful, please star it and share with others to spread the initiative.**
