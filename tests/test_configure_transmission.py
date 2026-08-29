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
