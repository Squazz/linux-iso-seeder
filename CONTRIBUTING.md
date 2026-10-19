# Contributing

1. Fork the repository
2. Create a new branch (`feature/your-feature`)
3. Commit your changes with clear messages
4. Push to your fork and submit a pull request

**Ideas for contribution:**

- Adding more distros or mirrors
- Implementing Prometheus metrics endpoint
- Slack or Matrix notification integration
- Disk cleanup or retention policies

## Maintenance notes

When making changes to the fetch logic or features:

- Update `README.md` to reflect new functionality
- Test the script in a controlled environment before deployment
- Ensure log parsing works correctly for ratio checks
- Verify regex patterns match all intended torrent names (e.g., Ubuntu variants)
- Ratio checking is per ISO type (e.g., `installer-amd64`) rather than per distro

## Testing the image

CI checks the built image before anything is pushed. To run the same checks
locally (Docker required):

```sh
docker build --target test .                 # unit suite on the image's apk packages
docker build -t linux-iso-seeder:smoke .
sh scripts/smoke_test.sh linux-iso-seeder:smoke
```

The smoke test starts the image with `--network none`, both as root and
with `RUN_AS_NON_ROOT=true`, and checks that `configure_transmission.py`
applied its overrides, that `transmission-daemon` is running, that the
daily `fetch_torrents.py` run started, and that every module imports.

When `alpine:latest` moves to new `python3` or `py3-*` versions, bump the
pins in `requirements-test.txt` and CI's `python-version` in
`.github/workflows/docker-image.yml` to match.

The `test` job also lints the shell scripts and the Dockerfile with pinned
images. To run them locally:

```sh
docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:v0.11.0 entrypoint.sh scripts/*.sh
docker run --rm -i hadolint/hadolint:v2.15.1 < Dockerfile
```

## Upstream drift

The merge check never touches the network. `.github/workflows/drift.yml`
runs weekly (or by hand from the Actions tab) against the live distro sites,
a live tracker, a real `transmission-daemon` and the published image, and
opens or comments on an issue labelled `drift` when something has moved. To
fix scraper drift, re-record the pages and update the expected results in
`tests/test_scrapers.py` to the new snapshot:

```sh
python scripts/live_check.py scrapers     # what the weekly job checks
python scripts/record_fixtures.py [distro ...]
git diff tests/fixtures/pages
```

## Mutation testing

Mutation testing checks that the tests actually pin behavior, not just
execute lines. It uses mutmut 2.x (pinned in `requirements-dev.txt`), configured
under `[tool.mutmut]` in `pyproject.toml`:

```
pip install -r requirements-dev.txt
mutmut run            # mutate all three modules, run the suite per mutant
mutmut results        # list surviving mutants
mutmut show <id>      # show one mutant's diff
```

mutmut edits the source files in place while it runs, so run it on a clean
working tree (or a copy of the repo). A full run takes a while (~40 minutes on
Windows).

### Handling surviving mutants

A survivor is either a missing test or a mutant that cannot change behavior
(an *equivalent* mutant). Deal with them in this order:

1. **Write the missing test.** Most survivors are real gaps: an untested
   boundary (`>=` vs `>`), a `continue` that could be a `break`, a branch whose
   result is never asserted. Confirm the new test fails with the mutant applied
   (`mutmut apply <id>`, run the test, then `git checkout` the file).
2. **If no test can kill it, remove the cause.** An equivalent mutant usually
   points at redundant code: a variable initialised but never read, or a
   condition that an earlier step already guarantees. Simplify the code so the
   mutant can no longer be generated. Pin the current behavior with a test
   before refactoring.
3. **If the code is already as simple as it should be, exclude the line** with
   `# pragma: no mutate` and say why on the same line, so the exclusion can be
   reviewed:

   ```python
   if os.getenv("SKIP_RATIO_CHECK", "false").lower() == "true":  # pragma: no mutate (any default but "true" is equivalent)
   ```

   Don't use the pragma to hide a gap you could test.

**Log and error-message strings.** mutmut changes string literals
(`"Could not…"` → `"XXCould not…XX"`), and most of these survive because tests
don't assert exact log text. They're expected and are not worth a pragma on
every log line. Assert the message only where its content matters, for example
an error that names the bad input.

**In CI**, don't gate on zero survivors. Use a score threshold for the critical
modules, a committed baseline of known survivors (fail only on new ones), or
mutate only the lines changed in the PR. Run it on a schedule rather than on
every push, given how long it takes.

## Cutting a release

Releases and container publishing are automated from Git tags:

- Use semantic version tags: `git tag -a 1.2.0 -m "Release 1.2.0"`
- Push the tag: `git push origin 1.2.0`
- GitHub Actions will automatically:
  - publish `ghcr.io/squazz/linux-iso-seeder:1.2.0`
  - update `ghcr.io/squazz/linux-iso-seeder:latest`
  - create a GitHub Release for `1.2.0`, unless one already exists for that tag

On normal `main` branch changes, CI still builds and publishes
`ghcr.io/squazz/linux-iso-seeder:latest`. Container image metadata includes
the release version via Docker labels.
