from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from infra import health_monitor


class HealthMonitorTests(unittest.TestCase):
    def test_markdown_requires_markdown_content_type(self) -> None:
        ok, error, _ = health_monitor.evaluate_result(
            "/llms.txt",
            {"status": 200, "content_type": "text/plain", "body": b"# Site"},
        )
        self.assertFalse(ok)
        self.assertIn("text/plain", error)

    def test_sitemap_requires_xml_content_type_and_body(self) -> None:
        ok, error, _ = health_monitor.evaluate_result(
            "/sitemap.xml",
            {"status": 200, "content_type": "text/html", "body": b"<urlset />"},
        )
        self.assertFalse(ok)
        self.assertIn("text/html", error)

        ok, error, _ = health_monitor.evaluate_result(
            "/sitemap.xml",
            {"status": 200, "content_type": "application/xml", "body": b"<urlset />"},
        )
        self.assertTrue(ok, error)

    def test_full_health_requires_inventory_and_freshness(self) -> None:
        fresh_timestamp = datetime.now(timezone.utc).isoformat()
        ok, error, freshness = health_monitor.evaluate_result(
            "/__health/full",
            {
                "status": 200,
                "content_type": "application/json",
                "body": json.dumps(
                    {
                        "status": "ok",
                        "matchedInventory": 66,
                        "dealerVaultUpdatedAt": fresh_timestamp,
                        "catalogUpdatedAt": fresh_timestamp,
                        "agentQuery": {"status": "ok"},
                    }
                ).encode(),
            },
        )
        self.assertTrue(ok, error)
        self.assertIsNotNone(freshness)

    def test_agent_query_checks_require_markdown_and_valid_json_results(self) -> None:
        ok, error, _ = health_monitor.evaluate_result(
            "/llms?query=service&limit=1",
            {"status": 200, "content_type": "text/markdown", "body": b"# Results\n\nService"},
        )
        self.assertTrue(ok, error)

        ok, error, _ = health_monitor.evaluate_result(
            "/llms/json?query=service&limit=1",
            {
                "status": 200,
                "content_type": "application/json",
                "body": json.dumps(
                    {"schema": "motorinn.llmsQuery.v1", "resultCount": 1, "results": [{"id": "service"}]}
                ).encode(),
            },
        )
        self.assertTrue(ok, error)

        ok, error, _ = health_monitor.evaluate_result(
            "/llms/json?query=service&limit=1",
            {
                "status": 200,
                "content_type": "application/json",
                "body": json.dumps({"schema": "motorinn.llmsQuery.v1", "resultCount": 0, "results": []}).encode(),
            },
        )
        self.assertFalse(ok)
        self.assertIn("no valid query results", error)

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
