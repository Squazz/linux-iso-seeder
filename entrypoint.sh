#!/bin/sh

echo "Starting linux-iso-seeder container"

# Update packages and transmission-daemon to latest
apk update
apk upgrade transmission-daemon

# Start torrent fetcher script in background, running daily
while true; do
    python3 /usr/local/bin/fetch_torrents.py
    sleep 86400  # 24 hours
done &

# Start transmission-daemon
exec transmission-daemon --foreground --config-dir /config --download-dir /downloads --watch-dir /watch
