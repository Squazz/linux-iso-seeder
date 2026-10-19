# 38 — Re-measure, raise the coverage ratchet, record the baseline

**Priority**: P3 · **Class**: — · **Depends on**: 28–37 (or whichever of them are done)

## Steps
1. Full mutmut runs on all three modules, with the whole suite as the runner. `test_live_check` needs `scripts/` in the mutation working copy; copy it in, or leave the module out.
2. Coverage. It is 99% total at aa81ef3 against `fail_under = 94` in `pyproject.toml`. Raise `fail_under` to a value CI can hold (e.g. 97). CI's pip-installed versions can cover slightly different lines than local runs, so check the CI number before ratcheting to the local one.
3. Update the "Targets" table in `tasks/README.md`: tests, coverage, mutation scores, Farley, and the accepted-equivalent survivor list from task 36.
4. Optionally re-run `/test-health` to produce a fresh report and compare it with `.dev-team-reports/test-health-2026-10-19.md`.

## Optional: business-readable seeding policy (Q2)
The suite has no business-facing (Q2) layer: no `.feature` files, and the seeding policy exists only as code-level examples. A short README or `docs/` section would let a non-developer review the policy without adopting a BDD runner. It would be a plain table of when an ISO is fetched, kept, removed or re-seeded, with each row naming the test that pins it.
