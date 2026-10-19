"""Characterization tests for fetch_torrents.py's `__main__` block - the
whole daily run - executed via runpy exactly as the container runs it.

Everything external is faked at its boundary: HTTP (requests.get/post),
the Transmission client (the transmission_rpc stub), the RPC port check
(socket.create_connection), disk usage and the clock. Log/state files live
in a per-test temp dir via FETCH_TORRENTS_LOG_DIR.

`watch_dir = "/watch"` is assigned at import time, and runpy executes the
module in a fresh namespace, so it can't be patched like the other module
globals. _redirect_watch_dir() reroutes file access under /watch to a temp
dir instead. (That friction is what tasks/18 removes by extracting run().)

Run with: python -m unittest discover -s tests
"""

import builtins
import contextlib
import io
import logging
import os
import runpy
import shutil
import socket
import sys
import time
import types
import unittest
import unittest.mock
from unittest.mock import MagicMock

if "transmission_rpc" not in sys.modules:
    stub = types.ModuleType("transmission_rpc")
    stub.Client = MagicMock()
    sys.modules["transmission_rpc"] = stub

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "fetch_torrents.py")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import helpers

UBUNTU_META = (
    "Dist: jammy\nName: Jammy Jellyfish\nVersion: 22.04 LTS\nSupported: 0\n\n"
    "Dist: noble\nName: Noble Numbat\nVersion: 24.04 LTS\nSupported: 1\n"
)
UBUNTU = "https://releases.ubuntu.com/noble/"
LUBUNTU = "https://cdimage.ubuntu.com/lubuntu/releases/noble/release/"
XUBUNTU = "https://torrent.ubuntu.com/xubuntu/releases/noble/release/"
ARCH_HTML = (
    "<html><body><table id='release-table'>"
    "<tr><td class='available-yes'></td>"
    "<td><a href='/releng/releases/2026.09.01/torrent/'>t</a></td></tr>"
    "</table></body></html>"
)
ARCH_TORRENT = "https://archlinux.org/releng/releases/2026.09.01/torrent/"


class FakeResponse:
    def __init__(self, status_code=200, text="", content=b"", headers=None, body=None):
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class FakeTransmission:
    """In-memory Transmission: get_torrents() returns what's held,
    remove_torrent() drops it and records the call in `events`."""

    def __init__(self, torrents, events):
        self.torrents = list(torrents)
        self.events = events

    def get_torrents(self):
        self.events.append("get_torrents")
        return list(self.torrents)

    def remove_torrent(self, torrent_id, delete_data=False):
        self.events.append(("remove", torrent_id))
        self.torrents = [t for t in self.torrents if t.id != torrent_id]


def torrent(name, id_, ratio):
    return types.SimpleNamespace(name=name, id=id_, ratio=ratio, added_date=None)


class DailyRunCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.log_dir = helpers.make_temp_dir(self, "daily_run_logs_")
        self.watch_dir = helpers.make_temp_dir(self, "daily_run_watch_")
        self.requested = []
        self.events = []
        self.routes = {}
        self.disk_used_percent = 10
        self.transmission = FakeTransmission([], self.events)

    # -- fakes --------------------------------------------------------------

    def _get(self, url, timeout=None):
        self.requested.append(url)
        route = self.routes.get(url)
        if route is None:
            return FakeResponse(404)
        if isinstance(route, Exception):
            raise route
        return route

    def _post(self, url, json=None, **kwargs):
        if json is None:
            return FakeResponse(headers={"X-Transmission-Session-Id": "sid"})
        torrents = [
            {"name": t.name, "uploadRatio": t.ratio} for t in self.transmission.torrents
        ]
        return FakeResponse(body={"arguments": {"torrents": torrents}})

    def _disk_usage(self, path):
        self.events.append("disk_usage")
        total = 100 * 2**30
        used = total * self.disk_used_percent // 100
        return (total, used, total - used)

    def _redirect_watch_dir(self):
        real_open, real_exists, real_remove = builtins.open, os.path.exists, os.remove

        def redirect(path):
            if isinstance(path, str) and path.replace("\\", "/").startswith("/watch/"):
                return os.path.join(
                    self.watch_dir, path.replace("\\", "/")[len("/watch/") :]
                )
            return path

        return [
            unittest.mock.patch.object(
                builtins, "open", lambda p, *a, **k: real_open(redirect(p), *a, **k)
            ),
            unittest.mock.patch.object(
                os.path, "exists", lambda p: real_exists(redirect(p))
            ),
            unittest.mock.patch.object(
                os, "remove", lambda p: real_remove(redirect(p))
            ),
        ]

    def _write_ratio_log(self, ratios):
        with open(
            os.path.join(self.log_dir, "fetch_torrents_ratios.log"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("2026-08-01 00:00:00,000 INFO: [ratio] RATIOS START\n")
            f.writelines(
                f"2026-08-01 00:00:00,000 INFO: [ratio] {name} → {ratio:.3f}\n"
                for name, ratio in ratios.items()
            )
            f.write("2026-08-01 00:00:00,000 INFO: [ratio] RATIOS END\n")

    def _run(self, **env):
        """Runs the script as __main__; returns its log messages."""
        logger = logging.getLogger("fetch_torrents")
        handlers_before = list(logger.handlers)

        @contextlib.contextmanager
        def connect(*args, **kwargs):
            yield MagicMock()

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                helpers.isolated_env(FETCH_TORRENTS_LOG_DIR=self.log_dir, **env)
            )
            stack.enter_context(unittest.mock.patch("requests.get", self._get))
            stack.enter_context(unittest.mock.patch("requests.post", self._post))
            stack.enter_context(
                unittest.mock.patch.object(
                    sys.modules["transmission_rpc"],
                    "Client",
                    side_effect=lambda **kwargs: self.transmission,
                )
            )
            stack.enter_context(
                unittest.mock.patch.object(socket, "create_connection", connect)
            )
            stack.enter_context(
                unittest.mock.patch.object(shutil, "disk_usage", self._disk_usage)
            )
            stack.enter_context(
                unittest.mock.patch.object(time, "time", return_value=1000.0)
            )
            for patcher in self._redirect_watch_dir():
                stack.enter_context(patcher)
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            logs = stack.enter_context(self.assertLogs(logger, level="DEBUG"))
            try:
                runpy.run_path(SCRIPT, run_name="__main__")
            finally:
                # assertLogs puts the logger's original handlers back on exit,
                # dropping the ones this run added - close their files first.
                for handler in logger.handlers:
                    if isinstance(handler, logging.FileHandler):
                        handler.close()
        self.assertEqual(logger.handlers, handlers_before)
        return [record.getMessage() for record in logs.records]

    def _route_ubuntu(self):
        self.routes.update(
            {
                "https://changelogs.ubuntu.com/meta-release-lts": FakeResponse(
                    text=UBUNTU_META
                ),
                UBUNTU + "ubuntu-24.04-desktop-amd64.iso.torrent": FakeResponse(
                    content=b"d1"
                ),
                # live-server: not routed -> 404
                LUBUNTU + "lubuntu-24.04-desktop-amd64.iso.torrent": FakeResponse(500),
                XUBUNTU
                + "desktop/xubuntu-24.04-desktop-amd64.iso.torrent": FakeResponse(
                    content=b"x1"
                ),
                XUBUNTU
                + "minimal/xubuntu-24.04-minimal-amd64.iso.torrent": FakeResponse(
                    content=b"x2"
                ),
            }
        )
        with open(
            os.path.join(self.watch_dir, "xubuntu-24.04-minimal-amd64.iso.torrent"),
            "wb",
        ) as f:
            f.write(b"already here")

    def _route_arch(self):
        self.routes.update(
            {
                "https://archlinux.org/releng/releases/": FakeResponse(text=ARCH_HTML),
                ARCH_TORRENT: FakeResponse(content=b"a1"),
            }
        )

    # -- tests --------------------------------------------------------------

    def test_counts_each_download_outcome_and_reports_them_in_the_summary(self):
        self._route_ubuntu()

        messages = self._run(FETCH_TORRENTS_DISTROS="ubuntu")

        self.assertEqual(
            sorted(os.listdir(self.watch_dir)),
            [
                "ubuntu-24.04-desktop-amd64.iso.torrent",
                "xubuntu-24.04-desktop-amd64.iso.torrent",
                "xubuntu-24.04-minimal-amd64.iso.torrent",
            ],
        )
        self.assertEqual(
            messages[-1],
            "Run complete in 0.00 seconds. 2 added, 1 existing, "
            "1 not found upstream, 1 failed.",
        )

    def test_distros_not_selected_are_never_fetched(self):
        self._route_ubuntu()
        self._route_arch()

        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertEqual(
            self.requested, ["https://archlinux.org/releng/releases/", ARCH_TORRENT]
        )

    def test_low_previous_ratio_blocks_the_new_release(self):
        self._route_arch()
        self._write_ratio_log({"archlinux-2026.08.01": 0.4})

        messages = self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertNotIn(ARCH_TORRENT, self.requested)
        self.assertIn(
            "Skipping archlinux-2026.09.01 due to low ratio on previous version.",
            messages,
        )
        self.assertEqual(os.listdir(self.watch_dir), [])

    def test_previous_ratio_at_the_floor_allows_the_new_release(self):
        self._route_arch()
        self._write_ratio_log({"archlinux-2026.08.01": 1.0})

        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertEqual(os.listdir(self.watch_dir), ["archlinux-2026.09.01.torrent"])

    def test_a_failing_distro_does_not_stop_the_others(self):
        self._route_arch()
        self.routes["https://changelogs.ubuntu.com/meta-release-lts"] = ConnectionError(
            "down"
        )

        messages = self._run(FETCH_TORRENTS_DISTROS="ubuntu,arch")

        self.assertEqual(os.listdir(self.watch_dir), ["archlinux-2026.09.01.torrent"])
        self.assertEqual(
            messages[-1],
            "Run complete in 0.00 seconds. 1 added, 0 existing, "
            "0 not found upstream, 1 failed.",
        )

    def test_keep_only_latest_selects_the_old_version_cleanup(self):
        self.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 2.0),
        ]

        self._run(
            FETCH_TORRENTS_DISTROS="arch", CLEANUP_KEEP_ONLY_LATEST_VERSION="true"
        )

        self.assertEqual(
            [t.name for t in self.transmission.torrents],
            ["ubuntu-24.04-desktop-amd64.iso"],
        )

    def test_default_cleanup_is_stagnation_based(self):
        # No ratio history yet, so the stagnation cleanup can't judge the old
        # version and keeps it - unlike keep-only-latest, which removes it.
        self.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 2.0),
        ]

        self._run(FETCH_TORRENTS_DISTROS="arch")

        self.assertEqual(len(self.transmission.torrents), 2)
        self.assertTrue(
            os.path.exists(
                os.path.join(self.log_dir, "fetch_torrents_ratio_history.json")
            )
        )

    def test_disk_usage_limit_runs_after_cleanup(self):
        self.transmission.torrents = [
            torrent("ubuntu-24.04-desktop-amd64.iso", 1, 2.0),
            torrent("ubuntu-23.10-desktop-amd64.iso", 2, 0.1),
        ]
        self.disk_used_percent = 99

        self._run(
            FETCH_TORRENTS_DISTROS="arch", CLEANUP_DISK_USAGE_THRESHOLD_PERCENT="95"
        )

        cleanup_listing = self.events.index("get_torrents")
        first_disk_check = self.events.index("disk_usage")
        self.assertLess(cleanup_listing, first_disk_check)
        self.assertIn(("remove", 2), self.events[first_disk_check:])

    def test_disk_usage_limit_error_is_logged_not_raised(self):
        messages = self._run(
            FETCH_TORRENTS_DISTROS="arch", CLEANUP_DISK_USAGE_THRESHOLD_PERCENT="lots"
        )

        self.assertTrue(
            any(m.startswith("Could not enforce disk usage limit:") for m in messages)
        )
        self.assertTrue(messages[-1].startswith("Run complete in"))

    def test_seed_ratios_are_logged_for_the_next_run(self):
        self.transmission.torrents = [torrent("archlinux-2026.08.01", 1, 0.664)]

        self._run(FETCH_TORRENTS_DISTROS="arch")

        with open(
            os.path.join(self.log_dir, "fetch_torrents_ratios.log"), encoding="utf-8"
        ) as f:
            text = f.read()
        self.assertIn("[ratio] archlinux-2026.08.01", text)
        self.assertIn("→ 0.664", text)


if __name__ == "__main__":
    unittest.main()
