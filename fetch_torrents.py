#!/usr/bin/env python3
import os
import re
import json
import requests
import logging
import time
import shutil
import socket
from bs4 import BeautifulSoup
from transmission_rpc import Client

# Configure logging
log_dir = os.getenv('FETCH_TORRENTS_LOG_DIR', '/logs')
log_file = os.path.join(log_dir, "fetch_torrents.log")
ratio_log_file = os.path.join(log_dir, "fetch_torrents_ratios.log")

def parse_log_level(env_var: str, default: int = logging.INFO) -> int:
    value = os.getenv(env_var, '').strip()
    if not value:
        return default
    if value.isdigit():
        try:
            return int(value)
        except ValueError:
            return default
    level = value.upper()
    return logging._nameToLevel.get(level, default)


def parse_bool(env_var: str, default: bool = False) -> bool:
    value = os.getenv(env_var, '').strip().lower()
    if not value:
        return default
    return value in ('1', 'true', 'yes', 'on')

log_level = parse_log_level('FETCH_TORRENTS_LOG_LEVEL', parse_log_level('LOG_LEVEL', logging.INFO))
formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(formatter)

class RatioOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().startswith("[ratio]")

class NonRatioFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith("[ratio]")

class ImportantMessageFilter(logging.Filter):
    def __init__(self, level: int, important_prefixes=None):
        super().__init__()
        self.level = level
        self.important_prefixes = important_prefixes or []

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.levelno >= self.level:
            return True
        return any(message.startswith(prefix) for prefix in self.important_prefixes)


def get_always_log_prefixes():
    return [
        "Starting torrent fetch run.",
        "Run complete in",
        "Downloads folder usage:",
        "Fetching latest",
        "Querying Transmission RPC",
        "Selected distros for this run:",
        "Skipping distro",
    ]

always_log_enabled = parse_bool('FETCH_TORRENTS_ALWAYS_LOG', True)
important_prefixes = get_always_log_prefixes() if always_log_enabled else []

stream_handler.setLevel(logging.DEBUG)
stream_handler.addFilter(NonRatioFilter())
if always_log_enabled:
    stream_handler.addFilter(ImportantMessageFilter(log_level, important_prefixes))
else:
    stream_handler.setLevel(log_level)

file_handler.setLevel(logging.DEBUG)
file_handler.addFilter(NonRatioFilter())
if always_log_enabled:
    file_handler.addFilter(ImportantMessageFilter(log_level, important_prefixes))
else:
    file_handler.setLevel(log_level)

ratio_handler = logging.FileHandler(ratio_log_file, mode='w')
ratio_handler.setLevel(logging.INFO)
ratio_handler.addFilter(RatioOnlyFilter())
ratio_handler.setFormatter(formatter)

logger = logging.getLogger('fetch_torrents')
logger.setLevel(logging.DEBUG)
logger.addHandler(stream_handler)
logger.addHandler(file_handler)
logger.addHandler(ratio_handler)
logger.propagate = False

watch_dir = "/watch"


