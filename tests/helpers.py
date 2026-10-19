"""Shared test helpers.

Not a test module itself (doesn't match the test*.py discovery pattern);
`unittest discover -s tests` puts tests/ on sys.path, so test modules import
this as `import helpers`.
"""

import glob
import inspect
import json
import os
import shutil
import socket
import tempfile
import unittest.mock
from urllib.parse import urldefrag

import requests
import transmission_rpc

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
    use_isolated_env()). The scrubbed copy is taken when this is called, not
    when it is entered, so call it at the point of use."""
    return unittest.mock.patch.dict(
        os.environ, scrubbed_environ(**overrides), clear=True
    )


def use_isolated_env(testcase, **overrides):
    """Apply isolated_env() for the rest of a test (call from setUp)."""
    patcher = isolated_env(**overrides)
    patcher.start()
    testcase.addCleanup(patcher.stop)


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

    Every call is bound against the real Client's signature first, so an
    argument the pinned library wouldn't accept raises TypeError here too
    (see tests/test_transmission_double.py)."""

    def __init__(self, torrents=()):
        self.torrents = list(torrents)
        self.calls = []

    def get_torrents(self, *args, **kwargs):
        _bind_to_client("get_torrents", args, kwargs)
        self.calls.append("get_torrents")
        return list(self.torrents)

    def remove_torrent(self, *args, **kwargs):
        call = _bind_to_client("remove_torrent", args, kwargs)
        self.calls.append(("remove_torrent", call["ids"], call["delete_data"]))
        self.torrents = [t for t in self.torrents if t.id != call["ids"]]

    @property
    def names(self):
        return sorted(t.name for t in self.torrents)


class FakeDisk:
    """shutil.disk_usage() stand-in whose used space is `base_used` plus the
    size of every torrent `transmission` still holds - so removals free
    space the way they would for real."""

    def __init__(self, transmission, total, sizes, base_used=0):
        self.transmission = transmission
        self.total = total
        self.sizes = sizes
        self.base_used = base_used
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)
        used = self.base_used + sum(
            self.sizes.get(t.id, 0) for t in self.transmission.torrents
        )
        return (self.total, used, self.total - used)


PAGES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "pages"
)


def fake_response(body=b"", status=200, url="", headers=None):
    """A real requests.Response with the given body (str or bytes), so
    .text, .content, .json() and raise_for_status() behave as for real."""
    response = requests.Response()
    response.status_code = status
    response.reason = {200: "OK", 404: "Not Found", 500: "Internal Server Error"}.get(
        status, ""
    )
    response._content = body.encode("utf-8") if isinstance(body, str) else body
    response.encoding = "utf-8"
    response.url = url
    response.headers.update(headers or {})
    return response


class RecordedPages:
    """A requests.get stand-in serving tests/fixtures/pages (captured by
    scripts/record_fixtures.py), keyed by the URL in each .meta.json.

    `overrides` maps a URL to a response, or to an exception to raise.
    Any other URL is recorded in `unexpected` and answered with a 404, so a
    test can assert the scraper asked for nothing it wasn't expected to."""

    def __init__(self, overrides=None):
        self.pages = {}
        for meta_path in glob.glob(os.path.join(PAGES_DIR, "*", "*.meta.json")):
            with open(meta_path, encoding="utf-8") as f:
                url = json.load(f)["url"]
            stem = meta_path[: -len(".meta.json")]
            (body_path,) = (
                path for path in glob.glob(stem + ".*") if path != meta_path
            )
            self.pages[url] = body_path
        self.overrides = dict(overrides or {})
        self.requested = []
        self.unexpected = []

    def get(self, url, timeout=None, **kwargs):
        # A fragment never reaches the server, so match without it.
        url = urldefrag(url).url
        self.requested.append(url)
        if url in self.overrides:
            override = self.overrides[url]
            if isinstance(override, BaseException):
                raise override
            return override
        if url in self.pages:
            with open(self.pages[url], "rb") as f:
                return fake_response(f.read(), url=url)
        self.unexpected.append(url)
        return fake_response(b"not recorded", status=404, url=url)


def _refuse_network(*args, **kwargs):
    raise RuntimeError("tests must not open network connections")


def block_network():
    """Makes every real socket connection fail for the rest of the module
    (call from setUpModule; returns the function that undoes it, for
    unittest.addModuleCleanup). Mocked sockets are unaffected."""
    patchers = [
        unittest.mock.patch.object(socket.socket, "connect", _refuse_network),
        unittest.mock.patch.object(socket.socket, "connect_ex", _refuse_network),
    ]
    for patcher in patchers:
        patcher.start()

    def stop():
        for patcher in reversed(patchers):
            patcher.stop()

    return stop
