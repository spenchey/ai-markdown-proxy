from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "tools" / "xtime_preflight.py"


class XtimePreflightTests(unittest.TestCase):
    @staticmethod
    def configured_environment(active=False, verified=False):
        environment = {
            "MOTORINN_XTIME_CARROLL_URL": (
                "https://consumer.xtime.com/scheduling?webkey=secret-carroll"
            )
        }
        if active:
            environment["MOTORINN_XTIME_CARROLL_ACTIVE"] = "true"
        if verified:
            environment["MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION"] = "carroll"
        return environment

    def run_preflight(self, extra_env=None, requirement="none"):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("MOTORINN_XTIME_")
        }
        environment.update(extra_env or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--require", requirement],
            cwd=REPOSITORY,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_unconfigured_preflight_is_safe_and_does_not_print_provider_urls(self):
        result = self.run_preflight()

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "motorinn.xtimePreflight.v1")
        self.assertTrue(payload["configurationValid"])
        self.assertTrue(payload["requirementSatisfied"])
        self.assertEqual(len(payload["locations"]), 1)
        location = payload["locations"][0]
        self.assertEqual(location["location"], "carroll")
        self.assertEqual(location["name"], "Carroll")
        self.assertFalse(location["configured"])
        self.assertEqual(len(location["stableHandoffUrls"]), 3)
        self.assertNotIn("webkey", result.stdout.casefold())
        self.assertNotIn("consumer.xtime.com", result.stdout.casefold())

    def test_configured_requirement_checks_carroll_without_disclosing_urls(self):
        result = self.run_preflight(
            self.configured_environment(), requirement="configured"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["configurationValid"])
        self.assertTrue(payload["requirementSatisfied"])
        location = payload["locations"][0]
        self.assertTrue(location["configured"])
        self.assertFalse(location["active"])
        self.assertNotIn("secret-", result.stdout.casefold())
        self.assertNotIn("consumer.xtime.com", result.stdout.casefold())

    def test_invalid_active_configuration_fails_closed_without_disclosing_values(self):
        environment = self.configured_environment(active=True, verified=True)
        environment["MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION"] = "wrong-location"

        result = self.run_preflight(environment, requirement="active")

        self.assertEqual(result.returncode, 2, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["configurationValid"])
        self.assertFalse(payload["requirementSatisfied"])
        location = payload["locations"][0]
        self.assertEqual(location["status"], "invalid")
        self.assertTrue(location["configured"])
        self.assertFalse(location["locationBindingVerified"])
        self.assertEqual(location["error"], "invalid_active_configuration")
        self.assertNotIn("wrong-location", result.stdout.casefold())
        self.assertNotIn("secret-", result.stdout.casefold())

    def test_malformed_inactive_staging_and_activation_flags_are_invalid(self):
        staged = self.configured_environment()
        staged["MOTORINN_XTIME_CARROLL_URL"] = (
            "https://evil.example/scheduling?webkey=do-not-print"
        )
        invalid_url = self.run_preflight(staged)

        self.assertEqual(invalid_url.returncode, 2, invalid_url.stderr)
        invalid_url_payload = json.loads(invalid_url.stdout)
        self.assertFalse(invalid_url_payload["configurationValid"])
        location = invalid_url_payload["locations"][0]
        self.assertEqual(location["error"], "invalid_staged_url")
        self.assertNotIn("evil.example", invalid_url.stdout)
        self.assertNotIn("do-not-print", invalid_url.stdout)

        malformed_flag = self.configured_environment()
        malformed_flag["MOTORINN_XTIME_CARROLL_ACTIVE"] = "tru"
        invalid_flag = self.run_preflight(malformed_flag)

        self.assertEqual(invalid_flag.returncode, 2, invalid_flag.stderr)
        invalid_flag_payload = json.loads(invalid_flag.stdout)
        self.assertFalse(invalid_flag_payload["configurationValid"])
        location = invalid_flag_payload["locations"][0]
        self.assertEqual(location["error"], "invalid_activation_flag")
        self.assertFalse(location["active"])

    def test_active_requirement_succeeds_only_after_exact_location_verification(self):
        result = self.run_preflight(
            self.configured_environment(active=True, verified=True),
            requirement="active",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["configurationValid"])
        self.assertTrue(payload["requirementSatisfied"])
        location = payload["locations"][0]
        self.assertTrue(location["locationBindingVerified"])
        self.assertTrue(location["active"])


if __name__ == "__main__":
    unittest.main()
