"""Shared test helpers.

Not a test module itself (doesn't match the test*.py discovery pattern);
`unittest discover -s tests` puts tests/ on sys.path, so test modules import
this as `import helpers`. Importing it also puts the repo root on sys.path,
so `import fetch_torrents` etc. work after it.

A typical test module:

    import helpers

    import fetch_torrents as ft


    def setUpModule():
        helpers.isolate_module()
"""

import errno
import glob
import importlib.util
import inspect
import json
import os
import shutil
import socket
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import date
from urllib.parse import urldefrag

import requests
import transmission_rpc
import transmission_rpc.constants

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Env vars production code reads at call time. A developer who happens to
# have any of these exported (e.g. SKIP_RATIO_CHECK=true) must not be able
# to flip test outcomes, so isolated_env() removes them unless a test sets
# them explicitly.
_ISOLATED_PREFIXES = (
    "SKIP_RATIO_CHECK",
    "CLEANUP_",
    "TRANSMISSION_",
    "FETCH_TORRENTS_",
)
# Where fetch_torrents' state and log files go; a test that sets it (e.g.
# for a subprocess or runpy run) must not have it scrubbed.
_PRESERVED = frozenset({"FETCH_TORRENTS_LOG_DIR"})


def scrubbed_environ(**overrides):
    """A copy of os.environ without the isolated keys, plus overrides."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key in _PRESERVED or not key.startswith(_ISOLATED_PREFIXES)
    }
    env.update(overrides)
    return env


def isolated_env(**overrides):
    """patch.dict replacing os.environ with scrubbed_environ(**overrides).

    Usable as a context manager, or started/stopped manually (see
    isolate_module()). The scrubbed copy is taken when this is called, not
    when it is entered, so call it at the point of use."""
    return unittest.mock.patch.dict(
        os.environ, scrubbed_environ(**overrides), clear=True
    )


def isolate_module():
    """The baseline for a test module (call from setUpModule): the
    developer's exported SKIP_RATIO_CHECK/CLEANUP_*/TRANSMISSION_*/
    FETCH_TORRENTS_* can't leak in (including into subprocesses, which copy
    os.environ), and no real network connection can be opened."""
    patcher = isolated_env()
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)
    unittest.addModuleCleanup(block_network())


def fixed_date(today):
    """A drop-in for fetch_torrents' `date` whose today() is pinned."""

    class FixedDate(date):
        @classmethod
        def today(cls):
            return today

    return FixedDate


def names_of(torrents):
    return sorted(t.name for t in torrents)


def removed(name, ratio=None, *, on="2026-01-01"):
    """A removed-history entry for `name`, as record_removal() writes it
    ({name: {...}}; merge several with {**a, **b}). Only the ratio matters
    to the ratio gate, and only the date to the old-release log line; no
    ratio makes a legacy entry from before ratios were recorded."""
    entry = {"removed_date": on, "reason": "stagnant"}
    if ratio is not None:
        entry["ratio"] = ratio
    return {name: entry}


