"""Shared test helpers.

Not a test module itself (doesn't match the test*.py discovery pattern);
`unittest discover -s tests` puts tests/ on sys.path, so test modules import
this as `import helpers`.
"""

import os
import shutil
import tempfile
import unittest.mock

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


class FakeTransmission:
    """In-memory stand-in for transmission_rpc.Client: get_torrents()
    returns what it currently holds, remove_torrent() drops that torrent.
    `calls` records both, in order, for tests that care about sequencing."""

    def __init__(self, torrents=()):
        self.torrents = list(torrents)
        self.calls = []

    def get_torrents(self):
        self.calls.append("get_torrents")
        return list(self.torrents)

    def remove_torrent(self, ids, delete_data=False):
        self.calls.append(("remove_torrent", ids, delete_data))
        self.torrents = [t for t in self.torrents if t.id != ids]

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
