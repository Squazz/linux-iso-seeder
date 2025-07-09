#!/usr/bin/env python3
import os
import re
import requests
import logging
import time
import shutil
from bs4 import BeautifulSoup

# Configure logging
log_file = "/logs/fetch_torrents.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file)
    ]
)

watch_dir = "/watch"

def download_torrent(name, url):
    dest   = os.path.join(watch_dir, f"{name}.torrent")
    added  = os.path.join(watch_dir, f"{name}.torrent.added")

    # Skip if already processed or queued 
    if dest.exists() or added.exists():
        logging.info("Skip %s – torrent already present.", dest.name)
        return False

    try:
        logging.info(f"Fetching {url} ...")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
        logging.info(f"Saved {dest}")
        return True
    except Exception as e:
        logging.error(f"Failed to download {url}: {e}")
        return False

def fetch_ubuntu_lts():
    url = "https://releases.ubuntu.com/"
    try:
        text = requests.get("https://changelogs.ubuntu.com/meta-release-lts", timeout=30).text
        blocks  = [b for b in text.strip().split("\n\n") if "Supported: 1" in b]
        results = {}

        # newest first (optional – remove reversed() if order is irrelevant)
        for block in reversed(blocks):
            version  = re.search(r"Version:\s*([\d.]+)", block).group(1)
            codename = re.search(r"Dist:\s*(\w+)",   block).group(1)

            results[f"ubuntu-{version}-desktop"] = download_torrent(f"ubuntu-{version}-desktop", f"https://releases.ubuntu.com/{codename}/ubuntu-{version}-desktop-amd64.iso.torrent")
            results[f"ubuntu-{version}-live-server"] = download_torrent(f"ubuntu-{version}-live-server", f"https://releases.ubuntu.com/{codename}/ubuntu-{version}-live-server-amd64.iso.torrent")
            results[f"lbuntu-{version}-desktop"] = download_torrent(f"lbuntu-{version}-desktop", f"https://cdimage.ubuntu.com/lubuntu/releases/{codename}/release/lubuntu-{version}-desktop-amd64.iso.torrent")
            results[f"xbuntu-{version}-desktop"] = download_torrent(f"xbuntu-{version}-desktop", f"https://torrent.ubuntu.com/xubuntu/releases/{codename}/release/desktop/xubuntu-{version}-desktop-amd64.iso.torrent")
            results[f"xbuntu-{version}-minimal"] = download_torrent(f"xbuntu-{version}-minimal", f"https://torrent.ubuntu.com/xubuntu/releases/{codename}/release/minimal/xubuntu-{version}-minimal-amd64.iso.torrent")
            
        return results
    except Exception as e:
        logging.error(f"Ubuntu fetch error: {e}")
        return False

def fetch_debian_stable():
    urls = [
            "https://cdimage.debian.org/debian-cd/current/amd64/bt-dvd/",
            "https://cdimage.debian.org/debian-cd/current/arm64/bt-dvd/",
            "https://cdimage.debian.org/debian-cd/current/amd64/bt-cd/",
            "https://cdimage.debian.org/debian-cd/current/arm64/bt-cd/"
        ]
    results = {}

    for url in urls:
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            
            results[url] = False
            for link in soup.find_all('a', href=True):
                href = link['href']
                if ".iso.torrent" in href:
                    torrent_url = url + href
                    name = href.replace(".iso.torrent", "")
                    results[name] = download_torrent(name, torrent_url)
                    break
            else:
                logging.warning("No Debian DVD-1 torrent found.")  
            
        except Exception as e:
            logging.error(f"Debian fetch error: {e}")
            results[url] = False

    return results

def fetch_arch_latest():
    torrent_url = "https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso.torrent"
    return download_torrent("archlinux-latest", torrent_url)

def fetch_kali_latest():
    url = "https://www.kali.org/get-kali/#kali-installer-images"
    try:        
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        matches = re.findall(r"kali-linux-(\d+\.\d+)-installer-", html)

        if not matches:
            logging.warning("Could not detect a Kali release number on %s", url)
            return None
        # pick the highest version (works because <major>.<minor>)
        latest = max(matches, key=lambda v: tuple(map(int, v.split("."))))

        baseCD = f"https://cdimage.kali.org/kali-{ver}/kali-linux-{ver}-installer"
        baseARM = f"https://kali.download/arm-images/kali-{ver}/kali-linux-{ver}"
        torrents = [
            f"{baseCD}-amd64.iso.torrent",
            f"{baseCD}-netinst-amd64.iso.torrent",
            f"{baseCD}-everything-amd64.iso.torrent",
            f"{baseCD}-arm64.iso.torrent",
            f"{baseCD}-netinst-arm64.iso.torrent",
            f"{baseCD}-purple-amd64.iso.torrent",
            f"{baseARM}-raspberry-pi-armhf.img.xz.torrent",
            f"{baseARM}-raspberry-pi-zero-2-w-armhf.img.xz.torrent",
            f"{baseARM}-raspberry-pi-zero-w-armel.img.xz.torrent",
            f"{baseARM}-cloud-genericcloud-amd64.tar.xz.torrent",
            f"{baseARM}-cloud-genericcloud-arm64.tar.xz.torrent",
        ]
        results = {}

        for url in torrents:
            name = os.path.basename(url).replace(".torrent", "")
            results[name] = download_torrent(name, url)

        if not results:
            logging.warning("No Kali installer torrents found.")
            return False

        return results
    except Exception as e:
        logging.error(f"Kali fetch error: {e}")
        return False

def fetch_distrowatch_torrents():
    enable = os.getenv("ENABLE_DISTROWATCH", "false").lower() == "true"
    if not enable:
        logging.info("DistroWatch fetching disabled.")
        return False

    filters = os.getenv("DISTROWATCH_FILTER", "").split(",")
    filters = [f.strip().lower() for f in filters if f.strip()]

    url = "https://distrowatch.com/dwres.php?resource=torrents"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        count = 0
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.endswith(".torrent"):
                distro_name = link.text.lower()
                if filters and not any(f in distro_name for f in filters):
                    continue

                torrent_url = href if href.startswith("http") else f"https://distrowatch.com/{href}"
                name = os.path.basename(torrent_url).replace(".torrent", "")
                if download_torrent(name, torrent_url):
                    count += 1
        logging.info(f"DistroWatch torrents fetched: {count}")
        return True
    except Exception as e:
        logging.error(f"DistroWatch fetch error: {e}")
        return False

if __name__ == "__main__":
    start_time = time.time()
    logging.info("Starting torrent fetch run.")

    success_count = 0
    failure_count = 0

    for func in [fetch_ubuntu_lts, fetch_debian_stable, fetch_kali_latest, fetch_arch_latest, fetch_distrowatch_torrents]:
        if func():
            success_count += 1
        else:
            failure_count += 1

    total, used, free = shutil.disk_usage("/downloads")
    logging.info(f"Downloads folder usage: {used // (2**30)} GB used / {total // (2**30)} GB total")

    elapsed = time.time() - start_time
    logging.info(f"Run complete in {elapsed:.2f} seconds. {success_count} successful, {failure_count} failed.")
