from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import server
import yaml
from jsonschema import Draft202012Validator

from muse_inventory import (
    DEFAULT_LOCATION_ID,
    MUSE_INVENTORY_ENABLED,
    UnsupportedInventoryFilter,
    map_public_vehicle,
    validate_inventory_filters,
)


NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
HEADERS = {
    "Host": "ai.motorinnofcarroll.com",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-11-25",
}
PUBLIC_VEHICLE = {
    "id": "C1",
    "vin": "1G1ZD5ST1RF123456",
    "stockNumber": "C1",
    "year": 2024,
    "make": "CHEVROLET",
    "model": "Malibu",
    "trim": "LT",
    "condition": "new",
    "advertisedPrice": {"amount": "25180.00", "sourceField": "internet_price"},
    "availability": "in stock",
    "site": {"key": "motorinnchevy"},
    "canonicalUrl": "https://www.motorinnofcarroll.com/vehicle/C1",
    "imageUrl": "https://images.example/C1.jpg",
    "sourceFreshness": {
        "dealerVaultUpdatedAt": "2026-10-19T11:00:00Z",
        "publicCatalogUpdatedAt": "2026-10-19T10:00:00Z",
        "dealerVaultTimestampBasis": "s3_object_last_modified",
        "publicCatalogTimestampBasis": "http_last_modified_or_retrieval_time",
    },
}


class MuseContextProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def test_customer_guide_is_linked_from_machine_discovery(self) -> None:
        guide = self.client.get("/agent-connection.md", headers={"Host": "ai.motorinnofcarroll.com"})
        llms = self.client.get("/llms.txt", headers={"Host": "ai.motorinnofcarroll.com"})
        self.assertEqual(guide.status_code, 200)
        self.assertIn("/mcp/customer", guide.get_data(as_text=True))
        self.assertIn("/agent-connection.md", llms.get_data(as_text=True))
        self.assertIn("/mcp/customer", llms.get_data(as_text=True))

    def mcp(self, path: str, method: str, params: dict, request_id: int = 1):
        return self.client.post(
            path,
            headers=HEADERS,
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )

    def test_context_profile_lists_only_context_tools_and_default_profile_is_unchanged(self) -> None:
        context = self.mcp("/mcp/context", "tools/list", {}).get_json()["result"]["tools"]
        default = self.mcp("/mcp", "tools/list", {}).get_json()["result"]["tools"]
        customer = self.mcp("/mcp/customer", "tools/list", {}).get_json()["result"]["tools"]

        self.assertEqual(
            {tool["name"] for tool in context},
            {"list_locations", "get_service_information", "get_parts_information", "search_public_website"},
        )
        self.assertEqual(
            {tool["name"] for tool in default},
            {"search_vehicles", "get_vehicle", "list_locations", "get_service_information", "get_parts_information"},
        )
        self.assertNotIn("search_public_website", {tool["name"] for tool in default})
        self.assertEqual(
            {tool["name"] for tool in customer},
            {"search_vehicles", "get_vehicle", "list_locations", "get_service_information", "get_parts_information", "search_public_website"},
        )
        by_name = {tool["name"]: tool for tool in customer}
        self.assertTrue(by_name["search_vehicles"]["annotations"]["openWorldHint"])
        self.assertTrue(by_name["get_vehicle"]["annotations"]["openWorldHint"])
        self.assertFalse(by_name["search_public_website"]["annotations"]["openWorldHint"])
        self.assertTrue(all(tool["outputSchema"]["type"] == "object" for tool in customer))

    def test_customer_profile_supports_standard_initialize_list_and_inventory_call(self) -> None:
        initialize = self.mcp(
            "/mcp/customer",
            "initialize",
            {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "fixture-client", "version": "1"}},
        )
        listed = self.mcp("/mcp/customer", "tools/list", {}).get_json()["result"]["tools"]
        calls = [
            {"name": "search_vehicles", "arguments": {"condition": "new", "limit": 5}},
            {"name": "search_public_website", "arguments": {"query": "service", "limit": 3}},
        ]
        with patch(
            "server.api_inventory_search",
            return_value={"schema": "motorinn.vehicleSearch.v1", "vehicles": [], "resultCount": 0},
        ):
            inventory = self.mcp("/mcp/customer", "tools/call", calls[0]).get_json()["result"]
        context = self.mcp("/mcp/customer", "tools/call", calls[1]).get_json()["result"]

        self.assertEqual(initialize.get_json()["result"]["protocolVersion"], "2025-11-25")
        self.assertIn("tools", initialize.get_json()["result"]["capabilities"])
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in listed))
        self.assertEqual(inventory["structuredContent"]["schema"], "motorinn.vehicleSearch.v1")
        self.assertEqual(context["structuredContent"]["resultCount"] > 0, True)
        self.assertTrue(all(result["sourceType"] == "static" for result in context["structuredContent"]["results"]))

    def test_context_search_uses_only_static_documents_and_validates_its_output(self) -> None:
        with (
            patch("server.build_query_documents", side_effect=AssertionError("mixed query index used")),
            patch("server.render_inventory", side_effect=AssertionError("inventory renderer used")),
            patch("server.rendered_offers", side_effect=AssertionError("offers renderer used")),
            patch("server.load_catalog", side_effect=AssertionError("catalog loaded")),
            patch("server.load_private_inventory", side_effect=AssertionError("inventory loaded")),
        ):
            response = self.mcp(
                "/mcp/context",
                "tools/call",
                {"name": "search_public_website", "arguments": {"query": "service", "limit": 3}},
            )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()["result"]["structuredContent"]
        self.assertGreater(result["resultCount"], 0)
        self.assertTrue(all(item["sourceType"] == "static" for item in result["results"]))
        tool = next(tool for tool in server.mcp_tools("context-only") if tool["name"] == "search_public_website")
        Draft202012Validator(tool["outputSchema"]).validate(result)

    def test_context_search_never_loads_dynamic_sources_for_inventory_or_offer_terms_or_urls(self) -> None:
        queries = [
            "new inventory in stock",
            "current offers specials",
            "https://ai.motorinnofcarroll.com/new-inventory.md",
            "https://ai.motorinnofcarroll.com/offers.md",
        ]
        with (
            patch("server.build_query_documents", side_effect=AssertionError("mixed query index used")),
            patch("server.render_inventory", side_effect=AssertionError("inventory renderer used")),
            patch("server.rendered_offers", side_effect=AssertionError("offers renderer used")),
            patch("server.load_catalog", side_effect=AssertionError("catalog loaded")),
            patch("server.load_private_inventory", side_effect=AssertionError("inventory loaded")),
        ):
            for index, query in enumerate(queries, start=1):
                response = self.mcp(
                    "/mcp/context",
                    "tools/call",
                    {"name": "search_public_website", "arguments": {"query": query}},
                    request_id=index,
                )
                self.assertEqual(response.status_code, 200)
                result = response.get_json()["result"]["structuredContent"]
                self.assertTrue(all(item["sourceType"] == "static" for item in result["results"]))

    def test_context_profile_has_no_resources_or_prompts_and_repeated_bad_calls_do_not_enable_mapper(self) -> None:
        for index, method in enumerate(("resources/list", "prompts/list"), start=1):
            response = self.mcp("/mcp/context", method, {}, request_id=index).get_json()
            self.assertEqual(response["error"]["code"], -32601)

        bad_calls = [
            {"name": "search_vehicles", "arguments": {"condition": "new"}},
            {"name": "get_vehicle", "arguments": {"vin": "1G1ZD5ST1RF123456"}},
            {"name": "search_public_website", "arguments": {"query": "   "}},
        ]
        for index in range(3, 18):
            bad = bad_calls[index % len(bad_calls)]
            self.mcp("/mcp/context", "tools/call", bad, request_id=index)
        self.assertFalse(MUSE_INVENTORY_ENABLED)
        self.assertNotIn("search_inventory", {tool["name"] for tool in server.mcp_tools("context-only")})
        self.assertNotIn("search_inventory", {tool["name"] for tool in server.mcp_tools()})

    def test_structured_context_tools_remain_readable_without_inventory(self) -> None:
        calls = [
            {"name": "list_locations", "arguments": {}},
            {"name": "get_service_information", "arguments": {}},
            {"name": "get_parts_information", "arguments": {}},
        ]
        with (
            patch("server.load_catalog", side_effect=AssertionError("catalog loaded")),
            patch("server.load_private_inventory", side_effect=AssertionError("inventory loaded")),
        ):
            for index, arguments in enumerate(calls, start=1):
                response = self.mcp(
                    "/mcp/context",
                    "tools/call",
                    {"name": arguments["name"], "arguments": arguments["arguments"]},
                    request_id=index,
                )
                self.assertIn("structuredContent", response.get_json()["result"])

    def test_context_profile_rejects_unknown_fields_and_inventory_tools(self) -> None:
        unknown = self.mcp(
            "/mcp/context",
            "tools/call",
            {"name": "search_public_website", "arguments": {"query": "service", "include_inventory": True}},
        ).get_json()["result"]
        invalid_query = self.mcp(
            "/mcp/context",
            "tools/call",
            {"name": "search_public_website", "arguments": {"query": "   "}},
            request_id=3,
        ).get_json()["result"]
        inventory_tool = self.mcp(
            "/mcp/context",
            "tools/call",
            {"name": "search_vehicles", "arguments": {"condition": "new"}},
            request_id=2,
        ).get_json()
        self.assertTrue(unknown["isError"])
        self.assertEqual(json.loads(unknown["content"][0]["text"])["error"]["code"], "invalid_request")
        self.assertTrue(invalid_query["isError"])
        self.assertEqual(json.loads(invalid_query["content"][0]["text"])["error"]["code"], "invalid_request")
        self.assertIn("error", inventory_tool)
        self.assertEqual(inventory_tool["error"]["code"], -32602)

    def test_muse_inventory_projection_uses_unknowns_and_no_photos_or_unverified_price(self) -> None:
        mapped = map_public_vehicle({**PUBLIC_VEHICLE, "cost": 19000, "internal_notes": "never expose"}, checked_at=NOW)
        self.assertEqual(mapped["location_id"], DEFAULT_LOCATION_ID)
        self.assertTrue(mapped["vehicle_id"].startswith("carroll_"))
        self.assertEqual(mapped["availability"], "unknown")
        self.assertEqual(mapped["public_price"]["amount_minor"], None)
        self.assertEqual(mapped["public_price"]["basis"], "call_for_price")
        self.assertIsNone(mapped["freshness"]["source_updated_at"])
        self.assertIsNone(mapped["freshness"]["ingested_at"])
        self.assertEqual(mapped["freshness"]["basis"], "ingestion_only")
        self.assertEqual(mapped["freshness"]["state"], "unknown")
        self.assertEqual(mapped["image_urls"], [])
        self.assertTrue(all(value is None for value in (
            mapped["body_style"], mapped["drivetrain"], mapped["powertrain"], mapped["fuel"],
            mapped["exterior_color"], mapped["interior_color"], mapped["odometer"],
        )))
        self.assertNotIn("imageUrl", mapped)
        self.assertNotIn("advertisedPrice", mapped)
        self.assertNotIn("cost", mapped)
        self.assertNotIn("internal_notes", mapped)
        self.assertFalse(MUSE_INVENTORY_ENABLED)

    def test_muse_inventory_projection_rejects_bad_urls_and_unsupported_price_filters(self) -> None:
        with self.assertRaises(ValueError):
            map_public_vehicle({**PUBLIC_VEHICLE, "canonicalUrl": "http://dealer.example/vehicle"}, checked_at=NOW)
        with self.assertRaises(ValueError):
            map_public_vehicle(
                {
                    **PUBLIC_VEHICLE,
                    "sourceFreshness": {
                        **PUBLIC_VEHICLE["sourceFreshness"],
                        "dealerVaultTimestampBasis": "supplier_source_updated_at",
                    },
                },
                checked_at=NOW,
            )
        validate_inventory_filters({"condition": "used"})
        with self.assertRaises(UnsupportedInventoryFilter):
            validate_inventory_filters({"max_price_minor": 3000000})
        with self.assertRaises(UnsupportedInventoryFilter):
            validate_inventory_filters({"include_inventory_private_columns": True})


if __name__ == "__main__":
    unittest.main()