def load_script(name):
    """Imports scripts/<name>.py from its path, so scripts/ itself never
    lands on sys.path for other tests. sys.path is restored afterwards: a
    script run inside the image may add the image's own directories."""
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(REPO_ROOT, "scripts", f"{name}.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    saved_path = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved_path
    return module


class FakeClock:
    """A monotonic clock that only moves when `sleep` is called, recording
    each sleep."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_temp_dir(testcase, prefix):
    """mkdtemp() that is removed again when the test finishes."""
    path = tempfile.mkdtemp(prefix=prefix)
    testcase.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path


def FakeTorrent(name, id_, ratio=0.0, added_date=0):
    """A real transmission_rpc.Torrent holding the RPC fields production
    code reads (via .name, .id, .ratio, .added_date), so a test can't rely
    on an attribute the library doesn't have. `added_date` is a Unix time."""
    return transmission_rpc.Torrent(
        fields={
            "id": id_,
            "name": name,
            "uploadRatio": ratio,
            "addedDate": added_date,
        }
    )


# Captured at import: a test may patch transmission_rpc.Client itself (e.g.
# to hand a FakeTransmission to a runpy'd script).
_REAL_CLIENT = transmission_rpc.Client


class DuckTorrent:
    """A torrent-shaped object a real transmission_rpc.Torrent can't be -
    ratio None, or added_date None/a float/a datetime - only for exercising
    the defensive getattr()/`or 0.0` branches in production code."""

    def __init__(self, name, id_, ratio=0.0, added_date=None):
        self.name = name
        self.id = id_
        self.ratio = ratio
        self.added_date = added_date

    def __repr__(self):
        return f"DuckTorrent({self.name!r}, ratio={self.ratio})"


def _bind_to_client(method_name, args, kwargs):
    """The arguments of a call to transmission_rpc.Client.<method_name>, by
    parameter name with defaults filled in. Raises TypeError for a call the
    real (pinned) Client wouldn't accept."""
    signature = inspect.signature(getattr(_REAL_CLIENT, method_name))
    bound = signature.bind(None, *args, **kwargs)
    bound.apply_defaults()
    return bound.arguments


class FakeTransmission:
    """In-memory stand-in for transmission_rpc.Client: get_torrents()
    returns what it currently holds, remove_torrent() drops that torrent.
    `calls` records both, in order, for tests that care about sequencing.
    A torrent removed without delete_data (the real Client's default) moves
    to `data_left_on_disk`, since Transmission leaves its files behind.

    Every call is bound against the real Client's signature first, so an
    argument the pinned library wouldn't accept raises TypeError here too
    (see tests/test_helpers.py)."""

    def __init__(self, torrents=()):
        self.torrents = list(torrents)
        self.data_left_on_disk = []
        self.calls = []

    def get_torrents(self, *args, **kwargs):
        _bind_to_client("get_torrents", args, kwargs)
        self.calls.append("get_torrents")
        return list(self.torrents)

    def remove_torrent(self, *args, **kwargs):
        call = _bind_to_client("remove_torrent", args, kwargs)
        self.calls.append(("remove_torrent", call["ids"], call["delete_data"]))
        if not call["delete_data"]:
            self.data_left_on_disk += [t for t in self.torrents if t.id == call["ids"]]
        self.torrents = [t for t in self.torrents if t.id != call["ids"]]

    @property
    def names(self):
        return sorted(t.name for t in self.torrents)

    @property
    def removals(self):
        """The remove_torrent calls made so far, as (ids, delete_data)."""
        return [call[1:] for call in self.calls if call != "get_torrents"]


class FakeDisk:
    """shutil.disk_usage() stand-in whose used space is `base_used` plus the
    size of every torrent whose data is still on disk - those `transmission`
    holds, plus any it removed without delete_data - so removals free space
    only the way they would for real."""

    def __init__(self, transmission, total, sizes, base_used=0):
        self.transmission = transmission
        self.total = total
        self.sizes = sizes
        self.base_used = base_used
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)
        on_disk = self.transmission.torrents + self.transmission.data_left_on_disk
        used = self.base_used + sum(self.sizes.get(t.id, 0) for t in on_disk)
        return (self.total, used, self.total - used)


