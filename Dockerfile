FROM alpine:latest
ARG VERSION=latest
LABEL org.opencontainers.image.source=https://github.com/squazz/linux-iso-seeder
LABEL org.opencontainers.image.version=$VERSION
# Install prerequisites
RUN apk update && \
    apk add --no-cache transmission-daemon curl wget python3 py3-pip py3-requests py3-beautifulsoup4 py3-transmission-rpc su-exec

# Create a non-root user/group the daemon and fetch script can optionally
# run as (see RUN_AS_NON_ROOT in entrypoint.sh). Unused, and no behavior
# change, unless that's explicitly enabled - the container still runs as
# root by default.
RUN addgroup -g 1000 seeder && \
    adduser -D -H -u 1000 -G seeder seeder

# Add fetch script
COPY fetch_torrents.py /usr/local/bin/fetch_torrents.py
RUN chmod +x /usr/local/bin/fetch_torrents.py

# Add Transmission RPC/web UI settings.json configurator
COPY configure_transmission.py /usr/local/bin/configure_transmission.py
RUN chmod +x /usr/local/bin/configure_transmission.py

# Add entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose Transmission Web UI and peer ports
EXPOSE 9091 51413

# Create directories
RUN mkdir -p /config /downloads /watch /logs

VOLUME ["/config", "/downloads", "/watch", "/logs"]

ENTRYPOINT ["/entrypoint.sh"]
