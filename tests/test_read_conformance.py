from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import agent_access
import requests
import server

from read_conformance import (
    HttpResult,
    ReadConformanceHarness,
    RequestsTransport,
    exit_code,
    load_client_evidence,
)


HOST = "ai.motorinnautogroup.com"
BASE = f"https://{HOST}"
VIN = "1G1ZD5ST1RF100001"


def response(status, payload, content_type="application/json"):
    body = json.dumps(payload).encode() if not isinstance(payload, str) else payload.encode()
    return HttpResult(status, {"Content-Type": content_type}, body)


def mcp_success(payload):
    return response(200, {"jsonrpc": "2.0", "id": "test", "result": {"structuredContent": payload, "content": [{"type": "text", "text": json.dumps(payload)}]}})


def mcp_error(code):
    payload = {"schema": "motorinn.error.v1", "error": {"code": code, "message": "unavailable", "retryable": True}}
    return response(200, {"jsonrpc": "2.0", "id": "test", "result": {"isError": True, "content": [{"type": "text", "text": json.dumps(payload)}]}})


class FixtureTransport:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, *, json_body=None):
        path = urlsplit(url).path
        query = urlsplit(url).query
        target = f"{path}?{query}" if query else path
        key = (method, target)
        if method == "POST":
            params = json_body.get("params", {})
            name = params.get("name") if json_body.get("method") == "tools/call" else json_body.get("method")
            key = (method, path, name)
        self.calls.append((method, path, json_body))
        if key not in self.routes:
            raise AssertionError(f"Unexpected request: {key}")
        return self.routes[key]


def fixture_routes():
    site = {"key": "motorinnautogroup", "name": "Motor Inn Auto Group", "host": HOST, "canonicalUrl": "https://www.motorinnautogroup.com"}
    vehicles = {"schema": "motorinn.vehicleSearch.v1", "site": site, "resultCount": 1, "nextCursor": None, "sourceFreshness": {}, "vehicles": [{"vin": VIN, "condition": "new"}]}
    locations = {
        "schema": "motorinn.locations.v1",
        "site": site,
        "locations": [{
            "brandContext": site,
            "contactResourceUrl": f"{BASE}/contact-hours.md",
            "contacts": [],
            "location": {"key": "carroll", "name": "Carroll", "timeZone": "America/Chicago", "address": {"streetAddress": "1526 Le Clark Road", "addressLocality": "Carroll", "addressRegion": "IA", "postalCode": "51401", "addressCountry": "US"}},
        }],
    }
    service = {
        "schema": "motorinn.capabilityInformation.v1",
        "site": site,
        "domain": "service",
        "capabilityState": "information_only",
        "actionUrl": "https://www.motorinnautogroup.com/service-locations.html",
        "serviceLocation": {"key": "carroll"},
    }
    parts = {
        "schema": "motorinn.capabilityInformation.v1",
        "site": site,
        "domain": "parts",
        "capabilityState": "requested_only",
        "actionUrl": "https://www.motorinnautogroup.com/orderparts.aspx",
    }
    tools = [
        {"name": name, "annotations": {"readOnlyHint": True, "destructiveHint": False}}
        for name in ["search_vehicles", "get_vehicle", "list_locations", "get_service_information", "get_parts_information"]
    ]
    required_paths = {
        path: {"get": {}}
        for path in [
            "/api/v1/vehicles",
            "/api/v1/vehicles/{vin}",
            "/api/v1/locations",
            "/api/v1/service-information",
            "/api/v1/parts-information",
        ]
    }
    return {
        ("GET", "/openapi.json"): response(200, {"openapi": "3.1.2", "servers": [{"url": BASE}], "paths": required_paths}),
        ("POST", "/mcp", "tools/list"): response(200, {"jsonrpc": "2.0", "id": "tools/list", "result": {"tools": tools}}),
        ("GET", "/llms.txt"): response(200, f"# Motor Inn\n- {BASE}/openapi.json\n- {BASE}/mcp\n", "text/markdown; charset=utf-8"),
        ("GET", "/api/v1/vehicles?limit=10"): response(200, vehicles),
        ("POST", "/mcp", "search_vehicles"): mcp_success(vehicles),
        ("GET", "/new-inventory.md"): response(200, f"# New\nVIN: {VIN}", "text/markdown"),
        ("GET", "/used-inventory.md"): response(200, "# Used", "text/markdown"),
        ("GET", "/api/v1/locations"): response(200, locations),
        ("POST", "/mcp", "list_locations"): mcp_success(locations),
        ("GET", "/contact-hours.md"): response(200, "1526 Le Clark Rd, Carroll, IA 51401", "text/markdown"),
        ("GET", "/api/v1/service-information"): response(200, service),
        ("POST", "/mcp", "get_service_information"): mcp_success(service),
        ("GET", "/api/v1/parts-information"): response(200, parts),
        ("POST", "/mcp", "get_parts_information"): mcp_success(parts),
        ("GET", "/service.md"): response(200, f"{service['actionUrl']}\n{parts['actionUrl']}", "text/markdown"),
        ("GET", "/llms-full.txt"): response(200, parts["actionUrl"], "text/markdown"),
    }


