"""Live drift checks for .github/workflows/drift.yml: the scrapers and the
tracker scrape, run against the real upstream sites.

Usage:
  python scripts/live_check.py scrapers   every fetcher returns well-formed,
                                          reachable candidates
  python scripts/live_check.py tracker    a current Ubuntu torrent's tracker
                                          answers a scrape with integer counts

Prints what it checked and exits 1 if anything looks wrong. Not part of the
merge check - upstream sites move independently of this repo.
"""

import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import requests

import fetch_torrents as ft
import torrent_scrape

FETCHERS = (
    *ft.DEFAULT_FETCHERS,
    ("kali-old", ft.fetch_kali_old_versions),
    ("fedora-old", ft.fetch_fedora_workstation_old_versions),
)
# Old-release fetchers may legitimately find nothing (e.g. right after
# cdimage.kali.org drops the previous release's folder).
MAY_BE_EMPTY = {"kali-old", "fedora-old"}


def distro_of(fetcher_name):
    return fetcher_name.removesuffix("-old")


def problems(distro, name, url):
    """What's wrong with one candidate a fetcher returned, as messages
    (empty if it looks like a real release of `distro`)."""
    found = []
    pattern = (
        ft.DEVUAN_NAME_PATTERN if distro == "devuan" else ft.distro_patterns[distro]
    )
    if not pattern.match(name):
        found.append(f"name {name!r} doesn't look like a {distro} release")
    elif distro != "devuan":
        try:
            version, _type = ft.parse_version_type(name, distro)
            ft.version_to_tuple(version)
        except Exception:
            found.append(f"name {name!r} has no parseable version")
    if not url.startswith("https://"):
        found.append(f"URL {url!r} is not https")
    if not (
        url.endswith(".torrent") or (distro == "arch" and url.endswith("/torrent/"))
    ):
        found.append(f"URL {url!r} is not a .torrent")
    return found


def is_reachable(url):
    try:
        r = requests.head(url, allow_redirects=True, timeout=30)
        if r.status_code == 405:  # HEAD not allowed: ask for the body instead
            with requests.get(url, stream=True, timeout=30) as r:
                return r.status_code == 200
        return r.status_code == 200
    except requests.RequestException:
        return False


def check_scrapers():
    failures = []
    for fetcher_name, fetcher in FETCHERS:
        distro = distro_of(fetcher_name)
        candidates = fetcher() or {}
        print(f"{fetcher_name}: {len(candidates)} candidates")
        if not candidates:
            if fetcher_name not in MAY_BE_EMPTY:
                failures.append(f"{fetcher_name}: no candidates")
            continue

        well_formed = []
        for name, url in candidates.items():
            found = problems(distro, name, url)
            failures.extend(f"{fetcher_name}: {problem}" for problem in found)
            if not found:
                well_formed.append(url)

        # ESM-only Ubuntu releases etc. are expected to 404 (download_torrent()
        # counts those as "not found upstream"), so one reachable is enough.
        reachable = next((url for url in well_formed if is_reachable(url)), None)
        if reachable:
            print(f"  reachable: {reachable}")
        elif well_formed:
            failures.append(f"{fetcher_name}: none of its torrent URLs returned 200")
    return failures


def check_tracker():
    candidates = ft.fetch_ubuntu_lts() or {}
    desktop = [url for name, url in candidates.items() if "-desktop-" in name]
    for url in desktop:  # newest first; older ones may be gone (404)
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            break
    else:
        return ["tracker: no current Ubuntu desktop torrent could be downloaded"]

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ubuntu.torrent")
        with open(path, "wb") as f:
            f.write(r.content)
        result = torrent_scrape.scrape_torrent(path)
    print(f"tracker: {url} -> {result}")
    if result is None:
        return ["tracker: no tracker answered the scrape"]
    if not all(isinstance(result.get(key), int) for key in ("seeders", "leechers")):
        return [f"tracker: non-integer seeders/leechers in {result}"]
    return []


def main(argv):
    checks = {"scrapers": check_scrapers, "tracker": check_tracker}
    if len(argv) != 1 or argv[0] not in checks:
        print(__doc__, file=sys.stderr)
        return 2
    failures = checks[argv[0]]()
    for failure in failures:
        print(f"DRIFT: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
