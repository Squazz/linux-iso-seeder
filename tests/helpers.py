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
# Read at import time to choose where fetch_torrents writes its logs; the
# test modules set it to a temp dir before importing, so it must survive.
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
