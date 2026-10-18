# 13 — Fix `bdecode` accepting/mis-reporting truncated input

**Priority**: P1 (defect) · **Class**: NO_REFACTOR · **Depends on**: —

## Problem
`torrent_scrape.bdecode` (`torrent_scrape.py:36–75`) is meant to raise `BencodeError` on malformed
data. Verified on 84761d3:

| Input | Actual | Expected |
| --- | --- | --- |
| `b'4:ab'` (declares 4 bytes, has 2) | returns `(b'ab', 6)`, accepted silently | `BencodeError` |
| `b'i12'` (no terminating `e`) | `ValueError: subsection not found` (from `bytes.index`) | `BencodeError` |
| `b'iabce'` (non-numeric int) | `ValueError` from `int()` | `BencodeError` |
| `b'2x:ab'` (bad length) | `ValueError` from `bytes.index`/`int()` | `BencodeError` |

The silent truncation matters most. A truncated `.torrent` download decodes into a wrong `info` dict,
so `compute_info_hash` produces the wrong hash, and the tracker scrape then reports "no demand"
rather than "bad file". `BencodeError` subclasses `ValueError`, so existing callers that catch
`ValueError` keep working.

## Acceptance criteria
- Each input in the table raises `BencodeError` with a message naming the problem and its index.
- A string length that runs past the end of the data raises.
- Existing round-trip tests (`BdecodeBencodeTests`) stay green.
- Mutation: the new guard lines are killed.

## Approach
Add the table above as tests in `BdecodeBencodeTests` and confirm each fails today. Then add a length
check in the byte-string branch, and wrap the `index`/`int` calls so they re-raise as `BencodeError`.
