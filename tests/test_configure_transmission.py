"""Tests for configure_transmission.py.

Run with: python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import configure_transmission as ct


class BuildRpcOverridesTests(unittest.TestCase):
    def test_no_relevant_env_vars_yields_no_overrides(self):
        self.assertEqual(ct.build_rpc_overrides({}), {})

    def test_whitelist_env_var_broadens_and_keeps_whitelist_enabled(self):
        overrides = ct.build_rpc_overrides({'TRANSMISSION_RPC_WHITELIST': '10.0.0.*'})

        self.assertEqual(
            overrides,
            {'rpc-whitelist-enabled': True, 'rpc-whitelist': '10.0.0.*'},
        )

    def test_blank_whitelist_env_var_is_ignored(self):
        self.assertEqual(ct.build_rpc_overrides({'TRANSMISSION_RPC_WHITELIST': '   '}), {})

    def test_username_and_password_enable_authentication(self):
        overrides = ct.build_rpc_overrides({
            'TRANSMISSION_RPC_USERNAME': 'alice',
            'TRANSMISSION_RPC_PASSWORD': 'hunter2',
        })

        self.assertEqual(
            overrides,
            {
                'rpc-authentication-required': True,
                'rpc-username': 'alice',
                'rpc-password': 'hunter2',
            },
        )

    def test_username_without_password_does_not_enable_authentication(self):
        overrides = ct.build_rpc_overrides({'TRANSMISSION_RPC_USERNAME': 'alice'})

        self.assertEqual(overrides, {})

    def test_password_without_username_does_not_enable_authentication(self):
        overrides = ct.build_rpc_overrides({'TRANSMISSION_RPC_PASSWORD': 'hunter2'})

        self.assertEqual(overrides, {})

    def test_whitelist_and_auth_can_combine(self):
        overrides = ct.build_rpc_overrides({
            'TRANSMISSION_RPC_WHITELIST': '*',
            'TRANSMISSION_RPC_USERNAME': 'alice',
            'TRANSMISSION_RPC_PASSWORD': 'hunter2',
        })

        self.assertEqual(
            overrides,
            {
                'rpc-whitelist-enabled': True,
                'rpc-whitelist': '*',
                'rpc-authentication-required': True,
                'rpc-username': 'alice',
                'rpc-password': 'hunter2',
            },
        )


class BuildPeerLimitOverridesTests(unittest.TestCase):
    def test_no_relevant_env_vars_yields_no_overrides(self):
        self.assertEqual(ct.build_peer_limit_overrides({}), {})

    def test_global_limit_env_var_sets_override(self):
        overrides = ct.build_peer_limit_overrides({'TRANSMISSION_PEER_LIMIT_GLOBAL': '1000'})

        self.assertEqual(overrides, {'peer-limit-global': 1000})

    def test_per_torrent_limit_env_var_sets_override(self):
        overrides = ct.build_peer_limit_overrides({'TRANSMISSION_PEER_LIMIT_PER_TORRENT': '300'})

        self.assertEqual(overrides, {'peer-limit-per-torrent': 300})

    def test_both_limits_can_combine(self):
        overrides = ct.build_peer_limit_overrides({
            'TRANSMISSION_PEER_LIMIT_GLOBAL': '1000',
            'TRANSMISSION_PEER_LIMIT_PER_TORRENT': '300',
        })

        self.assertEqual(overrides, {'peer-limit-global': 1000, 'peer-limit-per-torrent': 300})

    def test_blank_env_vars_are_ignored(self):
        overrides = ct.build_peer_limit_overrides({
            'TRANSMISSION_PEER_LIMIT_GLOBAL': '   ',
            'TRANSMISSION_PEER_LIMIT_PER_TORRENT': '',
        })

        self.assertEqual(overrides, {})

    def test_non_numeric_env_vars_are_ignored(self):
        overrides = ct.build_peer_limit_overrides({
            'TRANSMISSION_PEER_LIMIT_GLOBAL': 'unlimited',
            'TRANSMISSION_PEER_LIMIT_PER_TORRENT': 'lots',
        })

        self.assertEqual(overrides, {})

    def test_zero_and_negative_values_are_ignored(self):
        overrides = ct.build_peer_limit_overrides({
            'TRANSMISSION_PEER_LIMIT_GLOBAL': '0',
            'TRANSMISSION_PEER_LIMIT_PER_TORRENT': '-5',
        })

        self.assertEqual(overrides, {})


class BuildPortForwardingOverridesTests(unittest.TestCase):
    def test_no_env_var_on_first_run_defaults_to_disabled(self):
        overrides = ct.build_port_forwarding_overrides({}, settings_file_exists=False)

        self.assertEqual(overrides, {'port-forwarding-enabled': False})

    def test_no_env_var_on_later_run_yields_no_override(self):
        overrides = ct.build_port_forwarding_overrides({}, settings_file_exists=True)

        self.assertEqual(overrides, {})

    def test_explicit_true_enables_it_even_on_first_run(self):
        overrides = ct.build_port_forwarding_overrides(
            {'TRANSMISSION_PORT_FORWARDING': 'true'}, settings_file_exists=False,
        )

        self.assertEqual(overrides, {'port-forwarding-enabled': True})

    def test_explicit_false_disables_it_on_a_later_run(self):
        overrides = ct.build_port_forwarding_overrides(
            {'TRANSMISSION_PORT_FORWARDING': 'false'}, settings_file_exists=True,
        )

        self.assertEqual(overrides, {'port-forwarding-enabled': False})

    def test_blank_env_var_on_first_run_falls_back_to_default(self):
        overrides = ct.build_port_forwarding_overrides(
            {'TRANSMISSION_PORT_FORWARDING': '   '}, settings_file_exists=False,
        )

        self.assertEqual(overrides, {'port-forwarding-enabled': False})

    def test_invalid_env_var_on_later_run_yields_no_override(self):
        overrides = ct.build_port_forwarding_overrides(
            {'TRANSMISSION_PORT_FORWARDING': 'sometimes'}, settings_file_exists=True,
        )

        self.assertEqual(overrides, {})


class WarnIfOpenWithoutAuthTests(unittest.TestCase):
    def test_warns_when_whitelist_broadened_without_auth(self):
        warning = ct.warn_if_open_without_auth({'rpc-whitelist-enabled': True, 'rpc-whitelist': '*'})

        self.assertIsNotNone(warning)

    def test_no_warning_when_auth_also_required(self):
        warning = ct.warn_if_open_without_auth({
            'rpc-whitelist-enabled': True,
            'rpc-whitelist': '*',
            'rpc-authentication-required': True,
            'rpc-username': 'alice',
            'rpc-password': 'hunter2',
        })

        self.assertIsNone(warning)

    def test_no_warning_when_whitelist_untouched(self):
        self.assertIsNone(ct.warn_if_open_without_auth({}))


class ApplyOverridesTests(unittest.TestCase):
    def test_overrides_take_precedence_but_other_keys_survive(self):
        settings = {'peer-port': 51413, 'rpc-whitelist-enabled': True, 'rpc-whitelist': '127.0.0.1'}
        overrides = {'rpc-whitelist': '10.0.0.*'}

        merged = ct.apply_overrides(settings, overrides)

        self.assertEqual(merged['peer-port'], 51413)
        self.assertEqual(merged['rpc-whitelist'], '10.0.0.*')
        self.assertTrue(merged['rpc-whitelist-enabled'])


class SettingsFilePersistenceTests(unittest.TestCase):
    def test_round_trips_through_disk(self):
        tmp_dir = tempfile.mkdtemp(prefix='configure_transmission_')
        path = os.path.join(tmp_dir, 'settings.json')
        settings = {'rpc-whitelist': '10.0.0.*'}

        ct.save_settings(path, settings)
        loaded = ct.load_settings(path)

        self.assertEqual(loaded, settings)

    def test_missing_file_returns_empty_settings(self):
        tmp_dir = tempfile.mkdtemp(prefix='configure_transmission_')
        path = os.path.join(tmp_dir, 'does-not-exist.json')

        self.assertEqual(ct.load_settings(path), {})

    def test_corrupt_file_returns_empty_settings_instead_of_raising(self):
        tmp_dir = tempfile.mkdtemp(prefix='configure_transmission_')
        path = os.path.join(tmp_dir, 'settings.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{not valid json')

        self.assertEqual(ct.load_settings(path), {})


if __name__ == "__main__":
    unittest.main()