def wait_for_transmission_rpc(host='localhost', port=9091, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            time.sleep(1)
    return False


def get_previous_ratios(log_file):
    if not os.path.exists(log_file):
        return {}
    ratios = {}
    with open(log_file, 'r') as f:
        lines = f.readlines()

    # Only parse the latest ratio segment between the last start and end markers.
    start_marker = '[ratio] RATIOS START'
    end_marker = '[ratio] RATIOS END'
    start_index = None
    end_index = None

    for idx, line in enumerate(lines):
        if start_marker in line:
            start_index = idx
            end_index = None
        elif start_index is not None and end_marker in line:
            end_index = idx

    if start_index is not None:
        if end_index is not None and end_index > start_index:
            lines = lines[start_index + 1:end_index]
        else:
            lines = lines[start_index + 1:]

    for line in lines:
        match = re.search(r'\[ratio\]\s+(.+?)\s+→\s+(\d+\.\d+)', line)
        if match:
            name = match.group(1).strip()
            ratio = float(match.group(2))
            ratios[name] = ratio
    return ratios

distro_patterns = {
    'ubuntu': re.compile(r'^ubuntu-|^lbuntu-|^xbuntu-'),
    'debian': re.compile(r'^debian-'),
    'kali': re.compile(r'^kali-linux-'),
    'arch': re.compile(r'^archlinux-'),
    'mint': re.compile(r'^linuxmint-'),
    'fedora': re.compile(r'^Fedora-Workstation-Live-'),
}

DEFAULT_DISTROS = tuple(distro_patterns.keys())

def parse_supported_distros(env_var='FETCH_TORRENTS_DISTROS'):
    value = os.getenv(env_var, '').strip()
    if not value:
        return list(DEFAULT_DISTROS)

    requested = [entry.strip().lower() for entry in value.split(',') if entry.strip()]
    valid = [d for d in DEFAULT_DISTROS if d in requested]

    invalid = [entry for entry in requested if entry not in DEFAULT_DISTROS]
    if invalid:
        logger.warning(
            "%s contains unknown distributions: %s. Valid values: %s",
            env_var,
            ", ".join(invalid),
            ", ".join(DEFAULT_DISTROS),
        )

    if not valid:
        logger.warning(
            "%s did not specify any valid distros. Falling back to all: %s",
            env_var,
            ", ".join(DEFAULT_DISTROS),
        )
        return list(DEFAULT_DISTROS)

    return valid


# cloud-genericcloud images are chronically low-ratio regardless of
# architecture or how recent the release is (see fetch_torrents_ratios.log) —
# cloud images are typically pulled directly from a cloud provider rather
# than via BitTorrent, so hosting them by default tends to leave this seeder
# as a leecher.
#
# Kali's netinst installer is likewise consistently low-ratio across amd64,
# arm64 and many releases, because Kali also ships a plain "installer" and an
# "installer-everything" image that cover the same need. This is Kali-
# specific: Debian's netinst image is the opposite — the single highest-ratio
# image in the whole log — so it's deliberately excluded from this pattern.
#
# arm64/aarch64/armhf/armel builds were deliberately *not* included here —
# the ratio log's low numbers for those are almost all older, superseded
# versions (normal version churn already handled by
# should_fetch_torrent()/plan_cleanup()); current-version arm64/armhf builds
# (e.g. kali-linux-2026.2-raspberry-pi-armhf-img-xz, debian-13.6.0-arm64-netinst.iso)
# actually have solid ratios, so architecture alone isn't a reliable signal.
#
# FETCH_TORRENTS_INCLUDE_LOW_DEMAND opts back into all of the above.
LOW_DEMAND_PATTERN = re.compile(
    r'(cloud-genericcloud|^kali-linux-\d+\.\d+-installer-netinst-)', re.IGNORECASE
)

def is_low_demand_variant(name):
    return bool(LOW_DEMAND_PATTERN.search(name))

def filter_low_demand(torrents, include_low_demand):
    if include_low_demand:
        return dict(torrents)
    kept = {}
    for name, url in torrents.items():
        if is_low_demand_variant(name):
            logger.info(
                "Skipping %s – low-demand image family (set "
                "FETCH_TORRENTS_INCLUDE_LOW_DEMAND=true to include).", name,
            )
        else:
            kept[name] = url
    return kept

def get_distro(name):
    for distro, pattern in distro_patterns.items():
        if pattern.match(name):
            return distro
    return None

def version_to_tuple(v):
    try:
        return tuple(map(int, v.split('.')))
    except ValueError as exc:
        raise ValueError(f"Invalid version string '{v}'") from exc

def parse_version_type(name, distro):
    if distro == 'ubuntu':
        parts = name.split('-')
        prefix = parts[0]
        version = parts[1]
        suffix = '-'.join(parts[2:])
        type_ = f"{prefix}-{suffix}"
    elif distro == 'debian':
        parts = name.split('-')
        version = parts[1]
        arch = parts[2]
        type_suffix = '-'.join(parts[3:])
        type_ = f"{arch}-{type_suffix}"
    elif distro == 'kali':
        parts = name.split('-')
        version = parts[2]
        type_ = '-'.join(parts[3:])
    elif distro == 'arch':
        parts = name.split('-')
        version = parts[1]
        type_ = ''
    elif distro == 'mint':
        parts = name.split('-')
        version = parts[1]
        type_ = '-'.join(parts[2:])
    elif distro == 'fedora':
        parts = name.split('-')
        version = parts[-1]
        type_ = parts[-2]
    else:
        version = ''
        type_ = ''
    return version, type_

def should_fetch_torrent(name, ratios):
    if os.getenv('SKIP_RATIO_CHECK', 'false').lower() == 'true':
        return True
    distro = get_distro(name)
    if not distro:
        return True

    try:
        version_str, type_ = parse_version_type(name, distro)
        version = version_to_tuple(version_str)
    except Exception as exc:
        logger.error("Could not determine ratio decision for %s: %s", name, exc)
        return True

    # get all ratios for this type
    type_ratios = {}
    for n, r in ratios.items():
        d = get_distro(n)
        if d == distro:
            try:
                v_str, t = parse_version_type(n, d)
                if t == type_:
                    type_ratios[version_to_tuple(v_str)] = r
            except Exception as exc:
                logger.warning("Skipping stored ratio entry %s due to parse error: %s", n, exc)

    if not type_ratios:
        return True  # no previous, fetch
    # find max version < current
    prev_versions = [v for v in type_ratios if v < version]
    if not prev_versions:
        return True  # no previous version, fetch
    prev_max = max(prev_versions)
    return type_ratios[prev_max] >= 1.0

def download_torrent(name, url):
    dest   = os.path.join(watch_dir, f"{name}.torrent")
    added  = os.path.join(watch_dir, f"{name}.torrent.added")

    # Skip if already processed or queued 
    if os.path.exists(dest):
        logger.info("Skip %s – torrent already present.", os.path.basename(dest))
        return "existing"
    if os.path.exists(added):
        logger.info("Skip %s – torrent already present.", os.path.basename(added))
        return "existing"

    try:
        logger.info(f"Fetching {url} ...")
        r = requests.get(url, timeout=30)
        if r.status_code == 404:
            # Expected for releases upstream still flags as "supported" (e.g.
            # for ESM) long after their installer media has been pulled —
            # not a real failure, so don't log it as an error.
            logger.info("%s not found upstream (404) – likely no longer hosted.", url)
            return "not_found"
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
        logger.info(f"Saved {dest}")
        return "added"
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return "failed"

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

            torrent_urls = [
                f"https://releases.ubuntu.com/{codename}/ubuntu-{version}-desktop-amd64.iso.torrent",
                f"https://releases.ubuntu.com/{codename}/ubuntu-{version}-live-server-amd64.iso.torrent",
                f"https://cdimage.ubuntu.com/lubuntu/releases/{codename}/release/lubuntu-{version}-desktop-amd64.iso.torrent",
                f"https://torrent.ubuntu.com/xubuntu/releases/{codename}/release/desktop/xubuntu-{version}-desktop-amd64.iso.torrent",
                f"https://torrent.ubuntu.com/xubuntu/releases/{codename}/release/minimal/xubuntu-{version}-minimal-amd64.iso.torrent",
            ]
            # Use the real ISO filename (arch + .iso) as the dict key, same as
            # fetch_kali_latest() does, so it matches what Transmission later
            # reports as torrent.name and the ratio-check lookup can find it.
            for torrent_url in torrent_urls:
                name = os.path.basename(torrent_url).replace(".torrent", "")
                results[name] = torrent_url

        return results
    except Exception as e:
        logger.error(f"Ubuntu fetch error: {e}")
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
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                if ".iso.torrent" in href:
                    torrent_url = url + href
                    # Keep the .iso extension so this matches what Transmission
                    # later reports as torrent.name for the ratio-check lookup.
                    name = os.path.basename(href).replace(".torrent", "")
                    results[name] = torrent_url
                    break
            else:
                logger.warning("No Debian DVD-1 torrent found.")  
            
        except Exception as e:
            logger.error(f"Debian fetch error: {e}")

    return results

def fetch_kali_latest():
    url = "https://www.kali.org/get-kali/#kali-installer-images"
    try:
        html = requests.get(url, timeout=30).text

        matches = re.findall(r"kali-linux-(\d+\.\d+)-installer-", html)
        if not matches:
            logger.warning("Could not detect a Kali release number on %s", url)
            return False

        ver = max(matches, key=lambda v: tuple(map(int, v.split("."))))  # nyeste

        base_cd  = f"https://cdimage.kali.org/kali-{ver}/kali-linux-{ver}-installer"
        base_arm = f"https://kali.download/arm-images/kali-{ver}/kali-linux-{ver}"
        base_cloud = f"https://kali.download/cloud-images/kali-{ver}/kali-linux-{ver}-cloud-genericcloud"
        torrents = [
            f"{base_cd}-amd64.iso.torrent",
            f"{base_cd}-netinst-amd64.iso.torrent",
            f"{base_cd}-everything-amd64.iso.torrent",
            f"{base_cd}-arm64.iso.torrent",
            f"{base_cd}-netinst-arm64.iso.torrent",
            f"{base_cd}-purple-amd64.iso.torrent",

            f"{base_arm}-raspberry-pi-armhf.img.xz.torrent",
            f"{base_arm}-raspberry-pi-zero-2-w-armhf.img.xz.torrent",
            f"{base_arm}-raspberry-pi-zero-w-armel.img.xz.torrent",
            
            f"{base_cloud}-amd64.tar.xz.torrent",
            f"{base_cloud}-arm64.tar.xz.torrent",
        ]

        results = {}
        for turl in torrents:
            name = os.path.basename(turl).replace(".torrent", "")
            results[name] = turl

        if not results:
            logger.warning("No Kali torrents found.")
            return False

        return results

    except Exception as exc:
        logger.error("Kali fetch error: %s", exc)
        return False

def fetch_arch_latest():
    base_url = "https://archlinux.org"
    url = f"{base_url}/releng/releases/"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        results = {}
        release_rows = soup.find("table", id="release-table").find_all("tr")
        for row in release_rows:
            if not row.find("td", class_="available-yes"):
                continue

            torrent_url_pattern = "/releng/releases/(.+)/torrent/"
            href = row.find("a", href=re.compile(torrent_url_pattern))['href']
            version = re.sub(torrent_url_pattern, "\\1", href)

            logger.debug(f"Arch Linux {version}: {base_url}{href}")
            results[f"archlinux-{version}"] = base_url + href

        return results
    except Exception as exc:
        logger.error("Arch Linux fetch error: %s", exc)
        return False

def fetch_linuxmint_cinnamon():
    url = "https://www.linuxmint.com/download.php"
    try:
        text = requests.get(url, timeout=30).text
        match = re.search(r"<title>Download Linux Mint ([\d.]+)", text)
        if not match:
            logger.warning("Could not detect a Linux Mint version on %s", url)
            return False

        version = match.group(1)
        torrent_url = f"https://www.linuxmint.com/torrents/linuxmint-{version}-cinnamon-64bit.iso.torrent"
        # Use the real ISO filename (as embedded in the torrent's own "name"
        # field) as the dict key, same as fetch_ubuntu_lts() does, so it
        # matches what Transmission later reports as torrent.name.
        name = os.path.basename(torrent_url).replace(".torrent", "")
        return {name: torrent_url}
    except Exception as e:
        logger.error(f"Linux Mint fetch error: {e}")
        return False

def fetch_fedora_workstation():
    url = "https://torrent.fedoraproject.org/torrents/"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        pattern = re.compile(r"^Fedora-Workstation-Live-([A-Za-z0-9_]+)-(\d+)\.torrent$")
        latest = {}
        for link in soup.find_all('a', href=True):
            match = pattern.match(link['href'])
            if not match:
                continue
            arch, version = match.group(1), int(match.group(2))
            if arch not in latest or version > latest[arch][0]:
                latest[arch] = (version, link['href'])

        if not latest:
            logger.warning("No Fedora Workstation torrents found on %s", url)
            return False

        results = {}
        for arch, (version, href) in latest.items():
            torrent_url = url + href
            # The torrent's own "name" field (and Transmission's later
            # torrent.name) has no .iso extension for Fedora, unlike Ubuntu/
            # Debian, so the dict key is just the basename minus .torrent.
            name = href.replace(".torrent", "")
            results[name] = torrent_url

        return results
    except Exception as exc:
        logger.error("Fedora fetch error: %s", exc)
        return False

def log_seed_ratios_via_http(rpc_url="http://localhost:9091/transmission/rpc", auth: tuple | None = None):
    logger.info("Querying Transmission RPC for seed ratios...")
    r = requests.post(rpc_url)
    headers = {"X-Transmission-Session-Id": r.headers["X-Transmission-Session-Id"]}
    payload = {
        "method": "torrent-get",
        "arguments": {"fields": ["name", "uploadRatio"]}
    }
    r = requests.post(rpc_url, json=payload, headers=headers, auth=auth, timeout=15)
    r.raise_for_status()

    torrents = r.json()["arguments"]["torrents"]

    # sort by uploadRatio, highest first
    torrents_sorted = sorted(
        torrents,
        key=lambda t: float(t["uploadRatio"] or 0.0),
        reverse=True,
    )

    logger.info("[ratio] RATIOS START")
    for t in torrents_sorted:
        logger.info("[ratio] %-50s → %.3f", t["name"], float(t["uploadRatio"] or 0.0))
    logger.info("[ratio] RATIOS END")
    logger.info("")

# Group torrents by (distro, type_) using the same parsing logic used for
# ratio lookups, so grouping matches how real Transmission torrent names are
# actually structured for each distro. Kept separate from cleanup_old_versions()
# so the selection logic can be unit tested without a live Transmission RPC
# connection (see tests/test_fetch_torrents.py).
def plan_cleanup(torrents, skip_ratio_check=False, min_ratio=1.0):
    groups = {}
    for torrent in torrents:
        distro = get_distro(torrent.name)
        if not distro:
            continue
        try:
            version_str, type_ = parse_version_type(torrent.name, distro)
            version = version_to_tuple(version_str)
        except Exception as exc:
            logger.warning("Skipping %s during cleanup due to parse error: %s", torrent.name, exc)
            continue
        groups.setdefault((distro, type_), []).append((version, torrent))

    to_remove = []
    to_keep_low_ratio = []
    for (distro, type_), entries in groups.items():
        if len(entries) < 2:
            continue
        # Keep the highest version, consider the rest for removal.
        entries.sort(key=lambda entry: entry[0], reverse=True)
        for version, torrent in entries[1:]:
            ratio = float(getattr(torrent, 'ratio', 0.0) or 0.0)
            if not skip_ratio_check and ratio < min_ratio:
                to_keep_low_ratio.append((torrent, ratio))
            else:
                to_remove.append(torrent)

    return to_remove, to_keep_low_ratio

def cleanup_old_versions():
    tc = Client(host='localhost', port=9091)
    torrents = tc.get_torrents()

    skip_ratio_check = parse_bool('CLEANUP_SKIP_RATIO_CHECK', False)
    min_ratio = float(os.getenv('CLEANUP_MIN_RATIO', '1.0'))

    to_remove, to_keep_low_ratio = plan_cleanup(torrents, skip_ratio_check, min_ratio)

    for torrent, ratio in to_keep_low_ratio:
        logger.info(
            "Keeping old version %s – ratio %.3f is below cleanup threshold %.3f.",
            torrent.name, ratio, min_ratio,
        )
    for torrent in to_remove:
        logger.info(f"Removing old version: {torrent.name}")
        tc.remove_torrent(torrent.id, delete_data=True)

if __name__ == "__main__":
    start_time = time.time()
    logger.info("Starting torrent fetch run.")

    ratios = get_previous_ratios(ratio_log_file)

    success_count = 0
    existing_count = 0
    failure_count = 0
    not_found_count = 0

    distro_funcs = [
        ('ubuntu', fetch_ubuntu_lts),
        ('debian', fetch_debian_stable),
        ('kali', fetch_kali_latest),
        ('arch', fetch_arch_latest),
        ('mint', fetch_linuxmint_cinnamon),
        ('fedora', fetch_fedora_workstation),
    ]

    selected_distros = parse_supported_distros()
    logger.info("Selected distros for this run: %s", ", ".join(selected_distros))

    include_low_demand = parse_bool('FETCH_TORRENTS_INCLUDE_LOW_DEMAND', False)
    logger.info("Including low-demand image families (arm64/cloud/etc.): %s", include_low_demand)

    for distro, func in distro_funcs:
        if distro not in selected_distros:
            logger.info("Skipping distro %s because it is not enabled by FETCH_TORRENTS_DISTROS.", distro)
            continue

        logger.info(f"Fetching latest {distro} torrents...")
        torrents = func()
        if torrents:
            torrents = filter_low_demand(torrents, include_low_demand)
            for name, url in torrents.items():
                if should_fetch_torrent(name, ratios):
                    status = download_torrent(name, url)
                    if status == "added":
                        success_count += 1
                    elif status == "existing":
                        existing_count += 1
                    elif status == "not_found":
                        not_found_count += 1
                    else:
                        failure_count += 1
                else:
                    logger.info(f"Skipping {name} due to low ratio on previous version.")
        else:
            failure_count += 1

    if wait_for_transmission_rpc():
        try:
            log_seed_ratios_via_http()
        except Exception as exc:
            logger.error("Could not query Transmission: %s", exc)
    else:
        logger.error("Transmission RPC not available on localhost:9091; skipping ratio logs.")
        
    try:
        cleanup_old_versions()
    except Exception as exc:
        logger.error("Could not clean up old versions: %s", exc)

    total, used, free = shutil.disk_usage("/downloads")
    logger.info(f"Downloads folder usage: {used // (2**30)} GB used / {total // (2**30)} GB total")

    elapsed = time.time() - start_time
    logger.info(
        f"Run complete in {elapsed:.2f} seconds. {success_count} added, "
        f"{existing_count} existing, {not_found_count} not found upstream, {failure_count} failed."
    )
