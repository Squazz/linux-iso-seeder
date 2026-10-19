# 40 — https scrape URLs and non-UTF-8 tracker failure reasons

**Priority**: P2 · **Class**: NO_REFACTOR · **Depends on**: —

Found by re-running mutmut on `torrent_scrape.py` at 01b77ce. These survivors only change a string literal, so the round-2 scoring rule excluded them (see task 41).

## Evidence
- `torrent_scrape.py:165` `derive_scrape_url`: the mutant `("http", "XXhttpsXX")` survives. `DeriveScrapeUrlTests` (`tests/test_torrent_scrape.py:250`) has no `https://` case, so a change that drops https support passes. An https-only tracker would then never be scraped, and the release would be classed as "no demand".
- `torrent_scrape.py:168`: `rfind("/")` → `rfind("XX/XX")` survives. No case has "announce" in a *non-final* path segment (e.g. `http://example.com/announce/x` must give `None`), so the "last segment only" rule is unpinned.
- `torrent_scrape.py:341` (HTTP `failure reason`) and the UDP error-text decode (`decode('utf-8', 'replace')` in the UDP response parser): the mutant `'replace'` → `'XXreplaceXX'` survives. No test sends a non-UTF-8 failure message, so a change that raises `LookupError`/`UnicodeDecodeError` instead of a readable tracker error passes.

## Acceptance criteria
1. `DeriveScrapeUrlTests` cases table gains:
   - `https://example.com/announce` → `https://example.com/scrape`
   - `https://example.com/x/announce.php?a=1` → `https://example.com/x/scrape.php?a=1`
   - `http://example.com/announce/x` → `None`
2. An HTTP scrape whose bencoded `failure reason` is invalid UTF-8 (e.g. `b"bad \xff"`) raises `BencodeError` with the replacement character in the message. The same for a UDP action-3 error response, with `UdpTrackerError`.
3. Confirm each new test kills its mutant (`mutmut run --paths-to-mutate torrent_scrape.py` then `mutmut results`, or `mutmut apply <id>` and run the test).
4. If a test shows a real bug, fix the production code test-first.
