# linux-iso-seeder

## Testing requirements for agents

This repo has a test suite in [tests/](tests/) (stdlib `unittest`, no pytest).

**Before writing an implementation, write the test first.** For any bug fix
or behavior change:
1. Write (or extend) a test in `tests/` that encodes the expected behavior.
   Run it and confirm it fails for the reason you expect (i.e. it actually
   exercises the bug/gap, not something unrelated).
2. Implement the change.
3. Run the test again and confirm it passes.

This applies to logic changes in `fetch_torrents.py` (or any other Python
module later added). It does not apply to pure docs/README edits or CI/config
changes that have no testable behavior.

**A task is not complete until the full test suite passes.** Before reporting
a task as done, run:

```
python -m unittest discover -s tests -v
```

(On Windows dev machines without a `python` alias, use `py -m unittest
discover -s tests -v`.) If a test fails, fix it or the code — don't report
completion with a known-failing suite, and don't delete/weaken a test just to
make it pass unless the test itself was wrong.

CI runs this same command on every push and PR (`.github/workflows/docker-image.yml`,
`test` job) and gates the Docker image build/push on it passing.

## Why the test setup looks the way it does

`fetch_torrents.py` is written to run inside the container, which installs
`transmission_rpc` from Alpine's `py3-transmission-rpc`. Tests use the same
version from PyPI (`transmission-rpc`, pinned in `requirements-test.txt`;
bump the pin when `alpine:latest` moves), so they run without a container
or a live Transmission daemon. Never talk to a real `Client` in a test: use
`tests/helpers.py` `FakeTransmission` and `FakeTorrent`, which are checked
against the pinned library's `Client` signatures and `Torrent` fields (see
`tests/test_helpers.py`), so they can't drift from it.

Importing the module opens no files: log handlers are only attached by
`configure_logging()`, which the `__main__` block calls. Tests that need it
undo it with `addCleanup(ft.reset_logging)` (see `configure_logging_for_test()`).
The daily run itself is `run(config, client_factory=..., today=...)` with
its I/O (Transmission client, clock, disk usage) injected, so it is tested
directly with fakes from `tests/helpers.py` (`FakeTransmission`, `FakeDisk`);
`tests/test_daily_run.py` keeps one runpy test for the `__main__` wiring.
Which distros have old-release discovery is injected the same way
(`run(old_release_discovery=)`, `check_old_releases_for_demand(discovery=)`),
so tests pass a mapping instead of patching `OLD_RELEASE_DISCOVERY`.
Env vars are read once by `load_config(env)`. Transmission's HTTP RPC (the
ratio log) is faked with `helpers.FakeTransmissionRpc` as `requests.post`:
409 plus session id first, like the daemon, recording each call's auth
(its `error_status` fails every request past that handshake).
The file locations are module globals read at import
(`FETCH_TORRENTS_LOG_DIR`, `FETCH_TORRENTS_WATCH_DIR`); in-process tests
point them at temp dirs with `helpers.use_watch_dir(self)` and
`helpers.use_state_files(self)`, which return the paths, instead of
patching them by hand.

Every test module starts with `import helpers` (which also puts the repo
root on `sys.path`) and a `setUpModule()` calling `helpers.isolate_module()`:
that scrubs the developer's own `CLEANUP_*`, `FETCH_TORRENTS_*` etc. so they
can't change test outcomes, and refuses any real network connection, UDP
datagram or DNS lookup. HTTP is faked with `helpers.fake_response()` (a real
`requests.Response`), served as `requests.get` by `helpers.FakeHttp` (a
url -> response routes dict, 404 for anything else, recording each
request) or its subclasses `helpers.RecordedPages` (pages captured by
`scripts/record_fixtures.py`) and `helpers.OldReleaseTracker` (which also
fakes the tracker scrape for the old-release check).
`fetch_torrents` tests are split by concern: `test_ratio_gate.py`,
`test_fetchers.py`, `test_scrapers.py`, `test_cleanup.py`,
`test_persistence.py`, `test_logging.py`, `test_old_release_demand.py`,
`test_config.py` (`load_config()`, `parse_bool()`, `make_client_factory()`,
the run summary) and `test_daily_run.py` (`run()`, `__main__`).
Tests for the `scripts/` the drift job runs (`test_live_check.py`,
`test_record_fixtures.py`, `test_transmission_roundtrip.py`) import them
with `helpers.load_script(name)`, so `scripts/` never lands on `sys.path`;
their network, output directory and clock are injected (polling loops take
`clock=`/`sleep=`, faked with `helpers.FakeClock`).
`test_helpers.py` tests the doubles in `tests/helpers.py` themselves;
`test_repo_hygiene.py` checks the repository itself (shebang files are
executable in git).

Business logic that needs to be unit-testable should be kept as pure
functions (taking plain data in, returning plain data out) separate from
functions that perform I/O (RPC calls, network requests, file writes) — see
`plan_cleanup()` vs. `cleanup_old_versions()` for the pattern.

Test-only dependencies (`requests`, `beautifulsoup4` and `transmission-rpc`,
needed to import the modules — `unittest` itself is stdlib) live in
`requirements-test.txt`, separate from the apk packages the container
actually runs with.
