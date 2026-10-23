"""Tests for configure_transmission.py.

Run with: python -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import runpy
import unittest
import unittest.mock

import helpers

import configure_transmission as ct


def setUpModule():
    helpers.isolate_module()


class BuildRpcOverridesTests(unittest.TestCase):
    def test_no_relevant_env_vars_yields_no_overrides(self):
        self.assertEqual(ct.build_rpc_overrides({}), {})

    def test_whitelist_env_var_adds_to_localhost_and_keeps_whitelist_enabled(self):
        # The fetch script talks to the daemon from inside the container, so
        # replacing Transmission's 127.0.0.1,::1 default would lock it out.
        overrides = ct.build_rpc_overrides({"TRANSMISSION_RPC_WHITELIST": "10.0.0.*"})

        self.assertEqual(
            overrides,
            {"rpc-whitelist-enabled": True, "rpc-whitelist": "127.0.0.1,::1,10.0.0.*"},
        )

    def test_whitelist_env_var_entries_are_trimmed_and_localhost_not_repeated(self):
        overrides = ct.build_rpc_overrides(
            {"TRANSMISSION_RPC_WHITELIST": " 10.0.0.* , 127.0.0.1,, 192.168.1.5 "}
        )

        self.assertEqual(
            overrides["rpc-whitelist"], "::1,10.0.0.*,127.0.0.1,192.168.1.5"
        )

    def test_blank_whitelist_env_var_is_ignored(self):
        self.assertEqual(
            ct.build_rpc_overrides({"TRANSMISSION_RPC_WHITELIST": "   "}), {}
        )

    def test_username_and_password_enable_authentication(self):
        overrides = ct.build_rpc_overrides(
            {
                "TRANSMISSION_RPC_USERNAME": "alice",
                "TRANSMISSION_RPC_PASSWORD": "hunter2",
            }
        )

        self.assertEqual(
            overrides,
            {
                "rpc-authentication-required": True,
                "rpc-username": "alice",
                "rpc-password": "hunter2",
            },
        )

    def test_username_without_password_does_not_enable_authentication(self):
        overrides = ct.build_rpc_overrides({"TRANSMISSION_RPC_USERNAME": "alice"})

        self.assertEqual(overrides, {})

    def test_password_without_username_does_not_enable_authentication(self):
        overrides = ct.build_rpc_overrides({"TRANSMISSION_RPC_PASSWORD": "hunter2"})

        self.assertEqual(overrides, {})

    def test_whitelist_and_auth_can_combine(self):
        overrides = ct.build_rpc_overrides(
            {
                "TRANSMISSION_RPC_WHITELIST": "*",
                "TRANSMISSION_RPC_USERNAME": "alice",
                "TRANSMISSION_RPC_PASSWORD": "hunter2",
            }
        )

        self.assertEqual(
            overrides,
            {
                "rpc-whitelist-enabled": True,
                "rpc-whitelist": "127.0.0.1,::1,*",
                "rpc-authentication-required": True,
                "rpc-username": "alice",
                "rpc-password": "hunter2",
            },
        )


class BuildPeerLimitOverridesTests(unittest.TestCase):
    def test_no_relevant_env_vars_yields_no_overrides(self):
        self.assertEqual(ct.build_peer_limit_overrides({}), {})

    def test_global_limit_env_var_sets_override(self):
        overrides = ct.build_peer_limit_overrides(
            {"TRANSMISSION_PEER_LIMIT_GLOBAL": "1000"}
        )

        self.assertEqual(overrides, {"peer-limit-global": 1000})

    def test_per_torrent_limit_env_var_sets_override(self):
        overrides = ct.build_peer_limit_overrides(
            {"TRANSMISSION_PEER_LIMIT_PER_TORRENT": "300"}
        )

        self.assertEqual(overrides, {"peer-limit-per-torrent": 300})

    def test_both_limits_can_combine(self):
        overrides = ct.build_peer_limit_overrides(
            {
                "TRANSMISSION_PEER_LIMIT_GLOBAL": "1000",
                "TRANSMISSION_PEER_LIMIT_PER_TORRENT": "300",
            }
        )

        self.assertEqual(
            overrides, {"peer-limit-global": 1000, "peer-limit-per-torrent": 300}
        )

    def test_blank_env_vars_are_ignored(self):
        overrides = ct.build_peer_limit_overrides(
            {
                "TRANSMISSION_PEER_LIMIT_GLOBAL": "   ",
                "TRANSMISSION_PEER_LIMIT_PER_TORRENT": "",
            }
        )

        self.assertEqual(overrides, {})

    def test_non_numeric_env_vars_are_ignored(self):
        overrides = ct.build_peer_limit_overrides(
            {
                "TRANSMISSION_PEER_LIMIT_GLOBAL": "unlimited",
                "TRANSMISSION_PEER_LIMIT_PER_TORRENT": "lots",
            }
        )

        self.assertEqual(overrides, {})

    def test_a_limit_of_one_is_kept(self):
        overrides = ct.build_peer_limit_overrides(
            {
                "TRANSMISSION_PEER_LIMIT_GLOBAL": "1",
                "TRANSMISSION_PEER_LIMIT_PER_TORRENT": " 1 ",
            }
        )

        self.assertEqual(
            overrides, {"peer-limit-global": 1, "peer-limit-per-torrent": 1}
        )

    def test_zero_and_negative_values_are_ignored(self):
        overrides = ct.build_peer_limit_overrides(
            {
                "TRANSMISSION_PEER_LIMIT_GLOBAL": "0",
                "TRANSMISSION_PEER_LIMIT_PER_TORRENT": "-5",
            }
        )

        self.assertEqual(overrides, {})


class BuildPortForwardingOverridesTests(unittest.TestCase):
    def test_no_env_var_on_first_run_defaults_to_disabled(self):
        overrides = ct.build_port_forwarding_overrides({}, settings_file_exists=False)

        self.assertEqual(overrides, {"port-forwarding-enabled": False})

    def test_no_env_var_on_later_run_yields_no_override(self):
        overrides = ct.build_port_forwarding_overrides({}, settings_file_exists=True)

        self.assertEqual(overrides, {})

    def test_explicit_true_enables_it_even_on_first_run(self):
        overrides = ct.build_port_forwarding_overrides(
            {"TRANSMISSION_PORT_FORWARDING": "true"},
            settings_file_exists=False,
        )

        self.assertEqual(overrides, {"port-forwarding-enabled": True})

    def test_explicit_false_disables_it_on_a_later_run(self):
        overrides = ct.build_port_forwarding_overrides(
            {"TRANSMISSION_PORT_FORWARDING": "false"},
            settings_file_exists=True,
        )

        self.assertEqual(overrides, {"port-forwarding-enabled": False})

    def test_explicit_value_ignores_case_and_surrounding_whitespace(self):
        for value, expected in (("TRUE", True), (" false ", False), ("True\n", True)):
            with self.subTest(value=value):
                overrides = ct.build_port_forwarding_overrides(
                    {"TRANSMISSION_PORT_FORWARDING": value},
                    settings_file_exists=True,
                )

                self.assertEqual(overrides, {"port-forwarding-enabled": expected})

    def test_blank_env_var_on_first_run_falls_back_to_default(self):
        overrides = ct.build_port_forwarding_overrides(
            {"TRANSMISSION_PORT_FORWARDING": "   "},
            settings_file_exists=False,
        )

        self.assertEqual(overrides, {"port-forwarding-enabled": False})

    def test_invalid_env_var_on_later_run_yields_no_override(self):
        overrides = ct.build_port_forwarding_overrides(
            {"TRANSMISSION_PORT_FORWARDING": "sometimes"},
            settings_file_exists=True,
        )

        self.assertEqual(overrides, {})


class WarnIfOpenWithoutAuthTests(unittest.TestCase):
    def test_warns_when_whitelist_broadened_without_auth(self):
        warning = ct.warn_if_open_without_auth(
            {"rpc-whitelist-enabled": True, "rpc-whitelist": "*"}
        )

        self.assertEqual(
            warning,
            "TRANSMISSION_RPC_WHITELIST is set but TRANSMISSION_RPC_USERNAME/"
            "TRANSMISSION_RPC_PASSWORD are not - the web UI/RPC endpoint is "
            "reachable from that whitelist with no login required, and "
            "Transmission has no read-only RPC mode. Set both env vars to "
            "require authentication.",
        )

    def test_no_warning_when_auth_also_required(self):
        warning = ct.warn_if_open_without_auth(
            {
                "rpc-whitelist-enabled": True,
                "rpc-whitelist": "*",
                "rpc-authentication-required": True,
                "rpc-username": "alice",
                "rpc-password": "hunter2",
            }
        )

        self.assertIsNone(warning)

    def test_no_warning_when_whitelist_untouched(self):
        self.assertIsNone(ct.warn_if_open_without_auth({}))


class ApplyOverridesTests(unittest.TestCase):
    def test_overrides_take_precedence_but_other_keys_survive(self):
        settings = {
            "peer-port": 51413,
            "rpc-whitelist-enabled": True,
            "rpc-whitelist": "127.0.0.1",
        }
        overrides = {"rpc-whitelist": "10.0.0.*"}

        merged = ct.apply_overrides(settings, overrides)

        self.assertEqual(
            merged,
            {
                "peer-port": 51413,
                "rpc-whitelist-enabled": True,
                "rpc-whitelist": "10.0.0.*",
            },
        )
        self.assertEqual(
            settings,
            {
                "peer-port": 51413,
                "rpc-whitelist-enabled": True,
                "rpc-whitelist": "127.0.0.1",
            },
        )


class MainTests(unittest.TestCase):
    """main() runs at every container start, before the daemon: env vars in,
    settings.json out."""

    def setUp(self):
        self.path = self._new_settings_path()

    def _new_settings_path(self):
        return os.path.join(
            helpers.make_temp_dir(self, "configure_transmission_main_"),
            "settings.json",
        )

    def _run(self, **env):
        stderr = io.StringIO()
        with (
            unittest.mock.patch.dict(
                os.environ, {"TRANSMISSION_SETTINGS_FILE": self.path, **env}, clear=True
            ),
            contextlib.redirect_stderr(stderr),
        ):
            ct.main()
        return stderr.getvalue()

    def _write_settings(self, settings):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(settings, f)

    def _read_settings(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_first_run_with_credentials_writes_exactly_the_overrides(self):
        stderr = self._run(
            TRANSMISSION_RPC_USERNAME="alice", TRANSMISSION_RPC_PASSWORD="hunter2"
        )

        self.assertEqual(
            self._read_settings(),
            {
                "rpc-authentication-required": True,
                "rpc-username": "alice",
                "rpc-password": "hunter2",
                "port-forwarding-enabled": False,
            },
        )
        self.assertEqual(stderr, "")

    def test_existing_file_keeps_unrelated_keys_and_port_forwarding(self):
        self._write_settings(
            {"download-dir": "/downloads", "port-forwarding-enabled": True}
        )

        self._run(TRANSMISSION_PEER_LIMIT_GLOBAL="500")

        self.assertEqual(
            self._read_settings(),
            {
                "download-dir": "/downloads",
                "port-forwarding-enabled": True,
                "peer-limit-global": 500,
            },
        )

    def test_existing_file_and_no_overrides_is_left_untouched(self):
        self._write_settings({"download-dir": "/downloads"})
        with open(self.path, encoding="utf-8") as f:
            before = f.read()

        self._run()

        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_whitelist_without_credentials_warns_on_stderr(self):
        stderr = self._run(TRANSMISSION_RPC_WHITELIST="10.0.0.*")

        # The warning text itself is pinned by the whitelist warning tests above.
        self.assertRegex(
            stderr,
            r"\AWARNING: TRANSMISSION_RPC_WHITELIST is set .+ authentication\.\n\Z",
        )
        self.assertEqual(
            self._read_settings()["rpc-whitelist"], "127.0.0.1,::1,10.0.0.*"
        )

    def test_invalid_peer_limits_are_dropped_silently(self):
        # Pins current behavior; whether these should warn is a product call.
        for value in ("abc", "0"):
            with self.subTest(value=value):
                self.path = self._new_settings_path()

                stderr = self._run(TRANSMISSION_PEER_LIMIT_GLOBAL=value)

                self.assertEqual(
                    self._read_settings(), {"port-forwarding-enabled": False}
                )
                self.assertEqual(stderr, "")

    def test_corrupt_settings_file_starts_fresh(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        stderr = self._run(TRANSMISSION_RPC_WHITELIST="10.0.0.*")

        self.assertIn("starting fresh", stderr)
        self.assertEqual(
            self._read_settings(),
            {"rpc-whitelist-enabled": True, "rpc-whitelist": "127.0.0.1,::1,10.0.0.*"},
        )

    def test_running_the_script_calls_main(self):
        # entrypoint.sh runs it as a script, not as an import.
        with (
            unittest.mock.patch.dict(
                os.environ, {"TRANSMISSION_SETTINGS_FILE": self.path}, clear=True
            ),
        ):
            runpy.run_path(ct.__file__, run_name="__main__")

        self.assertEqual(self._read_settings(), {"port-forwarding-enabled": False})

    def test_default_settings_file_is_in_the_config_volume(self):
        self.assertEqual(ct.DEFAULT_SETTINGS_FILE, "/config/settings.json")

    def test_without_an_env_var_the_default_settings_file_is_used(self):
        # The default is patched to a temp path, so this never reads (or
        # depends on) a real /config/settings.json on the machine.
        with (
            unittest.mock.patch.object(ct, "DEFAULT_SETTINGS_FILE", self.path),
            unittest.mock.patch.dict(os.environ, {}, clear=True),
        ):
            ct.main()

        self.assertEqual(self._read_settings(), {"port-forwarding-enabled": False})

    def test_an_explicit_settings_path_wins_over_the_env_var(self):
        env_path = self._new_settings_path()
        with unittest.mock.patch.dict(
            os.environ, {"TRANSMISSION_SETTINGS_FILE": env_path}, clear=True
        ):
            ct.main(settings_path=self.path)

        self.assertEqual(self._read_settings(), {"port-forwarding-enabled": False})
        self.assertFalse(os.path.exists(env_path))


if __name__ == "__main__":
    unittest.main()
