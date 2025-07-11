FROM alpine:latest
LABEL org.opencontainers.image.source=https://github.com/squazz/linux-iso-seeder
# Install prerequisites
RUN apk update && \
    apk add --no-cache transmission-daemon curl wget python3 py3-pip py3-requests py3-beautifulsoup4 py3-transmission-rpc

# Add fetch script
COPY fetch_torrents.py /usr/local/bin/fetch_torrents.py
RUN chmod +x /usr/local/bin/fetch_torrents.py

# Add entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose Transmission Web UI and peer ports
EXPOSE 9091 51413

# Create directories
RUN mkdir -p /config /downloads /watch /logs

VOLUME ["/config", "/downloads", "/watch", "/logs"]

ENTRYPOINT ["/entrypoint.sh"]
