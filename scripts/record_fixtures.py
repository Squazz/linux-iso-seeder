"""Captures the upstream pages fetch_torrents' scrapers read into
tests/fixtures/pages/, for tests/test_scrapers.py to replay.

Usage: python scripts/record_fixtures.py [distro ...]

Each capture is written as <distro>/<slug>.<ext> plus <slug>.meta.json
holding the URL it came from and when. Re-recording overwrites both, so
`git diff tests/fixtures/pages` shows exactly what changed upstream; the
expected scraper results in tests/test_scrapers.py then need updating to
match the new snapshot (that's the point - review that they still make
sense before accepting them).
"""

import json
import os
import sys
from datetime import UTC, datetime

import requests

FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "fixtures",
    "pages",
)

# (distro, slug, url, extension) - every URL a fetch_* scraper requests.
ENDPOINTS = (
    (
        "ubuntu",
        "meta-release-lts",
        "https://changelogs.ubuntu.com/meta-release-lts",
        "txt",
    ),
    (
        "debian",
        "amd64-bt-dvd",
        "https://cdimage.debian.org/debian-cd/current/amd64/bt-dvd/",
        "html",
    ),
    (
        "debian",
        "arm64-bt-dvd",
        "https://cdimage.debian.org/debian-cd/current/arm64/bt-dvd/",
        "html",
    ),
    (
        "debian",
        "amd64-bt-cd",
        "https://cdimage.debian.org/debian-cd/current/amd64/bt-cd/",
        "html",
    ),
    (
        "debian",
        "arm64-bt-cd",
        "https://cdimage.debian.org/debian-cd/current/arm64/bt-cd/",
        "html",
    ),
    ("kali", "get-kali", "https://www.kali.org/get-kali/", "html"),
    ("kali", "cdimage", "https://cdimage.kali.org/", "html"),
    ("arch", "releng-releases", "https://archlinux.org/releng/releases/", "html"),
    ("devuan", "get-devuan", "https://www.devuan.org/get-devuan", "html"),
    ("mint", "download", "https://www.linuxmint.com/download.php", "html"),
    ("fedora", "torrents", "https://torrent.fedoraproject.org/torrents/", "html"),
)


def record(distro, slug, url, ext, now):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    directory = os.path.join(FIXTURES_DIR, distro)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, f"{slug}.{ext}"), "wb") as f:
        f.write(response.content)
    meta = {
        "url": url,
        "captured": now.isoformat(timespec="seconds"),
        "content_type": response.headers.get("Content-Type"),
    }
    with open(os.path.join(directory, f"{slug}.meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    print(f"{distro}/{slug}.{ext}: {len(response.content)} bytes from {url}")


def main(argv):
    wanted = set(argv)
    now = datetime.now(UTC)
    for distro, slug, url, ext in ENDPOINTS:
        if not wanted or distro in wanted:
            record(distro, slug, url, ext, now)


if __name__ == "__main__":
    main(sys.argv[1:])
