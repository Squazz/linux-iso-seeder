# 41 — Only exclude message-text literals from the mutation score

**Priority**: P3 · **Class**: process (docs) · **Depends on**: 40

## Evidence
- `tasks/README.md` ("Targets": "string-literal-only survivors (log and error text) are excluded") and `CONTRIBUTING.md` ("Log and error-message strings") treat **every** string-literal survivor as message text.
- In `torrent_scrape.py`, 5 of the 22 literal survivors at 01b77ce were not message text: a URL scheme (`"https"`), a path separator (`"/"`), `quote_from_bytes(safe="")`, and two codec error handlers (`"replace"`). Two of them hid real gaps (task 40).

## Acceptance criteria
1. Both documents say that only literals inside log calls and exception messages are excluded. Any other literal survivor is triaged like a behavioural survivor: test it, simplify the code, or accept it as an equivalent with a reason.
2. `safe=""` → `safe="XXXX"` in `build_scrape_request_url` is added to "Accepted equivalent mutants" with its reason: trackers decode `%58` and `X` the same, so leaving `X` unescaped changes nothing.
3. The `configure_transmission.py` default-`""` survivors (`value or ""`, `env.get(..., "")`) are added as accepted equivalents: `"XXXX"` fails to parse just as `""` does.
4. Docs only, so the test-first rule doesn't apply.
