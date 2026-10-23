# 53 — Lint and test workflow-only changes in CI

**Priority**: P3 · **Class**: CI · **Depends on**: —

## Evidence
- `.github/workflows/docker-image.yml:7-13` and `:20-26`: both `push` and `pull_request` ignore `.github/workflows/**`. A change that touches only workflow files never runs the `test` job, so:
  - task 48's actionlint step never sees a PR that only edits `drift.yml`;
  - a PR that only edits `docker-image.yml` itself, as task 39's build/push rework could have been, merges with no CI run at all. The first run of the changed workflow happens on `main`, where it can push `latest`.
- Task 48 left this on purpose, because removing the ignore would also rebuild the image on those edits and, on `main`, push `latest` again. `CONTRIBUTING.md` asks contributors to run actionlint locally instead. That is a convention, not a gate.

## Acceptance criteria
1. A PR that changes only files under `.github/workflows/` runs actionlint on all workflows and fails if it finds anything. Options, pick one and say why in the commit:
   - a small separate workflow (e.g. `.github/workflows/lint-workflows.yml`) triggered on `pull_request` and `push` with `paths: [".github/workflows/**"]`, running the same pinned `rhysd/actionlint` image as `docker-image.yml`; or
   - drop `.github/workflows/**` from `docker-image.yml`'s `pull_request` `paths-ignore` only (PR runs never push), keeping it on `push`.
2. A push to `main` that only edits a workflow still does not push a new `latest`.
3. Keep the actionlint image pin in one place, or add a comment at each copy saying to bump them together, the way task 48 did for `PYTHON_VERSION`.
4. Update `CONTRIBUTING.md` and `.claude/CLAUDE.md` to match. Verify locally with actionlint, and note in the commit that the trigger itself is only verified by the first workflow-only PR.

## Result
- Took the second option: `docker-image.yml`'s `pull_request` trigger no longer ignores `.github/workflows/**`, so a workflow-only PR runs the whole `test` job (actionlint included) and the `build` job's PR path, which never pushes. `push` keeps the ignore, so a workflow-only push to `main` still doesn't push `latest` (an edit to `docker-image.yml` itself still runs, as before). This keeps the actionlint image pin in one place, and a PR that reworks `docker-image.yml` now also gets its build path exercised before merge. The cost is a full test + build run on workflow-only PRs.
- Checked locally with actionlint 1.7.12 (no findings; without shellcheck installed, so the `run:` scripts weren't shell-linted). The trigger itself is only verified by the first workflow-only PR.