class FakeTransmissionRpc:
    """requests.post stand-in for transmission-daemon's HTTP RPC, as strict
    as the daemon: a request without the session id it handed out is
    refused with a 409 carrying that id. A torrent-get with it records its
    auth in `auths` and lists `transmission`'s torrents, with just the
    requested fields. A method or field the pinned transmission_rpc doesn't
    know raises ValueError. `calls` records every post, as mock.call()s.
    Set `error_status` (e.g. 500) to fail every request past the handshake
    with that status. Set `credentials` to a (user, password) tuple to
    require them like a daemon with rpc-authentication-required: a request
    with any other `auth` gets a 401 without the session id, checked first,
    as transmission-daemon 4.0.6's rpc-server.cc does."""

    URL = "http://localhost:9091/transmission/rpc"
    SESSION_ID = "sid"

    def __init__(self, transmission):
        self.transmission = transmission
        self.calls = []
        self.auths = []
        self.error_status = None
        self.credentials = None

    def post(self, url, **kwargs):
        self.calls.append(unittest.mock.call(url, **kwargs))
        if url != self.URL:
            return fake_response(b"not found", status=404, url=url)
        if self.credentials is not None and kwargs.get("auth") != self.credentials:
            return fake_response(
                b"unauthorized",
                status=401,
                url=url,
                headers={"WWW-Authenticate": 'Basic realm="Transmission"'},
            )
        headers = kwargs.get("headers") or {}
        if headers.get("X-Transmission-Session-Id") != self.SESSION_ID:
            return fake_response(
                status=409,
                url=url,
                headers={"X-Transmission-Session-Id": self.SESSION_ID},
            )
        if self.error_status is not None:
            return fake_response(b"error", status=self.error_status, url=url)
        payload = kwargs.get("json") or {}
        method = payload.get("method")
        RpcMethod = transmission_rpc.constants.RpcMethod
        if method not in {m.value for m in RpcMethod}:
            raise ValueError(f"the pinned transmission_rpc has no method {method!r}")
        if method != RpcMethod.TorrentGet.value:
            raise ValueError(f"method {method!r}: only torrent-get is faked")
        fields = payload["arguments"]["fields"]
        unknown = set(fields) - set(transmission_rpc.constants.TORRENT_GET_ARGS)
        if unknown:
            raise ValueError(
                f"torrent-get fields the pinned transmission_rpc lacks: {unknown}"
            )
        self.auths.append(kwargs.get("auth"))
        torrents = [
            {field: t.fields[field] for field in fields}
            for t in self.transmission.torrents
        ]
        return fake_response(
            json.dumps({"arguments": {"torrents": torrents}, "result": "success"}),
            url=url,
        )


def use_watch_dir(testcase):
    """Points fetch_torrents.watch_dir at a fresh temp dir for the rest of
    `testcase`; returns that dir."""
    import fetch_torrents

    path = make_temp_dir(testcase, "fetch_torrents_test_watch_")
    _patch_for_test(testcase, fetch_torrents, "watch_dir", path)
    return path


# fetch_torrents' state file globals and the file each is named after.
STATE_FILES = {
    "ratio_log_file": "fetch_torrents_ratios.log",
    "ratio_history_file": "fetch_torrents_ratio_history.json",
    "removed_history_file": "fetch_torrents_removed_history.json",
    "old_release_check_state_file": "fetch_torrents_old_release_check_state.json",
}


def use_state_files(testcase):
    """Points every fetch_torrents state file global (STATE_FILES) at a
    not-yet-existing file in a fresh temp dir for the rest of `testcase`.
    Returns a namespace holding `dir` and each patched path, by the
    global's name (e.g. `.removed_history_file`)."""
    import fetch_torrents

    state = types.SimpleNamespace(
        dir=make_temp_dir(testcase, "fetch_torrents_test_state_")
    )
    for attr, filename in STATE_FILES.items():
        path = os.path.join(state.dir, filename)
        setattr(state, attr, path)
        _patch_for_test(testcase, fetch_torrents, attr, path)
    return state


def _patch_for_test(testcase, target, attr, value):
    patcher = unittest.mock.patch.object(target, attr, value)
    patcher.start()
    testcase.addCleanup(patcher.stop)


