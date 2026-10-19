"""Drives a real transmission-daemon through every Transmission call the
daily run makes, using fetch_torrents' own code paths - for
.github/workflows/drift.yml, run *inside* the image so it also exercises
the image's apk py3-transmission-rpc against its transmission-daemon:

  docker cp scripts/transmission_roundtrip.py <container>:/tmp/
  docker exec -w /usr/local/bin <container> python3 /tmp/transmission_roundtrip.py

Drops a tiny self-made .torrent (one 16-byte file, random name, no
trackers - so nothing is ever downloaded) into /watch, waits for the daemon
to pick it up, reads it the way cleanup does, logs seed ratios over raw RPC
the way the daily run does, then removes it with delete_data=True.
Exits 1 on any failure.
"""

import hashlib
import os
import secrets
import sys
import time

sys.path.insert(0, "/usr/local/bin")

import fetch_torrents as ft
import torrent_scrape

TIMEOUT_SECONDS = 90


def make_torrent(name):
    data = secrets.token_bytes(16)
    info = {
        "name": name,
        "length": len(data),
        "piece length": 16384,
        "pieces": hashlib.sha1(data).digest(),
    }
    return torrent_scrape.bencode({"info": info})


def wait_for(description, predicate):
    deadline = time.time() + TIMEOUT_SECONDS
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(2)
    raise SystemExit(f"FAILED: timed out waiting for {description}")


def main():
    ft.configure_logging("/tmp")
    if not ft.wait_for_transmission_rpc(timeout=TIMEOUT_SECONDS):
        raise SystemExit("FAILED: Transmission RPC never came up")

    config = ft.load_config(os.environ)
    client = ft.make_client_factory(config)()

    name = f"drift-check-{secrets.token_hex(4)}.bin"
    with open(os.path.join(ft.watch_dir, f"{name}.torrent"), "wb") as f:
        f.write(make_torrent(name))

    def added():
        return next((t for t in client.get_torrents() if t.name == name), None)

    torrent = wait_for(f"{name} to be added from {ft.watch_dir}", added)
    # The attributes cleanup and the stagnation history read.
    print(
        f"added: id={torrent.id} name={torrent.name} ratio={float(torrent.ratio)} "
        f"added_date={torrent.added_date.timestamp()}"
    )

    ft.log_seed_ratios_via_http(auth=config.rpc_auth)
    with open(os.path.join("/tmp", ft.RATIO_LOG_FILE_NAME), encoding="utf-8") as f:
        if name not in f.read():
            raise SystemExit("FAILED: torrent missing from the RPC ratio log")

    client.remove_torrent(torrent.id, delete_data=True)
    wait_for(
        f"{name} to be removed",
        lambda: all(t.name != name for t in client.get_torrents()),
    )
    print("Transmission round trip passed.")


if __name__ == "__main__":
    main()
