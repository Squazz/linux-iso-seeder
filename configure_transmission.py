#!/usr/bin/env python3
"""Applies environment-variable-driven overrides to Transmission's
settings.json before transmission-daemon starts, so operators can opt into
broadening (and authenticating) the RPC/web UI without hand-editing the
auto-generated config file. Every override is additive: an unset env var
never touches - or resets - whatever's already on disk, whether that's a
value Transmission wrote itself or one an operator edited by hand.
"""
import json
import os
import sys


def build_rpc_overrides(env):
    overrides = {}

    whitelist = env.get('TRANSMISSION_RPC_WHITELIST', '').strip()
    if whitelist:
        overrides['rpc-whitelist-enabled'] = True
        overrides['rpc-whitelist'] = whitelist

    username = env.get('TRANSMISSION_RPC_USERNAME', '').strip()
    password = env.get('TRANSMISSION_RPC_PASSWORD', '').strip()
    if username and password:
        overrides['rpc-authentication-required'] = True
        overrides['rpc-username'] = username
        # Plaintext is intentional: transmission-daemon hashes rpc-password
        # in place on its next start, same as if set by hand.
        overrides['rpc-password'] = password

    return overrides


def warn_if_open_without_auth(overrides):
    """Broadening rpc-whitelist without also requiring authentication means
    anyone who can reach the RPC port has full control (add/remove/delete
    data) - Transmission has no read-only RPC mode. Returns a warning
    message to log, or None if there's nothing to warn about."""
    if overrides.get('rpc-whitelist-enabled') and not overrides.get('rpc-authentication-required'):
        return (
            "TRANSMISSION_RPC_WHITELIST is set but TRANSMISSION_RPC_USERNAME/"
            "TRANSMISSION_RPC_PASSWORD are not - the web UI/RPC endpoint is "
            "reachable from that whitelist with no login required, and "
            "Transmission has no read-only RPC mode. Set both env vars to "
            "require authentication."
        )
    return None


def apply_overrides(settings, overrides):
    return {**settings, **overrides}


def load_settings(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"configure_transmission: could not read {path} ({exc}) - starting fresh.", file=sys.stderr)
        return {}


def save_settings(path, settings):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4, sort_keys=True)
    os.replace(tmp_path, path)


def main():
    settings_path = os.getenv('TRANSMISSION_SETTINGS_FILE', '/config/settings.json')
    overrides = build_rpc_overrides(os.environ)
    if not overrides:
        return

    settings = load_settings(settings_path)
    settings = apply_overrides(settings, overrides)
    save_settings(settings_path, settings)

    warning = warn_if_open_without_auth(overrides)
    if warning:
        print(f"WARNING: {warning}", file=sys.stderr)


if __name__ == "__main__":
    main()
