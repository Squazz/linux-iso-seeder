# 50 — Re-measure round 3; optional seeding-policy table

**Priority**: P3 · **Class**: — · **Depends on**: 39–49 (or whichever are done)

## Steps
1. Full mutmut runs on all three modules with task 41's rule (only message literals excluded). Every other survivor is killed or listed under "Accepted equivalent mutants" with its reason.
2. Coverage. Raise `fail_under` if task 46 moved it, after checking the CI number.
3. Update the round-3 rows and the Targets table in `tasks/README.md`: tests, coverage, mutation scores, and Farley (8.33 across 493 tests at 01b77ce).
4. Re-run `/test-health` and compare with `.dev-team-reports/test-health-2026-10-19-r2.md`.

## Optional: business-readable seeding policy (Q2)
Carried over from task 38, still not done. Add a plain table in the README or a `docs/` page listing when an ISO is fetched, kept, removed or re-seeded. Each row names the test that pins it, so a non-developer can review the policy without a BDD runner.
