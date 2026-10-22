# 58 — Tests that pin private helpers' internals

**Priority**: P4 (optional) · **Class**: NO_REFACTOR (or a small REFACTOR_REQUIRED rename) · **Depends on**: —

## Evidence
Some tests call `_`-prefixed helpers directly, and a few pin *how* those helpers work rather than what they return:
- `tests/test_torrent_scrape.py` `RandomTransactionIdTests` (`:664`):
  - `test_is_four_random_bytes_read_big_endian` asserts `os.urandom` was called with `4`.
  - `test_is_the_default_id_source` asserts that `scrape_udp_tracker`'s `new_transaction_id` default `is ts._random_transaction_id`.

  Switching to `secrets.randbits(32)`, or inlining the helper, keeps the behaviour (a random 32-bit id per request) but fails both tests.
- `ResolveAddressesTests` (`:725`) asserts `getaddrinfo("tracker.example.com", None)` exactly. Passing a port or `type=SOCK_DGRAM` would fail it, though the addresses returned would be the same.
- `IsDisallowedIpTests` (`:683`), `IsSafeScrapeHostTests` (`:740`) and `tests/test_fetchers.py` `SafeWatchPathTests` (`:349`) call `ts._is_disallowed_ip`, `ts._is_safe_scrape_host`, `ft._safe_watch_path` and `ft._remove_watch_file` directly. These are pure, security-relevant guards (SSRF and path traversal), and their tests check inputs and outputs, so testing them directly is fine. The only problem is that they're private names that tests depend on.
- Found in the same 2026-10-22 coupling review as task 56.

## Acceptance criteria
1. Replace the two `RandomTransactionIdTests` with one behavioural test: ids fit in 32 bits, and the default source gives different ids on successive calls (e.g. two `scrape_udp_tracker` runs against task 56's `FakeUdpSocket` send different transaction ids). Or drop them if task 56's tests already cover this. Don't assert on `os.urandom`.
2. Make `ResolveAddressesTests` assert only on the addresses returned for a faked `getaddrinfo` result, not on the arguments it was called with.
3. For the security guards, pick one option and record it here: make them public (drop the `_`; update `docs/seeding-policy.md` and the mutation critical-set footnote in `tasks/README.md` if they name them), or keep them private and add a comment on each test class saying it pins a security guard on purpose.
4. Full suite, ruff, ruff format, mypy and the coverage gate are green, and mutation scores don't drop.

## Result
- `RandomTransactionIdTests` are replaced by `ScrapeUdpTrackerTests.test_default_transaction_ids_are_random_per_request`: two scrapes with the default id source against an echoing `FakeUdpSocket` tracker complete, and their four ids all differ. 32 bits is enforced by the wire format itself (`struct.pack(">I")` rejects anything larger). Nothing asserts on `os.urandom` any more.
- `ResolveAddressesTests` fakes `getaddrinfo` as a hostname -> entries lookup and asserts only on the addresses returned.
- Security guards: kept private. `IsDisallowedIpTests`, `IsSafeScrapeHostTests` and `SafeWatchPathTests` (which also covers `_remove_watch_file`) each say they call the private guard directly on purpose. Making them public would rename names the mutation critical set and other tasks refer to, for no change in what's tested.
- Mutation: `torrent_scrape.py` at e1d1329 (after tasks 56–58) is 99.2% (252/254), the same as task 50. The two survivors are the accepted `usedforsecurity` and `safe=` equivalents; the other 16 are exception-message literals, excluded under task 41's rule.
