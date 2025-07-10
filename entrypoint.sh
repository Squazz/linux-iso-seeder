#!/bin/sh

echo "Starting linux-iso-seeder container"

# Update all packages to latest
apk update
apk upgrade

# Clean up apk cache
rm -rf /var/cache/apk/*

# Start torrent fetcher script in background, running daily
while true; do
    python3 /usr/local/bin/fetch_torrents.py
    sleep 86400  # 24 hours
done &

# Start transmission-daemon
exec transmission-daemon --foreground --config-dir /config --download-dir /downloads --watch-dir /watch
