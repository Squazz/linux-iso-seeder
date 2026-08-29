#!/bin/sh

echo "Starting linux-iso-seeder container"

# Update all packages to latest
apk update
apk upgrade

# Clean up apk cache
rm -rf /var/cache/apk/*

# Root is the default, matching every previous release - so existing
# deployments (including ones sharing /config, /downloads, /watch, /logs
# with other containers/apps) see no behavior change. Set RUN_AS_NON_ROOT=true
# to opt in to running transmission-daemon and the fetch script as a
# dedicated non-root user instead.
RUN_AS_NON_ROOT=$(echo "${RUN_AS_NON_ROOT:-false}" | tr '[:upper:]' '[:lower:]')

RUN_AS=""
if [ "$RUN_AS_NON_ROOT" = "true" ]; then
    echo "RUN_AS_NON_ROOT=true: running transmission-daemon and the fetch script as the 'seeder' user"

    PUID=${PUID:-1000}
    PGID=${PGID:-1000}

    if [ "$(id -u seeder)" != "$PUID" ] || [ "$(id -g seeder)" != "$PGID" ]; then
        deluser seeder 2>/dev/null
        delgroup seeder 2>/dev/null
        addgroup -g "$PGID" seeder
        adduser -D -H -u "$PUID" -G seeder seeder
    fi

    # Recursive so an existing root-owned /config, /downloads, /watch, /logs
    # (e.g. a deployment enabling this after running as root before) becomes
    # readable/writable by the new user. Best-effort: must not block startup
    # if it fails (e.g. a mount that disallows chown).
    chown -R seeder:seeder /config /downloads /watch /logs || echo "WARNING: failed to chown working directories to seeder:seeder; continuing anyway"

    RUN_AS="su-exec seeder"
fi

# Start torrent fetcher script in background, running daily
while true; do
    $RUN_AS python3 /usr/local/bin/fetch_torrents.py
    sleep 86400  # 24 hours
done &

# Start transmission-daemon
exec $RUN_AS transmission-daemon --foreground --config-dir /config --download-dir /downloads --watch-dir /watch
