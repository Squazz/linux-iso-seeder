# 48 — CI leftovers: drift-job Python pin, actionlint

**Priority**: P3 · **Class**: CI · **Depends on**: —

From `.dev-team-reports/cd-test-architecture-linux-iso-seeder.md` (migration steps 3 and 5).

## Evidence
- `drift.yml:29`, `:57`, `:109` use `python-version: "3.x"`, while the `test` job pins 3.14 to match Alpine. A drift failure could come from a Python bump, not from upstream drift.
- No workflow linter. A typo in an `if:` or a `${{ }}` expression only shows up when that path runs, which for the tag-push steps is rare.

## Acceptance criteria
1. The drift jobs pin the same Python minor as the `test` job. Add a comment to bump them together.
2. The `test` job runs a pinned `rhysd/actionlint` image over `.github/workflows/`, with any ignores justified inline. CONTRIBUTING.md lists the command.
3. CI-only, so the test-first rule doesn't apply.
