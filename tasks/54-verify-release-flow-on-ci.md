# 54 — Verify the build-once release flow on GitHub

**Priority**: P2 · **Class**: CI (manual verification) · **Depends on**: 39, 48

## Evidence
- Task 39 changed the `build` job in `.github/workflows/docker-image.yml` to build the image once, smoke-test it, then `docker tag` + `docker push` it. A new step pulls each pushed tag back and fails if its image ID differs from the tested one. Locally only the build, cache reuse and smoke test were checked. Registry login, push, the pull-back digest check and the `workflow_dispatch` dry run have never run.
- Task 48 added the actionlint step to the `test` job; it has only run locally.
- Task 51's partial-failure test (`tests/test_daily_run.py`, `test_failing_to_save_the_check_state_still_reports_the_counts`) was only run on Windows. On Linux, the blocked write raises `IsADirectoryError` instead of `PermissionError`; the test only checks the message prefix, so it should pass, but CI is the first Linux run.

## Acceptance criteria
1. The round-3 PR's run is green: the `test` job (including actionlint and task 51's test on Linux) and the `build` job's PR path, which builds and smoke-tests but pushes nothing.
2. After merge, the `push` to `main` run pushes `latest`, and the pull-back check passes. Record the run URL here.
3. A `workflow_dispatch` run on a tag ref completes without pushing anything (check the registry's tag list before and after). Record the run URL.
4. On the next real release tag, `<version>` and `latest` are pushed and the pull-back check shows them as the same image ID. Record the run URL.
5. If any step fails, fix it in a follow-up commit referencing this task, rather than re-running until it passes.
