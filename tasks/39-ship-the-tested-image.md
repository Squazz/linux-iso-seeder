# 39 — Push the image that was tested, not a rebuild

**Priority**: P1 · **Class**: CI · **Depends on**: —

From `.dev-team-reports/cd-test-architecture-linux-iso-seeder.md` (migration steps 1–2) and `test-health-2026-10-19-r2.md`.

## Evidence
- `.github/workflows/docker-image.yml`, `build` job: "Build image for smoke test" builds `linux-iso-seeder:smoke` and "Smoke-test the image" tests it. Then "Build and push latest image for main branch" and "Build and push versioned image for tag" **rebuild from scratch** with `docker/build-push-action`.
- The Dockerfile uses `FROM alpine:latest` and unpinned `apk add` (`Dockerfile:4`, `:12-13`), so the rebuild can pull different packages than the image that passed. The rebuild also passes `VERSION=...` while the smoke build passes no build args, so even the layers differ.
- Nothing checks the pushed tag after the push. The weekly `published-image` job in `drift.yml` is the first check.

## Acceptance criteria
1. The image is built once per workflow run, with the final `VERSION` build arg (`latest` on main, the tag version on tags). The smoke test runs against that image ID.
2. The push publishes that exact image: `docker tag` + `docker push`, or `build-push-action` with `load: true` and then a push of the same image. No second `docker build` after the smoke test. For tags, `latest` and `<version>` point to the same digest.
3. After the push, a step pulls the pushed tag, checks that its digest matches the image that was smoke-tested, and fails the job if it doesn't.
4. The in-image unit-test stage (`docker build --target test .`) still runs before the build, on the same base. If the cache doesn't already share the base between the stages, pinning `alpine` by digest in the Dockerfile (bumped by Dependabot) is an acceptable way to make "tested == shipped".
5. CI-only change, so the test-first rule doesn't apply. Prove it with one green run on a branch and one dry tag push (or a `workflow_dispatch` path that skips the push).
