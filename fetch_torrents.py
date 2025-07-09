#!/usr/bin/env python3
import os
import re
import json
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
    if os.path.exists(dest) or os.path.exists(added):
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

def fetch_kali_latest():
    url = "https://www.kali.org/get-kali/#kali-installer-images"
    try:
        html = requests.get(url, timeout=30).text

        matches = re.findall(r"kali-linux-(\d+\.\d+)-installer-", html)
        if not matches:
            logging.warning("Could not detect a Kali release number on %s", url)
            return False

        ver = max(matches, key=lambda v: tuple(map(int, v.split("."))))  # nyeste

        base_cd  = f"https://cdimage.kali.org/kali-{ver}"
        base_arm = f"https://kali.download/arm-images/kali-{ver}"

        torrents = [
            # --- ISO-installer-filer (cdimage) ---
            f"{base_cd}/kali-linux-{ver}-installer-amd64.iso.torrent",
            f"{base_cd}/kali-linux-{ver}-installer-netinst-amd64.iso.torrent",
            f"{base_cd}/kali-linux-{ver}-installer-everything-amd64.iso.torrent",
            f"{base_cd}/kali-linux-{ver}-installer-arm64.iso.torrent",
            f"{base_cd}/kali-linux-{ver}-installer-netinst-arm64.iso.torrent",
            f"{base_cd}/kali-linux-{ver}-installer-purple-amd64.iso.torrent",
            # --- ARM-/cloud-images (arm-spejl) ---
            f"{base_arm}/kali-linux-{ver}-raspberry-pi-armhf.img.xz.torrent",
            f"{base_arm}/kali-linux-{ver}-raspberry-pi-zero-2-w-armhf.img.xz.torrent",
            f"{base_arm}/kali-linux-{ver}-raspberry-pi-zero-w-armel.img.xz.torrent",
            f"{base_arm}/kali-linux-{ver}-cloud-genericcloud-amd64.tar.xz.torrent",
            f"{base_arm}/kali-linux-{ver}-cloud-genericcloud-arm64.tar.xz.torrent",
        ]

        results = {}
        for turl in torrents:
            name = os.path.basename(turl).replace(".torrent", "")
            results[name] = download_torrent(name, turl)

        if not any(results.values()):
            logging.warning("No Kali torrents could be downloaded.")
            return False

        return results

    except Exception as exc:
        logging.error("Kali fetch error: %s", exc)
        return False

def log_seed_ratios_via_http(rpc_url="http://localhost:9091/transmission/rpc",
                             auth: tuple | None = None):
    
    r = requests.post(rpc_url)
    headers = {"X-Transmission-Session-Id": r.headers["X-Transmission-Session-Id"]}
    payload = {
        "method": "torrent-get",
        "arguments": {"fields": ["name", "uploadRatio"]}
    }
    r = requests.post(rpc_url, json=payload, headers=headers, auth=auth, timeout=15)
    r.raise_for_status()
    for t in r.json()["arguments"]["torrents"]:
        logging.info("[ratio] %s  →  %.3f", t["name"], t["uploadRatio"])

if __name__ == "__main__":
    start_time = time.time()
    logging.info("Starting torrent fetch run.")

    success_count = 0
    failure_count = 0

    for func in [fetch_ubuntu_lts, fetch_debian_stable, fetch_kali_latest]:
        if func():
            success_count += 1
        else:
            failure_count += 1

    try:
        log_seed_ratios_via_http()
    except Exception as exc:
        logging.warning("Could not query Transmission: %s", exc)

    total, used, free = shutil.disk_usage("/downloads")
    logging.info(f"Downloads folder usage: {used // (2**30)} GB used / {total // (2**30)} GB total")

    elapsed = time.time() - start_time
    logging.info(f"Run complete in {elapsed:.2f} seconds. {success_count} successful, {failure_count} failed.")
