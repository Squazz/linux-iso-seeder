#!/usr/bin/env python3
import os
import re
import json
import requests
import logging
import tempfile
import time
import shutil
import socket
from datetime import date
from bs4 import BeautifulSoup
from transmission_rpc import Client

import torrent_scrape

# Configure logging
log_dir = os.getenv('FETCH_TORRENTS_LOG_DIR', '/logs')
log_file = os.path.join(log_dir, "fetch_torrents.log")
ratio_log_file = os.path.join(log_dir, "fetch_torrents_ratios.log")
ratio_history_file = os.path.join(log_dir, "fetch_torrents_ratio_history.json")
old_release_check_state_file = os.path.join(log_dir, "fetch_torrents_old_release_check_state.json")
removed_history_file = os.path.join(log_dir, "fetch_torrents_removed_history.json")

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
        "Checking old releases",
        "Found unmet demand",
        "Old-release check complete",
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

ratio_handler = logging.FileHandler(ratio_log_file, mode='w', delay=True, encoding='utf-8')
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


def get_rpc_credentials():
    """TRANSMISSION_RPC_USERNAME/PASSWORD, read here so this script's own
    RPC calls (cleanup, ratio logging) authenticate the same way
    configure_transmission.py configured the daemon. Without this, setting
    rpc-authentication-required (as the README instructs whenever
    TRANSMISSION_RPC_WHITELIST is widened beyond localhost) makes every one
    of this script's own localhost RPC calls fail with 401 - silently, since
    callers only log the failure - permanently disabling cleanup."""
    username = os.getenv('TRANSMISSION_RPC_USERNAME', '').strip()
    password = os.getenv('TRANSMISSION_RPC_PASSWORD', '').strip()
    return username or None, password or None


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
    with open(log_file, 'r', encoding='utf-8') as f:
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

def format_run_summary(elapsed, success_count, existing_count, not_found_count, failure_count,
                        old_added=None, old_skipped=None):
    """The single end-of-run log line. old_added/old_skipped are only
    non-None when FETCH_TORRENTS_CHECK_OLD_RELEASES ran, so the count of
    torrents that flag introduced is visible at a glance rather than only
    in the earlier "Old-release check complete" line."""
    summary = (
        f"Run complete in {elapsed:.2f} seconds. {success_count} added, "
        f"{existing_count} existing, {not_found_count} not found upstream, {failure_count} failed."
    )
    if old_added is not None:
        summary += f" Old releases (FETCH_TORRENTS_CHECK_OLD_RELEASES): {old_added} added, {old_skipped} skipped."
    return summary


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

