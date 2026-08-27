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
        environment = {}
        for suffix, site_key in (
            ("GROUP", "motorinnautogroup"),
            ("CHEVY", "motorinnchevy"),
            ("TOYOTA", "motorinntoyota"),
        ):
            environment[f"MOTORINN_XTIME_{suffix}_URL"] = (
                f"https://consumer.xtime.com/scheduling?webkey=secret-{suffix.casefold()}"
            )
            if active:
                environment[f"MOTORINN_XTIME_{suffix}_ACTIVE"] = "true"
            if verified:
                environment[f"MOTORINN_XTIME_{suffix}_VERIFIED_ROOFTOP"] = site_key
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
        self.assertEqual({site["site"] for site in payload["sites"]}, {
            "motorinnautogroup", "motorinnchevy", "motorinntoyota",
        })
        self.assertTrue(all(not site["configured"] for site in payload["sites"]))
        self.assertNotIn("webkey", result.stdout.casefold())
        self.assertNotIn("consumer.xtime.com", result.stdout.casefold())

    def test_configured_requirement_checks_all_rooftops_without_disclosing_urls(self):
        result = self.run_preflight(
            self.configured_environment(), requirement="configured"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["configurationValid"])
        self.assertTrue(payload["requirementSatisfied"])
        self.assertTrue(all(site["configured"] for site in payload["sites"]))
        self.assertTrue(all(not site["active"] for site in payload["sites"]))
        self.assertNotIn("secret-", result.stdout.casefold())
        self.assertNotIn("consumer.xtime.com", result.stdout.casefold())

    def test_invalid_active_configuration_fails_closed_without_disclosing_values(self):
        environment = self.configured_environment(active=True, verified=True)
        environment["MOTORINN_XTIME_TOYOTA_VERIFIED_ROOFTOP"] = "wrong-rooftop"

        result = self.run_preflight(environment, requirement="active")

        self.assertEqual(result.returncode, 2, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["configurationValid"])
        self.assertFalse(payload["requirementSatisfied"])
        toyota = next(site for site in payload["sites"] if site["site"] == "motorinntoyota")
        self.assertEqual(toyota["status"], "invalid")
        self.assertTrue(toyota["configured"])
        self.assertFalse(toyota["rooftopBindingVerified"])
        self.assertEqual(toyota["error"], "invalid_active_configuration")
        self.assertNotIn("wrong-rooftop", result.stdout.casefold())
        self.assertNotIn("secret-", result.stdout.casefold())

    def test_malformed_inactive_staging_and_activation_flags_are_invalid(self):
        staged = self.configured_environment()
        staged["MOTORINN_XTIME_TOYOTA_URL"] = (
            "https://evil.example/scheduling?webkey=do-not-print"
        )
        invalid_url = self.run_preflight(staged)

        self.assertEqual(invalid_url.returncode, 2, invalid_url.stderr)
        invalid_url_payload = json.loads(invalid_url.stdout)
        self.assertFalse(invalid_url_payload["configurationValid"])
        toyota = next(
            site for site in invalid_url_payload["sites"]
            if site["site"] == "motorinntoyota"
        )
        self.assertEqual(toyota["error"], "invalid_staged_url")
        self.assertNotIn("evil.example", invalid_url.stdout)
        self.assertNotIn("do-not-print", invalid_url.stdout)

        malformed_flag = self.configured_environment()
        malformed_flag["MOTORINN_XTIME_TOYOTA_ACTIVE"] = "tru"
        invalid_flag = self.run_preflight(malformed_flag)

        self.assertEqual(invalid_flag.returncode, 2, invalid_flag.stderr)
        invalid_flag_payload = json.loads(invalid_flag.stdout)
        self.assertFalse(invalid_flag_payload["configurationValid"])
        toyota = next(
            site for site in invalid_flag_payload["sites"]
            if site["site"] == "motorinntoyota"
        )
        self.assertEqual(toyota["error"], "invalid_activation_flag")
        self.assertFalse(toyota["active"])

    def test_active_requirement_succeeds_only_after_exact_rooftop_verification(self):
        result = self.run_preflight(
            self.configured_environment(active=True, verified=True),
            requirement="active",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["configurationValid"])
        self.assertTrue(payload["requirementSatisfied"])
        self.assertTrue(all(site["active"] for site in payload["sites"]))


if __name__ == "__main__":
    unittest.main()
