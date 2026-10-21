# 32 — Atomic `.torrent` writes (partial file treated as "existing" forever)

**Priority**: P2 (bug) · **Class**: NO_REFACTOR (characterize, then behaviour fix) · **Depends on**: —

## Evidence
- `fetch_torrents.py:534` (`download_torrent`) and `:1115` (old-release add) write straight to the final `/watch/<name>.torrent` path.
- If the process dies or the disk fills mid-write, a truncated file stays behind. On the next run `os.path.exists(dest)` returns `"existing"`, so it is never re-fetched, and Transmission rejects or ignores the broken file.
- `configure_transmission.save_settings` and the `save_*` state writers already use tmp + `os.replace`. Only the watch-dir writes don't.

## Acceptance criteria
1. Characterization first: a test where the write fails part-way leaves a partial `<name>.torrent` behind today, and the next `download_torrent` call returns `"existing"`. Patch `open` to raise after the first write, or use a response whose `.content` access raises. Commit this as documenting current behaviour, or write it straight as the failing test for step 2.
2. Fix test-first: write to `<dest>.tmp` (or a `tempfile` in `watch_dir`, so transmission-daemon's watcher never sees a half file) and `os.replace` into place. On failure no `<name>.torrent` exists, and the next call downloads again.
3. Make sure transmission-daemon ignores the temp name. It watches `*.torrent`, so a `.torrent.part` suffix or a dot-prefixed name is safer than `.torrent.tmp`.
4. The same for the old-release write at `:1115`.
5. The README/CLAUDE.md notes are updated if the watch-dir contract changes.