def _kali_torrent_urls(ver):
    base_cd  = f"https://cdimage.kali.org/kali-{ver}/kali-linux-{ver}-installer"
    base_arm = f"https://kali.download/arm-images/kali-{ver}/kali-linux-{ver}"
    base_cloud = f"https://kali.download/cloud-images/kali-{ver}/kali-linux-{ver}-cloud-genericcloud"
    return [
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


def fetch_kali_latest():
    url = "https://www.kali.org/get-kali/#kali-installer-images"
    try:
        html = requests.get(url, timeout=30).text

        matches = re.findall(r"kali-linux-(\d+\.\d+)-installer-", html)
        if not matches:
            logger.warning("Could not detect a Kali release number on %s", url)
            return False

        ver = max(matches, key=lambda v: tuple(map(int, v.split("."))))  # nyeste

        results = {}
        for turl in _kali_torrent_urls(ver):
            name = os.path.basename(turl).replace(".torrent", "")
            results[name] = turl

        if not results:
            logger.warning("No Kali torrents found.")
            return False

        return results

    except Exception as exc:
        logger.error("Kali fetch error: %s", exc)
        return False


def fetch_kali_old_versions():
    """Non-latest Kali release(s) still available on cdimage.kali.org, for
    the old-release demand check (FETCH_TORRENTS_CHECK_OLD_RELEASES).
    cdimage only keeps a 'current/' symlink plus a small number of prior
    'kali-X.Y/' folders - once a version's folder disappears there's no way
    to discover it here, unlike fetch_kali_latest() which always has a
    current release to find."""
    url = "https://cdimage.kali.org/"
    try:
        html = requests.get(url, timeout=30).text
        soup = BeautifulSoup(html, "html.parser")

        versions = []
        for link in soup.find_all('a', href=True):
            match = re.match(r'^kali-(\d+\.\d+)/$', link['href'])
            if match:
                versions.append(match.group(1))

        if len(versions) < 2:
            return {}

        versions.sort(key=lambda v: tuple(map(int, v.split("."))))
        old_versions = versions[:-1]  # newest is fetch_kali_latest()'s job

        results = {}
        for ver in old_versions:
            for turl in _kali_torrent_urls(ver):
                name = os.path.basename(turl).replace(".torrent", "")
                results[name] = turl
        return results

    except Exception as exc:
        logger.error("Kali old-release fetch error: %s", exc)
        return {}

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


def fetch_fedora_workstation_old_versions():
    """Non-latest Fedora Workstation Live torrents per arch, from the same
    listing fetch_fedora_workstation() already scrapes - for the
    old-release demand check (FETCH_TORRENTS_CHECK_OLD_RELEASES)."""
    url = "https://torrent.fedoraproject.org/torrents/"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        pattern = re.compile(r"^Fedora-Workstation-Live-([A-Za-z0-9_]+)-(\d+)\.torrent$")
        by_arch = {}
        for link in soup.find_all('a', href=True):
            match = pattern.match(link['href'])
            if not match:
                continue
            arch, version = match.group(1), int(match.group(2))
            by_arch.setdefault(arch, []).append((version, link['href']))

        results = {}
        for versions in by_arch.values():
            versions.sort(key=lambda entry: entry[0], reverse=True)
            for _version, href in versions[1:]:  # newest is fetch_fedora_workstation()'s job
                name = href.replace(".torrent", "")
                results[name] = url + href
        return results

    except Exception as exc:
        logger.error("Fedora old-release fetch error: %s", exc)
        return {}


def has_unmet_demand(scrape_result, min_leechers, min_leecher_ratio, allow_zero_seeders):
    """True if a live tracker scrape shows real, currently-unserved demand:
    at least min_leechers leechers in absolute terms (so a single leecher
    never justifies a download on its own), AND at least min_leecher_ratio
    times as many leechers as seeders - a deliberately low bar (default 0.1,
    i.e. leechers only need to reach 10% of the seeder count) since scrape
    data can't tell us whether existing seeders have spare upload capacity
    or are bandwidth-constrained, so leechers don't need to approach or
    outnumber seeders to represent real demand; this just guards against the
    extreme case of a handful of leechers on an enormous, clearly-already-
    served swarm.

    A swarm with zero seeders is excluded by default regardless of leecher
    count: a scrape can't confirm the leechers collectively hold every
    piece, so a zero-seeder swarm might never actually reach 100% complete -
    we could end up leeching it forever without ever being able to seed it
    back, which defeats the point. Pass allow_zero_seeders=True (via
    FETCH_TORRENTS_OLD_RELEASE_ALLOW_ZERO_SEEDERS) to gamble on reviving
    such swarms anyway - the absolute floor still applies.

    scrape_result is a torrent_scrape.scrape_torrent() result, or None if
    scraping failed."""
    if not scrape_result:
        return False
    leechers = scrape_result.get('leechers', 0)
    if leechers < min_leechers:
        return False
    seeders = scrape_result.get('seeders', 0)
    if seeders == 0:
        return allow_zero_seeders
    return leechers >= min_leecher_ratio * seeders


def evaluate_old_release_demand(name, url, min_leechers, min_leecher_ratio, allow_zero_seeders, timeout=15):
    """Downloads name's .torrent metadata and scrapes its trackers for live
    demand, without adding it to Transmission. Returns (keep, torrent_bytes,
    scrape_result): keep is True once has_unmet_demand() passes;
    torrent_bytes/scrape_result are None if the download or every tracker
    scrape failed."""
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 404:
            logger.info("%s not found upstream (404) during old-release check.", url)
            return False, None, None
        r.raise_for_status()
    except Exception as exc:
        logger.error("Failed to download %s for old-release check: %s", url, exc)
        return False, None, None

    torrent_bytes = r.content
    tmp = tempfile.NamedTemporaryFile(suffix=".torrent", delete=False)
    try:
        tmp.write(torrent_bytes)
        tmp.close()
        scrape_result = torrent_scrape.scrape_torrent(tmp.name, timeout=timeout)
    except Exception as exc:
        logger.warning("Could not scrape %s: %s", name, exc)
        scrape_result = None
    finally:
        os.remove(tmp.name)

    keep = has_unmet_demand(scrape_result, min_leechers, min_leecher_ratio, allow_zero_seeders)
    return keep, torrent_bytes, scrape_result


def load_old_release_check_state(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read old-release check state at %s (%s) - starting fresh.", path, exc)
        return {}


def save_old_release_check_state(path, state):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def should_recheck_old_release(name, check_state, today, recheck_interval_days):
    """True if name has never been checked, or its last check was at least
    recheck_interval_days ago. Without this, check_old_releases_for_demand()
    would re-download and re-scrape every not-yet-wanted candidate on every
    daily run forever."""
    record = check_state.get(name)
    if record is None:
        return True
    last_checked = date.fromisoformat(record['last_checked'])
    return (today - last_checked).days >= recheck_interval_days


def load_removed_history(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read removed-torrent history at %s (%s) - starting fresh.", path, exc)
        return {}


def save_removed_history(path, history):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def record_removal(history, name, today, reason):
    """Pure: returns a copy of history noting name was removed today, for
    whatever reason cleanup removed it (a superseded low-ratio version, or
    stagnation). Once here, check_old_releases_for_demand() treats it as
    permanently excluded by default - a momentary leecher blip on a torrent
    that already took 30 stagnant days to justify removing shouldn't trigger
    re-downloading it, since the ratio may never be recouped before it goes
    stagnant again. See FETCH_TORRENTS_OLD_RELEASE_SKIP_REMOVED."""
    updated = dict(history)
    updated[name] = {'removed_date': today.isoformat(), 'reason': reason}
    return updated


# Only distros with a discoverable back-catalog of old release torrents.
# Ubuntu (meta-release-lts lists every currently-"Supported: 1" LTS, which
# in practice includes very old ones under ESM) and Arch (releng lists every
# still-available release) already surface old versions through their
# normal fetch_*() functions and should_fetch_torrent()'s per-version ratio
# check - no separate discovery needed. Debian and Mint don't expose a
# similarly easy back-catalog with the current fetch approach.
OLD_RELEASE_DISCOVERY = {
    'kali': fetch_kali_old_versions,
    'fedora': fetch_fedora_workstation_old_versions,
}


def check_old_releases_for_demand(selected_distros, include_low_demand, min_leechers, min_leecher_ratio,
                                   allow_zero_seeders, check_state=None, removed_history=None, today=None,
                                   recheck_interval_days=7):
    """FETCH_TORRENTS_CHECK_OLD_RELEASES: for distros with old-release
    discovery, scrape each not-yet-seeded candidate's trackers and add it to
    the watch dir only if there's live unmet demand - no need to leech it
    first to find out.

    allow_zero_seeders controls whether a candidate with zero seeders can
    ever count as demand - see has_unmet_demand(). check_state
    ({name: {'last_checked', 'leechers'}}) is consulted so a candidate that
    was checked recently isn't re-downloaded and re-scraped on every daily
    run - see should_recheck_old_release(). removed_history
    ({name: {'removed_date', 'reason'}}) is consulted so a candidate cleanup
    already gave up on isn't automatically re-added from a momentary demand
    blip - see record_removal().

    Returns (added_count, skipped_count, updated check_state).
    """
    check_state = dict(check_state) if check_state else {}
    removed_history = removed_history or {}
    today = today or date.today()

    added = 0
    skipped = 0

    for distro in selected_distros:
        discover = OLD_RELEASE_DISCOVERY.get(distro)
        if not discover:
            continue

        candidates = discover()
        if not candidates:
            continue
        candidates = filter_low_demand(candidates, include_low_demand)

        for name, url in candidates.items():
            dest = os.path.join(watch_dir, f"{name}.torrent")
            added_marker = f"{dest}.added"
            if os.path.exists(dest) or os.path.exists(added_marker):
                continue

            if name in removed_history:
                logger.info(
                    "Skipping old release %s - previously removed on %s, not re-adding automatically.",
                    name, removed_history[name]['removed_date'],
                )
                skipped += 1
                continue

            if not should_recheck_old_release(name, check_state, today, recheck_interval_days):
                logger.debug("Skipping old release %s - checked recently, not due for recheck.", name)
                skipped += 1
                continue

            keep, torrent_bytes, scrape_result = evaluate_old_release_demand(
                name, url, min_leechers, min_leecher_ratio, allow_zero_seeders,
            )
            check_state[name] = {
                'last_checked': today.isoformat(),
                'leechers': scrape_result['leechers'] if scrape_result else None,
            }

            if keep:
                with open(dest, "wb") as f:
                    f.write(torrent_bytes)
                logger.info(
                    "Found unmet demand on old release %s (%d leechers via %s) - added.",
                    name, scrape_result['leechers'], scrape_result['tracker'],
                )
                added += 1
            else:
                if scrape_result is not None and scrape_result.get('seeders', 0) == 0 and not allow_zero_seeders:
                    logger.info(
                        "Skipping old release %s - %d leechers but 0 seeders via %s (no verified-complete copy "
                        "in the swarm; set FETCH_TORRENTS_OLD_RELEASE_ALLOW_ZERO_SEEDERS=true to gamble on it).",
                        name, scrape_result['leechers'], scrape_result['tracker'],
                    )
                elif scrape_result is not None:
                    logger.info(
                        "Skipping old release %s - %d leechers / %d seeders via %s "
                        "(need >= %d leechers and >= %.1fx as many leechers as seeders).",
                        name, scrape_result['leechers'], scrape_result.get('seeders', 0),
                        scrape_result['tracker'], min_leechers, min_leecher_ratio,
                    )
                elif torrent_bytes is not None:
                    logger.info(
                        "Skipping old release %s - could not determine live demand from any tracker.", name,
                    )
                skipped += 1

    return added, skipped, check_state


def log_seed_ratios_via_http(rpc_url="http://localhost:9091/transmission/rpc", auth: tuple | None = None):
    if auth is None:
        username, password = get_rpc_credentials()
        auth = (username, password) if username and password else None

    logger.info("Querying Transmission RPC for seed ratios...")
    r = requests.post(rpc_url, timeout=15)
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
# actually structured for each distro. The newest entry per group is never
# returned - it's the version fetch_*() functions currently consider "latest"
# upstream, so removing it would just get it silently re-fetched and
# re-downloaded on the very next run (should_fetch_torrent() only knows to
# skip a fetch once a *previous* version's ratio is on record). Kept separate
# from the cleanup_*() functions so the selection logic can be unit tested
# without a live Transmission RPC connection (see tests/test_fetch_torrents.py).
def _old_version_candidates(torrents):
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

    candidates = []
    for entries in groups.values():
        if len(entries) < 2:
            continue
        # Keep the highest version, consider the rest for removal.
        entries.sort(key=lambda entry: entry[0], reverse=True)
        candidates.extend(torrent for _version, torrent in entries[1:])
    return candidates

def plan_cleanup(torrents, skip_ratio_check=False, min_ratio=1.0):
    to_remove = []
    to_keep_low_ratio = []
    for torrent in _old_version_candidates(torrents):
        ratio = float(getattr(torrent, 'ratio', 0.0) or 0.0)
        if not skip_ratio_check and ratio < min_ratio:
            to_keep_low_ratio.append((torrent, ratio))
        else:
            to_remove.append(torrent)

    return to_remove, to_keep_low_ratio

def cleanup_old_versions():
    """Space-constrained option (CLEANUP_KEEP_ONLY_LATEST_VERSION=true):
    remove superseded versions as soon as they clear the ratio floor,
    regardless of whether anyone's still downloading them."""
    username, password = get_rpc_credentials()
    tc = Client(host='localhost', port=9091, username=username, password=password)
    torrents = tc.get_torrents()

    skip_ratio_check = parse_bool('CLEANUP_SKIP_RATIO_CHECK', False)
    min_ratio = float(os.getenv('CLEANUP_MIN_RATIO', '1.0'))

    to_remove, to_keep_low_ratio = plan_cleanup(torrents, skip_ratio_check, min_ratio)

    for torrent, ratio in to_keep_low_ratio:
        logger.info(
            "Keeping old version %s – ratio %.3f is below cleanup threshold %.3f.",
            torrent.name, ratio, min_ratio,
        )

    removed_history = load_removed_history(removed_history_file)
    today = date.today()
    for torrent in to_remove:
        logger.info(f"Removing old version: {torrent.name}")
        tc.remove_torrent(torrent.id, delete_data=True)
        removed_history = record_removal(removed_history, torrent.name, today, 'keep_only_latest')
    save_removed_history(removed_history_file, removed_history)


RATIO_HISTORY_SAMPLE_INTERVAL_DAYS = 7


def load_ratio_history(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read ratio history at %s (%s) – starting fresh.", path, exc)
        return {}


def save_ratio_history(path, history):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


# Keeps the on-disk history bounded regardless of how long the seeder has
# been running: torrents no longer seeding are dropped entirely, and each
# remaining torrent keeps at most ~(window_days / interval) samples - one
# taken every RATIO_HISTORY_SAMPLE_INTERVAL_DAYS, pruned once older than
# window_days + the interval. That's a fixed handful of small numbers per
# torrent forever, not one entry per run.
def update_ratio_history(history, current_ratios, today, sample_interval_days=RATIO_HISTORY_SAMPLE_INTERVAL_DAYS, window_days=30):
    max_age_days = window_days + sample_interval_days
    updated = {}
    for name, ratio in current_ratios.items():
        samples = list(history.get(name, []))
        if not samples or (today - date.fromisoformat(samples[-1]['date'])).days >= sample_interval_days:
            samples.append({'date': today.isoformat(), 'ratio': ratio})
        updated[name] = [
            s for s in samples
            if (today - date.fromisoformat(s['date'])).days <= max_age_days
        ]
    return updated


def _stagnation_anchor(samples, today, window_days):
    """Ratio of the oldest recorded sample that's at least window_days old,
    or None if we don't have one yet - i.e. this torrent is too new to judge
    either way."""
    old_enough = [s for s in samples if (today - date.fromisoformat(s['date'])).days >= window_days]
    if not old_enough:
        return None
    return min(old_enough, key=lambda s: s['date'])['ratio']


def plan_stagnation_cleanup(torrents, history, today, window_days=30, min_ratio_delta=0.02):
    """Default cleanup path: among superseded (non-latest) versions per
    (distro, type) group, remove ones whose ratio has grown less than
    min_ratio_delta over the last window_days - nobody's downloading them
    anymore. Still-growing or not-yet-old-enough-to-judge candidates are
    kept. The latest/only version of a group is never a candidate (see
    _old_version_candidates)."""
    to_remove = []
    to_keep = []
    for torrent in _old_version_candidates(torrents):
        ratio = float(getattr(torrent, 'ratio', 0.0) or 0.0)
        anchor = _stagnation_anchor(history.get(torrent.name, []), today, window_days)
        if anchor is None:
            to_keep.append((torrent, None))
            continue
        delta = ratio - anchor
        if delta < min_ratio_delta:
            to_remove.append(torrent)
        else:
            to_keep.append((torrent, delta))
    return to_remove, to_keep


def cleanup_stagnant_torrents():
    username, password = get_rpc_credentials()
    tc = Client(host='localhost', port=9091, username=username, password=password)
    torrents = tc.get_torrents()

    window_days = int(os.getenv('CLEANUP_STAGNATION_WINDOW_DAYS', '30'))
    min_ratio_delta = float(os.getenv('CLEANUP_STAGNATION_MIN_RATIO_DELTA', '0.02'))
    today = date.today()

    history = load_ratio_history(ratio_history_file)
    current_ratios = {t.name: float(getattr(t, 'ratio', 0.0) or 0.0) for t in torrents}
    history = update_ratio_history(history, current_ratios, today, window_days=window_days)

    to_remove, to_keep = plan_stagnation_cleanup(torrents, history, today, window_days, min_ratio_delta)

    for torrent, delta in to_keep:
        if delta is None:
            logger.info(
                "Keeping old version %s – not enough ratio history yet (need %d days).",
                torrent.name, window_days,
            )
        else:
            logger.info(
                "Keeping old version %s – ratio grew by %.3f over the last %d days.",
                torrent.name, delta, window_days,
            )
    removed_history = load_removed_history(removed_history_file)
    for torrent in to_remove:
        logger.info(
            "Removing stagnant torrent: %s (no meaningful ratio growth in %d days)",
            torrent.name, window_days,
        )
        tc.remove_torrent(torrent.id, delete_data=True)
        removed_history = record_removal(removed_history, torrent.name, today, 'stagnant')
    save_removed_history(removed_history_file, removed_history)

    save_ratio_history(ratio_history_file, history)

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

    old_added = old_skipped = None
    check_old_releases = parse_bool('FETCH_TORRENTS_CHECK_OLD_RELEASES', False)
    if check_old_releases:
        old_release_min_leechers = int(os.getenv('FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHERS', '10'))
        old_release_min_leecher_ratio = float(os.getenv('FETCH_TORRENTS_OLD_RELEASE_MIN_LEECHER_RATIO', '0.1'))
        old_release_allow_zero_seeders = parse_bool('FETCH_TORRENTS_OLD_RELEASE_ALLOW_ZERO_SEEDERS', False)
        old_release_recheck_days = int(os.getenv('FETCH_TORRENTS_OLD_RELEASE_RECHECK_DAYS', '7'))
        skip_previously_removed = parse_bool('FETCH_TORRENTS_OLD_RELEASE_SKIP_REMOVED', True)

        check_state = load_old_release_check_state(old_release_check_state_file)
        removed_history = load_removed_history(removed_history_file) if skip_previously_removed else {}

        logger.info(
            "Checking old releases for unmet demand (min leechers: %d, min leecher/seeder ratio: %.1fx, "
            "allow zero-seeder swarms: %s, recheck interval: %d days)...",
            old_release_min_leechers, old_release_min_leecher_ratio, old_release_allow_zero_seeders,
            old_release_recheck_days,
        )
        old_added, old_skipped, check_state = check_old_releases_for_demand(
            selected_distros, include_low_demand, old_release_min_leechers, old_release_min_leecher_ratio,
            old_release_allow_zero_seeders, check_state, removed_history, date.today(), old_release_recheck_days,
        )
        save_old_release_check_state(old_release_check_state_file, check_state)
        logger.info("Old-release check complete: %d added, %d skipped.", old_added, old_skipped)

    if wait_for_transmission_rpc():
        try:
            log_seed_ratios_via_http()
        except Exception as exc:
            logger.error("Could not query Transmission: %s", exc)
    else:
        logger.error("Transmission RPC not available on localhost:9091; skipping ratio logs.")
        
    try:
        if parse_bool('CLEANUP_KEEP_ONLY_LATEST_VERSION', False):
            cleanup_old_versions()
        else:
            cleanup_stagnant_torrents()
    except Exception as exc:
        logger.error("Could not clean up old versions: %s", exc)

    total, used, free = shutil.disk_usage("/downloads")
    logger.info(f"Downloads folder usage: {used // (2**30)} GB used / {total // (2**30)} GB total")

    elapsed = time.time() - start_time
    logger.info(format_run_summary(
        elapsed, success_count, existing_count, not_found_count, failure_count, old_added, old_skipped,
    ))