def disk_full_open(module, only=None):
    """Patch `module`'s own `open` so a binary write keeps half its bytes and
    then fails with ENOSPC, as when the disk fills mid-write. Scoped to the
    module (not builtins) so logging's own file writes are unaffected. With
    `only`, just writes to a path containing that text fail."""
    real_open = open

    class HalfWritingFile:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()
            return False

        def write(self, data):
            self.f.write(data[: len(data) // 2])
            raise OSError(errno.ENOSPC, "No space left on device")

    def fake_open(path, mode="r", *args, **kwargs):
        f = real_open(path, mode, *args, **kwargs)
        failing = "wb" in mode and (only is None or only in os.fspath(path))
        return HalfWritingFile(f) if failing else f

    return unittest.mock.patch.object(module, "open", fake_open, create=True)


PAGES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "pages"
)


def fake_response(body=b"", status=200, url="", headers=None):
    """A real requests.Response with the given body (str or bytes), so
    .text, .content, .json(), raise_for_status() and `with` behave as for
    real."""
    response = requests.Response()
    response.status_code = status
    response.reason = {200: "OK", 404: "Not Found", 500: "Internal Server Error"}.get(
        status, ""
    )
    response._content = body.encode("utf-8") if isinstance(body, str) else body
    # Already read, so close() (and so `with response:`) needn't touch .raw.
    response._content_consumed = True
    response.encoding = "utf-8"
    response.url = url
    response.headers.update(headers or {})
    return response


class FakeHttp:
    """A requests.get stand-in answering from `routes`: url -> response, or
    an exception to raise. Any other URL is recorded in `unexpected` and
    answered with a 404. Records every request's (url, timeout) in
    `requests`; `requested` lists just the URLs. URLs are matched and
    recorded as they'd be sent: with any `params=` merged into the query,
    and without the fragment, which never reaches the server."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.requests = []
        self.unexpected = []

    @property
    def requested(self):
        return [url for url, _timeout in self.requests]

    def _answer(self, url):
        """The routed answer for `url`, or None for a 404."""
        return self.routes.get(url)

    def get(self, url, params=None, timeout=None, **kwargs):
        url = urldefrag(url).url
        if params:
            url = requests.Request("GET", url, params=params).prepare().url
        self.requests.append((url, timeout))
        answer = self._answer(url)
        if answer is None:
            self.unexpected.append(url)
            return fake_response(b"not found", status=404, url=url)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class RecordedPages(FakeHttp):
    """A FakeHttp serving tests/fixtures/pages (captured by
    scripts/record_fixtures.py), keyed by the URL in each .meta.json.

    `overrides` are routes that take precedence over the recordings. Any
    other URL lands in `unexpected` (and gets a 404), so a test can assert
    the scraper asked for nothing it wasn't expected to."""

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.pages = {}
        for meta_path in glob.glob(os.path.join(PAGES_DIR, "*", "*.meta.json")):
            with open(meta_path, encoding="utf-8") as f:
                url = json.load(f)["url"]
            stem = meta_path[: -len(".meta.json")]
            (body_path,) = (
                path for path in glob.glob(stem + ".*") if path != meta_path
            )
            self.pages[url] = body_path

    def _answer(self, url):
        if url in self.routes:
            return self.routes[url]
        if url in self.pages:
            with open(self.pages[url], "rb") as f:
                return fake_response(f.read(), url=url)
        return None


def swarm(leechers, seeders):
    """A tracker scrape result, as torrent_scrape.scrape_torrent() returns
    it."""
    return {
        "tracker": "udp://tracker.example:6969",
        "seeders": seeders,
        "leechers": leechers,
        "completed": 0,
    }


class OldReleaseTracker(FakeHttp):
    """Plays both network boundaries of the old-release check: requests.get
    for the candidate's .torrent (FakeHttp) and torrent_scrape.scrape_torrent,
    which answers from `swarms` (torrent bytes -> scrape result, or an
    exception to raise) by reading the file it was handed - so the real
    evaluate_old_release_demand() runs in between. Records every scrape's
    (bytes, path, timeout) in `scrapes`."""

    def __init__(self):
        super().__init__()
        self.swarms = {}
        self.scrapes = []

    def candidate(self, name, swarm):
        """Serves name's .torrent and gives it `swarm` (a scrape result,
        None for "no tracker answered", or an exception); returns its url."""
        url = f"https://cdimage.example/{name}.torrent"
        body = f"{name} metadata".encode()
        self.routes[url] = fake_response(body, url=url)
        self.swarms[body] = swarm
        return url

    def scrape_torrent(self, path, timeout=15):
        with open(path, "rb") as f:
            body = f.read()
        self.scrapes.append((body, path, timeout))
        swarm = self.swarms[body]
        if isinstance(swarm, Exception):
            raise swarm
        return swarm

    def patch(self, testcase):
        """Makes this tracker fetch_torrents' requests.get and
        torrent_scrape.scrape_torrent for the rest of `testcase`."""
        import fetch_torrents

        _patch_for_test(testcase, fetch_torrents.requests, "get", self.get)
        # double-waiver: B1 — opens UDP/HTTP tracker sockets
        _patch_for_test(
            testcase,
            fetch_torrents.torrent_scrape,
            "scrape_torrent",
            self.scrape_torrent,
        )


# Every image fetch_kali_latest()/fetch_kali_old_versions() offer for a
# release, written out by hand (not taken from fetch_torrents) so tests can
# check the scrapers against it.
KALI_SUFFIXES = (
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-amd64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-netinst-amd64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-everything-amd64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-arm64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-netinst-arm64.iso",
    "cdimage.kali.org/kali-{v}/kali-linux-{v}-installer-purple-amd64.iso",
    "kali.download/arm-images/kali-{v}/kali-linux-{v}-raspberry-pi-armhf.img.xz",
    "kali.download/arm-images/kali-{v}/kali-linux-{v}-raspberry-pi-zero-2-w-armhf.img.xz",
    "kali.download/arm-images/kali-{v}/kali-linux-{v}-raspberry-pi-zero-w-armel.img.xz",
    "kali.download/cloud-images/kali-{v}/kali-linux-{v}-cloud-genericcloud-amd64.tar.xz",
    "kali.download/cloud-images/kali-{v}/kali-linux-{v}-cloud-genericcloud-arm64.tar.xz",
)


def kali_candidates(*versions):
    """{name: torrent URL} for every Kali image of each version, in order."""
    return {
        os.path.basename(suffix.format(v=version)): (
            "https://" + suffix.format(v=version) + ".torrent"
        )
        for version in versions
        for suffix in KALI_SUFFIXES
    }


class FakeUdpSocket:
    """socket.socket stand-in for a UDP tracker client. Records each
    datagram sent, by sendto() or connect()+send() alike, as (payload, addr)
    in `sent`. recvfrom()/recv() serve `replies` in order: bytes, an
    exception to raise, or a function of the last payload sent (so a reply
    can echo its transaction id). `timeout` is what settimeout() was given,
    and `closed` is set by close() or by leaving a `with` block. patch()
    serves it for every UDP socket opened during a test."""

    def __init__(self, replies=()):
        self.replies = list(replies)
        self.sent = []
        self.timeout = None
        self.closed = False
        self._peer = None

    def patch(self, testcase):
        def open_socket(family=socket.AF_INET, type=socket.SOCK_DGRAM, *args):
            assert type == socket.SOCK_DGRAM, "FakeUdpSocket only fakes UDP"
            return self

        _patch_for_test(testcase, socket, "socket", open_socket)

    def _check_open(self):
        if self.closed:
            raise OSError("Bad file descriptor")

    def settimeout(self, value):
        self.timeout = value

    def gettimeout(self):
        return self.timeout

    def connect(self, address):
        self._check_open()
        self._peer = address

    def sendto(self, data, address):
        self._check_open()
        self.sent.append((bytes(data), address))
        return len(data)

    def send(self, data):
        return self.sendto(data, self._peer)

    def recvfrom(self, bufsize):
        self._check_open()
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(self.sent[-1][0])
        return reply, self.sent[-1][1]

    def recv(self, bufsize):
        return self.recvfrom(bufsize)[0]

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


def _refuse_network(*args, **kwargs):
    raise RuntimeError("tests must not open network connections")


def block_network():
    """Makes every real socket connection, UDP datagram and DNS lookup fail
    for the rest of the module (call from setUpModule; returns the function
    that undoes it, for unittest.addModuleCleanup). Mocked sockets are
    unaffected, and a test that patches getaddrinfo itself replaces the
    guard for that test. socket.create_connection() needs no patch of its
    own: it resolves through getaddrinfo and then calls connect."""
    patchers = [
        unittest.mock.patch.object(socket.socket, "connect", _refuse_network),
        unittest.mock.patch.object(socket.socket, "connect_ex", _refuse_network),
        unittest.mock.patch.object(socket.socket, "sendto", _refuse_network),
        unittest.mock.patch.object(socket, "getaddrinfo", _refuse_network),
        unittest.mock.patch.object(socket, "gethostbyname", _refuse_network),
    ]
    for patcher in patchers:
        patcher.start()

    def stop():
        for patcher in reversed(patchers):
            patcher.stop()

    return stop
