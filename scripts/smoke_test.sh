#!/bin/sh
# Starts a built image the way a deployment would and checks it comes up:
# entrypoint.sh runs, configure_transmission.py applies its overrides,
# transmission-daemon is running, RUN_AS_NON_ROOT hands /config to PUID:PGID,
# and every Python module imports against the image's apk packages.
#
# Usage: scripts/smoke_test.sh <image>
#
# By default it runs with --network none and SKIP_PACKAGE_UPDATES=true, which
# keeps it deterministic: the daily fetch inside the container logs network
# errors, which is expected - only startup is checked. The weekly drift job
# (.github/workflows/drift.yml) runs the published image as deployed instead:
#   SMOKE_NETWORK=bridge SMOKE_SKIP_PACKAGE_UPDATES=false \
#   SMOKE_TIMEOUT_SECONDS=300 scripts/smoke_test.sh <image>
set -eu

IMAGE=$1
TIMEOUT_SECONDS=${SMOKE_TIMEOUT_SECONDS:-30}
NETWORK=${SMOKE_NETWORK:-none}
SKIP_PACKAGE_UPDATES=${SMOKE_SKIP_PACKAGE_UPDATES:-true}
# Git Bash on Windows would otherwise rewrite /config etc. into Windows paths.
export MSYS_NO_PATHCONV=1

CONTAINERS=""
cleanup() {
    for cid in $CONTAINERS; do
        docker rm -f -v "$cid" >/dev/null 2>&1 || true
    done
}
trap cleanup EXIT

fail() {
    echo "SMOKE TEST FAILED: $1" >&2
    if [ -n "${2:-}" ]; then
        echo "--- container logs ---" >&2
        docker logs "$2" >&2 2>&1 || true
    fi
    exit 1
}

# Usage: start_container <extra docker run args...>; prints the container id.
start_container() {
    docker run -d --network "$NETWORK" \
        -e SKIP_PACKAGE_UPDATES="$SKIP_PACKAGE_UPDATES" \
        -e TRANSMISSION_PEER_LIMIT_GLOBAL=123 \
        "$@" "$IMAGE"
}

wait_until_started() {
    cid=$1
    elapsed=0
    while [ "$elapsed" -lt "$TIMEOUT_SECONDS" ]; do
        if [ "$(docker inspect -f '{{.State.Running}}' "$cid")" != "true" ]; then
            fail "container exited during startup" "$cid"
        fi
        if docker logs "$cid" 2>&1 | grep -q "Starting linux-iso-seeder container" &&
            docker exec "$cid" pgrep -x transmission-daemon >/dev/null; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    fail "transmission-daemon not running after ${TIMEOUT_SECONDS}s" "$cid"
}

# configure_transmission.py only writes settings.json once it has parsed the
# env and applied every override, so the override being there means it ran
# to completion.
check_configure_ran() {
    cid=$1
    docker exec "$cid" python3 -c "
import json, sys
settings = json.load(open('/config/settings.json'))
sys.exit(settings.get('peer-limit-global') != 123)
" || fail "configure_transmission.py did not apply TRANSMISSION_PEER_LIMIT_GLOBAL" "$cid"
}

echo "== default (root) startup"
cid=$(start_container)
CONTAINERS="$CONTAINERS $cid"
wait_until_started "$cid"
check_configure_ran "$cid"

echo "== RUN_AS_NON_ROOT=true PUID=1234 PGID=1234 startup"
cid=$(start_container -e RUN_AS_NON_ROOT=true -e PUID=1234 -e PGID=1234)
CONTAINERS="$CONTAINERS $cid"
wait_until_started "$cid"
check_configure_ran "$cid"
owner=$(docker exec "$cid" stat -c %u:%g /config)
[ "$owner" = "1234:1234" ] || fail "/config owned by $owner, expected 1234:1234" "$cid"
daemon_uid=$(docker exec "$cid" sh -c 'stat -c %u /proc/$(pgrep -x transmission-daemon)')
[ "$daemon_uid" = "1234" ] || fail "transmission-daemon runs as uid $daemon_uid, expected 1234" "$cid"

echo "== imports against the image's apk packages"
docker run --rm --network none -e FETCH_TORRENTS_LOG_DIR=/tmp \
    -w /usr/local/bin --entrypoint python3 "$IMAGE" \
    -c "import fetch_torrents, torrent_scrape, configure_transmission, transmission_rpc, requests, bs4" ||
    fail "a module failed to import inside the image"

echo "Smoke test passed."