class ReadConformanceTests(unittest.TestCase):
    def test_network_timeout_becomes_bounded_failed_result(self):
        transport = RequestsTransport(timeout_seconds=0.1)
        with patch.object(transport.session, "request", side_effect=requests.Timeout("do not expose")):
            result = transport.request("GET", f"{BASE}/openapi.json")
        self.assertEqual(result.status, 0)
        self.assertEqual(result.body, b"")
        self.assertEqual(result.headers["X-Conformance-Error"], "Timeout")

    def test_deployable_public_pages_advertise_each_structured_parts_action(self):
        for site in server.SITES.values():
            action_url = agent_access.parts_information(site)["actionUrl"]
            self.assertIn(action_url, server.static_content(site, "service.md"))

    def test_fixture_passes_and_uses_only_get_and_read_mcp_posts(self):
        transport = FixtureTransport(fixture_routes())
        evidence = [{
            "schema": "motorinn.clientReadEvidence.v1",
            "client": "browser",
            "host": HOST,
            "capturedAt": "2026-08-31T15:00:00Z",
            "observations": {"locations": {"locationKeys": ["carroll"]}},
        }]

        report = ReadConformanceHarness(transport).run(
            [HOST], client_evidence=evidence, required_clients={"browser"}
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(exit_code(report), 0)
        self.assertTrue(all(method == "GET" or (method == "POST" and path == "/mcp") for method, path, _ in transport.calls))
        tool_names = {
            body["params"].get("name")
            for method, _, body in transport.calls
            if method == "POST" and body.get("method") == "tools/call"
        }
        self.assertEqual(tool_names, {"search_vehicles", "list_locations", "get_service_information", "get_parts_information"})

    def test_consistent_inventory_source_outage_is_degraded_not_passed(self):
        routes = fixture_routes()
        unavailable = {"schema": "motorinn.error.v1", "error": {"code": "source_unavailable", "message": "unavailable", "retryable": True}}
        routes[("GET", "/api/v1/vehicles?limit=10")] = response(503, unavailable)
        routes[("POST", "/mcp", "search_vehicles")] = mcp_error("source_unavailable")
        routes[("GET", "/new-inventory.md")] = response(503, "unavailable", "text/markdown")
        routes[("GET", "/used-inventory.md")] = response(503, "unavailable", "text/markdown")

        report = ReadConformanceHarness(FixtureTransport(routes)).run([HOST])

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(exit_code(report), 3)

    def test_http_mcp_difference_fails(self):
        routes = fixture_routes()
        changed = routes[("GET", "/api/v1/service-information")].json().copy()
        changed["capabilityState"] = "confirmed"
        routes[("POST", "/mcp", "get_service_information")] = mcp_success(changed)

        report = ReadConformanceHarness(FixtureTransport(routes)).run([HOST])

        self.assertEqual(report["status"], "fail")
        finding = next(f for f in report["hosts"][0]["findings"] if f["check"] == "service_http_mcp")
        self.assertEqual(finding["status"], "fail")

    def test_client_evidence_rejects_sensitive_values(self):
        document = {
            "schema": "motorinn.clientReadEvidence.v1",
            "client": "chatgpt",
            "host": HOST,
            "capturedAt": "2026-08-31T15:00:00Z",
            "accessToken": "must-not-be-stored",
            "observations": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "possible secret"):
                load_client_evidence([path])


if __name__ == "__main__":
    unittest.main()
