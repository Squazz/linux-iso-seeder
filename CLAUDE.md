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

`fetch_torrents.py` is written to run inside the container: it imports
`transmission_rpc` (an apk-only package, not pip-installable) and opens log
files under `/logs` at import time. `tests/test_fetch_torrents.py` stubs
`transmission_rpc` via `sys.modules` and points `FETCH_TORRENTS_LOG_DIR` at a
temp directory before importing the module, so tests run without a container
or a live Transmission daemon. Follow that pattern for any new test file that
needs to import `fetch_torrents`.

Business logic that needs to be unit-testable should be kept as pure
functions (taking plain data in, returning plain data out) separate from
functions that perform I/O (RPC calls, network requests, file writes) — see
`plan_cleanup()` vs. `cleanup_old_versions()` for the pattern.

Test-only dependencies (currently just `requests` and `beautifulsoup4`,
needed to import the module — `unittest` itself is stdlib) live in
`requirements-test.txt`, separate from the apk packages the container
actually runs with.
