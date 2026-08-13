from __future__ import annotations

import json
import unittest

from infra import health_monitor


class HealthMonitorTests(unittest.TestCase):
    def test_markdown_requires_markdown_content_type(self) -> None:
        ok, error, _ = health_monitor.evaluate_result(
            "/llms.txt",
            {"status": 200, "content_type": "text/plain", "body": b"# Site"},
        )
        self.assertFalse(ok)
        self.assertIn("text/plain", error)

    def test_full_health_requires_inventory_and_freshness(self) -> None:
        ok, error, freshness = health_monitor.evaluate_result(
            "/__health/full",
            {
                "status": 200,
                "content_type": "application/json",
                "body": json.dumps(
                    {
                        "status": "ok",
                        "matchedInventory": 66,
                        "dealerVaultUpdatedAt": "2026-08-13T15:09:15+00:00",
                        "catalogUpdatedAt": "2026-08-12T21:01:48+00:00",
                    }
                ).encode(),
            },
        )
        self.assertTrue(ok, error)
        self.assertIsNotNone(freshness)

    def test_alerts_on_second_failure_and_once_on_recovery(self) -> None:
        host = "ai.motorinnautogroup.com"
        state, notifications = health_monitor.transition_state({"hosts": {}}, {host: False})
        self.assertEqual(notifications, [])
        state, notifications = health_monitor.transition_state(state, {host: False})
        self.assertEqual(notifications, [(host, "failed")])
        state, notifications = health_monitor.transition_state(state, {host: False})
        self.assertEqual(notifications, [])
        _, notifications = health_monitor.transition_state(state, {host: True})
        self.assertEqual(notifications, [(host, "recovered")])


if __name__ == "__main__":
    unittest.main()
