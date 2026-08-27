from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import server
import yaml
from jsonschema import Draft202012Validator


NOW = datetime(2026, 8, 27, 15, 30, tzinfo=timezone.utc)
CHEVY_VIN = "1G1ZD5ST1RF123456"
TOYOTA_VIN = "5TFJA5DB0RX123456"


PUBLIC_ROWS = [
    {
        "id": "C1",
        "stock_number": "C1",
        "vin": CHEVY_VIN,
        "condition": "new",
        "availability": "in stock",
        "vehicle_year": "2024",
        "vehicle_make": "CHEVROLET",
        "vehicle_model": "Malibu",
        "vehicle_trim": "LT",
        "link": "https://www.motorinnofcarroll.com/vehicle/C1?utm_source=test",
        "image_link": "https://images.example/C1.jpg",
    },
    {
        "id": "T1",
        "stock_number": "T1",
        "vin": TOYOTA_VIN,
        "condition": "new",
        "availability": "available",
        "vehicle_year": "2024",
        "vehicle_make": "TOYOTA",
        "vehicle_model": "Tundra",
        "vehicle_trim": "SR5",
        "link": "https://www.motorinntoyotaofcarroll.com/vehicle/T1",
        "image_link": "https://images.example/T1.jpg",
    },
]

PRIVATE_ROWS = [
    {
        "stock_number": "C1",
        "vin": CHEVY_VIN,
        "internet_price": "25000",
        "cost": "19000",
        "customer_email": "private@example.com",
        "internal_notes": "do not expose",
    },
    {
        "stock_number": "T1",
        "vin": TOYOTA_VIN,
        "list_price": "50000",
        "cost": "41000",
    },
]


class AgentAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        server._catalog_cache.clear()
        server._inventory_cache.clear()
        with server._query_rate_lock:
            server._query_rate_limits.clear()
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def inventory_sources(self):
        return (
            patch("server.load_catalog", return_value=(PUBLIC_ROWS, NOW)),
            patch("server.load_private_inventory", return_value=(PRIVATE_ROWS, NOW)),
        )

    def test_openapi_is_host_scoped_and_describes_only_live_reads(self) -> None:
        class UniqueKeyLoader(yaml.SafeLoader):
            pass

        def construct_unique_mapping(loader, node, deep=False):
            mapping = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in mapping:
                    raise AssertionError(f"duplicate OpenAPI key: {key}")
                mapping[key] = loader.construct_object(value_node, deep=deep)
            return mapping

        UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping)
        yaml.load(server.OPENAPI_PATH.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        response = self.client.get("/openapi.json", headers={"Host": "ai.motorinnofcarroll.com"})
        document = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "application/json")
        self.assertEqual(document["openapi"], "3.1.2")
        self.assertEqual(document["servers"], [{"url": "https://ai.motorinnofcarroll.com", "description": "Motor Inn of Carroll read-only mirror"}])
        self.assertIn("/api/v1/vehicles", document["paths"])
        self.assertIn("/service-scheduler", document["paths"])
        handoff_responses = document["paths"]["/service-scheduler"]["get"]["responses"]
        self.assertIn("302", handoff_responses)
        self.assertIn("503", handoff_responses)
        service_schema = document["components"]["schemas"]["ServiceInformationResponse"]
        service_required = service_schema["allOf"][1]["required"]
        self.assertIn("serviceLocation", service_required)
        self.assertIn("stableHandoffUrl", service_required)
        self.assertIn("providerTransition", service_required)
        provider_transition = document["components"]["schemas"]["ProviderTransition"]
        self.assertIn("locationBindingVerified", provider_transition["required"])
        self.assertNotIn("rooftopBindingVerified", provider_transition["properties"])
        service_examples = document["paths"]["/api/v1/service-information"]["get"]["responses"]["200"]["content"]["application/json"]["examples"]
        for example in service_examples.values():
            self.assertEqual(example["value"]["serviceLocation"]["key"], "carroll")
            self.assertEqual(
                example["value"]["providerTransition"]["locationKey"],
                "carroll",
            )
        self.assertTrue(all(set(path_item) <= {"get"} for path_item in document["paths"].values()))
        self.assertIn("ETag", response.headers)
        self.assertIn("/openapi.json", self.client.get("/llms.txt", headers={"Host": "ai.motorinnofcarroll.com"}).get_data(as_text=True))
        self.assertIn("/openapi.json", self.client.get("/sitemap.xml", headers={"Host": "ai.motorinnofcarroll.com"}).get_data(as_text=True))
        self.assertNotIn("/mcp", self.client.get("/sitemap.xml", headers={"Host": "ai.motorinnofcarroll.com"}).get_data(as_text=True))
        self.assertIn("500", document["paths"]["/api/v1/vehicles"]["get"]["responses"])

        with patch("server.openapi_document", side_effect=RuntimeError("internal detail must not escape")):
            failed = self.client.get("/openapi.json", headers={"Host": "ai.motorinnofcarroll.com"})
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.content_type, "application/json")
        self.assertEqual(failed.get_json()["error"]["code"], "internal_error")

    def test_vehicle_search_is_rooftop_scoped_and_projects_only_public_fields(self) -> None:
        catalog, inventory = self.inventory_sources()
        with catalog, inventory:
            response = self.client.get(
                "/api/v1/vehicles?condition=new&limit=25",
                headers={"Host": "ai.motorinntoyotaofcarroll.com"},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["schema"], "motorinn.vehicleSearch.v1")
        self.assertEqual(payload["resultCount"], 1)
        self.assertEqual(payload["sourceFreshness"], {"dealerVaultUpdatedAt": "2026-08-27T15:30:00Z", "publicCatalogUpdatedAt": "2026-08-27T15:30:00Z"})
        vehicle = payload["vehicles"][0]
        self.assertEqual(vehicle["vin"], TOYOTA_VIN)
        self.assertEqual(vehicle["advertisedPrice"]["amount"], "50180.00")
        self.assertTrue(vehicle["advertisedPrice"]["includesDocumentaryFee"])
        self.assertEqual(set(vehicle), {
            "id", "vin", "stockNumber", "year", "make", "model", "trim", "condition",
            "advertisedPrice", "availability", "site", "canonicalUrl", "imageUrl", "sourceFreshness",
        })
        self.assertNotIn("cost", json.dumps(payload))
        self.assertNotIn("private@example.com", json.dumps(payload))
        self.assertNotIn("utm_source", json.dumps(payload))

    def test_malformed_catalog_rows_do_not_escape_the_public_schema(self) -> None:
        malformed = {
            "id": "BAD",
            "stock_number": "BAD",
            "vin": "1G1ZD5ST9RF999999",
            "condition": "new",
            "vehicle_year": "2024",
            "vehicle_make": "CHEVROLET",
            "vehicle_model": "Malibu",
            "link": "https://[",
            "image_link": "https://images.example/BAD.jpg",
        }
        public_with_bad_image = {**PUBLIC_ROWS[0], "image_link": "https://["}
        credentialed_link = {**PUBLIC_ROWS[0], "id": "CREDS", "stock_number": "CREDS", "vin": "1G1ZD5ST5RF555555", "link": "https://agent:secret@www.motorinnofcarroll.com/vehicle/CREDS"}
        credentialed_image = {**public_with_bad_image, "image_link": "https://imguser:imgsecret@images.example/C1.jpg"}
        with patch("server.load_catalog", return_value=([malformed, credentialed_link, credentialed_image], NOW)), patch(
            "server.load_private_inventory",
            return_value=([{"stock_number": "BAD", "vin": malformed["vin"], "internet_price": "1"}, {"stock_number": "CREDS", "vin": credentialed_link["vin"], "internet_price": "1"}, PRIVATE_ROWS[0]], NOW),
        ):
            response = self.client.get("/api/v1/vehicles?condition=new", headers={"Host": "ai.motorinnofcarroll.com"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([vehicle["vin"] for vehicle in response.get_json()["vehicles"]], [CHEVY_VIN])
        self.assertIsNone(response.get_json()["vehicles"][0]["imageUrl"])

    def test_rooftop_host_rules_allow_group_new_vdps_but_not_cross_rooftop_or_unassigned_used(self) -> None:
        group_new = {**PUBLIC_ROWS[0], "link": "https://www.motorinnautogroup.com/vehicle/C1"}
        cross_new = {**PUBLIC_ROWS[0], "id": "CROSS", "stock_number": "CROSS", "vin": "1G1ZD5ST8RF888888", "link": "https://www.motorinntoyotaofcarroll.com/vehicle/CROSS"}
        group_used = {**PUBLIC_ROWS[0], "id": "USED", "stock_number": "USED", "vin": "1G1ZD5ST7RF777777", "condition": "used", "link": "https://www.motorinnautogroup.com/vehicle/USED"}
        private = [PRIVATE_ROWS[0], {"stock_number": "CROSS", "vin": cross_new["vin"], "internet_price": "25000"}, {"stock_number": "USED", "vin": group_used["vin"], "internet_price": "20000"}]
        with patch("server.load_catalog", return_value=([group_new, cross_new, group_used], NOW)), patch("server.load_private_inventory", return_value=(private, NOW)):
            chevy_new = self.client.get("/api/v1/vehicles?condition=new", headers={"Host": "ai.motorinnofcarroll.com"}).get_json()
            chevy_used = self.client.get("/api/v1/vehicles?condition=used", headers={"Host": "ai.motorinnofcarroll.com"}).get_json()
            group = self.client.get("/api/v1/vehicles?condition=used", headers={"Host": "ai.motorinnautogroup.com"}).get_json()
        self.assertEqual([row["vin"] for row in chevy_new["vehicles"]], [CHEVY_VIN])
        self.assertEqual(chevy_used["resultCount"], 0)
        self.assertEqual([row["vin"] for row in group["vehicles"]], [group_used["vin"]])

    def test_identifier_collisions_fail_closed_instead_of_mixing_prices(self) -> None:
        mismatched = [
            {"stock_number": "C1", "vin": "1G1ZD5ST6RF666666", "internet_price": "1"},
            {"stock_number": "OTHER", "vin": CHEVY_VIN, "internet_price": "30000"},
        ]
        with patch("server.load_catalog", return_value=([PUBLIC_ROWS[0]], NOW)), patch("server.load_private_inventory", return_value=(mismatched, NOW)):
            response = self.client.get("/api/v1/vehicles", headers={"Host": "ai.motorinnofcarroll.com"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "source_unavailable")

    def test_vehicle_filters_and_detail_fail_closed_across_rooftops(self) -> None:
        catalog, inventory = self.inventory_sources()
        with catalog, inventory:
            filtered = self.client.get(
                "/api/v1/vehicles?condition=new&make=CHEVROLET&model=Malibu&minPrice=25180&maxPrice=25180",
                headers={"Host": "ai.motorinnofcarroll.com"},
            )
            wrong_rooftop = self.client.get(
                f"/api/v1/vehicles/{CHEVY_VIN}",
                headers={"Host": "ai.motorinntoyotaofcarroll.com"},
            )

        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.get_json()["vehicles"][0]["vin"], CHEVY_VIN)
        self.assertEqual(wrong_rooftop.status_code, 404)
        self.assertEqual(wrong_rooftop.get_json()["error"]["code"], "not_found")

    def test_inventory_source_failure_uses_typed_api_error(self) -> None:
        with patch("server.load_catalog", side_effect=server.SourceUnavailable("catalog stale")):
            response = self.client.get("/api/v1/vehicles", headers={"Host": "ai.motorinnofcarroll.com"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {
            "schema": "motorinn.error.v1",
            "error": {
                "code": "source_unavailable",
                "message": "Public inventory sources are temporarily unavailable",
                "retryable": True,
            },
        })

    def test_vehicle_pagination_is_opaque_stable_and_filter_bound(self) -> None:
        second_public = {
            **PUBLIC_ROWS[0],
            "id": "C2",
            "stock_number": "C2",
            "vin": "1G1ZD5ST2RF123457",
            "vehicle_model": "Trax",
            "link": "https://www.motorinnofcarroll.com/vehicle/C2",
        }
        second_private = {"stock_number": "C2", "vin": second_public["vin"], "internet_price": "27000"}
        with patch("server.load_catalog", return_value=([PUBLIC_ROWS[0], second_public], NOW)), patch(
            "server.load_private_inventory", return_value=([PRIVATE_ROWS[0], second_private], NOW)
        ):
            first = self.client.get(
                "/api/v1/vehicles?condition=new&limit=1",
                headers={"Host": "ai.motorinnofcarroll.com"},
            ).get_json()
            second = self.client.get(
                f"/api/v1/vehicles?condition=new&limit=1&cursor={first['nextCursor']}",
                headers={"Host": "ai.motorinnofcarroll.com"},
            ).get_json()
            mismatched = self.client.get(
                f"/api/v1/vehicles?condition=used&limit=1&cursor={first['nextCursor']}",
                headers={"Host": "ai.motorinnofcarroll.com"},
            )

        self.assertEqual(first["resultCount"], 1)
        self.assertIsNotNone(first["nextCursor"])
        self.assertNotEqual(first["vehicles"][0]["vin"], second["vehicles"][0]["vin"])
        self.assertIsNone(second["nextCursor"])
        self.assertEqual(mismatched.status_code, 400)
        self.assertEqual(mismatched.get_json()["error"]["code"], "invalid_request")

        with patch("server.load_catalog", return_value=([PUBLIC_ROWS[0], second_public], NOW)), patch(
            "server.load_private_inventory", return_value=([PRIVATE_ROWS[0], second_private], NOW + timedelta(minutes=1))
        ):
            stale = self.client.get(
                f"/api/v1/vehicles?condition=new&limit=1&cursor={first['nextCursor']}",
                headers={"Host": "ai.motorinnofcarroll.com"},
            )
        self.assertEqual(stale.status_code, 400)
        self.assertIn("stale", stale.get_json()["error"]["message"])

    def test_api_validation_and_known_host_cannot_be_overridden(self) -> None:
        catalog, inventory = self.inventory_sources()
        with catalog, inventory:
            invalid = self.client.get(
                "/api/v1/vehicles?limit=26&minPrice=-1",
                headers={"Host": "ai.motorinnofcarroll.com"},
            )
            cannot_override = self.client.get(
                "/api/v1/vehicles?site=motorinntoyota&condition=new",
                headers={"Host": "ai.motorinnofcarroll.com"},
            )

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["error"]["code"], "invalid_request")
        self.assertEqual(cannot_override.status_code, 200)
        self.assertEqual(cannot_override.get_json()["site"]["key"], "motorinnchevy")
        self.assertEqual([vehicle["make"] for vehicle in cannot_override.get_json()["vehicles"]], ["CHEVROLET"])

    def test_locations_preserve_toyota_phone_ambiguity(self) -> None:
        response = self.client.get("/api/v1/locations", headers={"Host": "ai.motorinntoyotaofcarroll.com"})
        contacts = {item["department"]: item for item in response.get_json()["locations"][0]["contacts"]}

        self.assertEqual(response.status_code, 200)
        self.assertEqual(contacts["sales"]["status"], "unresolved")
        self.assertIsNone(contacts["sales"]["number"])
        self.assertEqual(contacts["service"]["number"], "712-513-1068")

    def test_location_api_keeps_brand_context_but_returns_one_carroll_location(self) -> None:
        responses = [
            self.client.get("/api/v1/locations", headers={"Host": host}).get_json()
            for host in (
                "ai.motorinnautogroup.com",
                "ai.motorinnofcarroll.com",
                "ai.motorinntoyotaofcarroll.com",
            )
        ]

        self.assertEqual(
            {response["site"]["key"] for response in responses},
            {"motorinnautogroup", "motorinnchevy", "motorinntoyota"},
        )
        self.assertEqual(
            {
                json.dumps(response["locations"][0]["location"], sort_keys=True)
                for response in responses
            },
            {json.dumps({
                "key": "carroll",
                "name": "Carroll",
                "address": {
                    "streetAddress": "1526 Le Clark Road",
                    "addressLocality": "Carroll",
                    "addressRegion": "IA",
                    "postalCode": "51401",
                    "addressCountry": "US",
                },
                "timeZone": "America/Chicago",
            }, sort_keys=True)},
        )
        self.assertTrue(all(
            response["locations"][0]["brandContext"] == response["site"]
            for response in responses
        ))

    def test_group_service_fallback_asks_for_brand_journey_not_location(self) -> None:
        response = self.client.get(
            "/api/v1/service-information",
            headers={"Host": "ai.motorinnautogroup.com"},
        ).get_json()

        self.assertEqual(response["capabilityState"], "information_only")
        self.assertEqual(response["authoritativeSystem"], "Motor Inn Carroll service page")
        self.assertIn("Carroll location", response["notice"])
        self.assertIn("Chevrolet or Toyota service journey", response["notice"])
        self.assertNotIn("choose a rooftop", response["notice"].casefold())

    def test_service_and_parts_report_current_authority_and_planned_xtime_transition(self) -> None:
        chevy = self.client.get("/api/v1/service-information", headers={"Host": "ai.motorinnofcarroll.com"}).get_json()
        toyota = self.client.get("/api/v1/service-information", headers={"Host": "ai.motorinntoyotaofcarroll.com"}).get_json()
        parts = self.client.get("/api/v1/parts-information", headers={"Host": "ai.motorinnofcarroll.com"}).get_json()

        self.assertEqual(chevy["capabilityState"], "external_handoff")
        self.assertEqual(chevy["authoritativeSystem"], "GM Online Service Scheduling")
        self.assertEqual(toyota["capabilityState"], "requested_only")
        self.assertEqual(toyota["authoritativeSystem"], "DealerOn appointment request form")
        self.assertEqual(toyota["providerTransition"], {
            "targetProvider": "Xtime Schedule by Cox Automotive",
            "locationKey": "carroll",
            "status": "planned",
            "configured": False,
            "locationBindingVerified": False,
            "active": False,
        })
        self.assertEqual(parts["capabilityState"], "requested_only")
        self.assertFalse(parts["availableOperations"]["confirm"])
        self.assertIn("not a stock check", parts["notice"])

    def test_all_site_brands_share_the_single_carroll_service_location(self) -> None:
        responses = [
            self.client.get(
                "/api/v1/service-information",
                headers={"Host": host},
            ).get_json()
            for host in (
                "ai.motorinnautogroup.com",
                "ai.motorinnofcarroll.com",
                "ai.motorinntoyotaofcarroll.com",
            )
        ]

        self.assertEqual(
            {response["site"]["key"] for response in responses},
            {"motorinnautogroup", "motorinnchevy", "motorinntoyota"},
        )
        self.assertEqual(
            {json.dumps(response["serviceLocation"], sort_keys=True) for response in responses},
            {
                json.dumps({
                    "key": "carroll",
                    "name": "Carroll",
                    "address": {
                        "streetAddress": "1526 Le Clark Road",
                        "addressLocality": "Carroll",
                        "addressRegion": "IA",
                        "postalCode": "51401",
                        "addressCountry": "US",
                    },
                    "timeZone": "America/Chicago",
                }, sort_keys=True)
            },
        )
        self.assertTrue(all(
            response["providerTransition"]["locationKey"] == "carroll"
            for response in responses
        ))

    def test_one_verified_carroll_xtime_configuration_serves_every_site_brand(self) -> None:
        environment = {
            "MOTORINN_XTIME_CARROLL_URL": "https://consumer.xtime.com/scheduling/?webkey=carroll-key",
            "MOTORINN_XTIME_CARROLL_ACTIVE": "true",
            "MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION": "carroll",
        }
        hosts = (
            "ai.motorinnautogroup.com",
            "ai.motorinnofcarroll.com",
            "ai.motorinntoyotaofcarroll.com",
        )

        with patch.dict("server.os.environ", environment, clear=False):
            responses = [
                self.client.get(
                    "/api/v1/service-information",
                    headers={"Host": host},
                ).get_json()
                for host in hosts
            ]
            handoffs = [
                self.client.get(
                    "/service-scheduler",
                    headers={"Host": host},
                )
                for host in hosts
            ]

        self.assertTrue(all(
            response["providerTransition"]["active"] is True
            for response in responses
        ))
        self.assertEqual(
            {response["actionUrl"] for response in responses},
            {environment["MOTORINN_XTIME_CARROLL_URL"]},
        )
        self.assertTrue(all(response.status_code == 302 for response in handoffs))
        self.assertEqual(
            {response.headers["Location"] for response in handoffs},
            {environment["MOTORINN_XTIME_CARROLL_URL"]},
        )

    def test_stable_service_handoff_keeps_current_scheduler_until_verified_cutover(self) -> None:
        current = self.client.get(
            "/service-scheduler",
            headers={"Host": "ai.motorinntoyotaofcarroll.com"},
        )

        self.assertEqual(current.status_code, 302)
        self.assertEqual(current.headers["Location"], "https://www.motorinntoyotaofcarroll.com/serviceappmt.aspx")
        self.assertEqual(current.headers["Cache-Control"], "no-store")
        self.assertEqual(current.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(current.headers["X-Robots-Tag"], "noindex, nofollow")

        service = self.client.get(
            "/api/v1/service-information",
            headers={"Host": "ai.motorinntoyotaofcarroll.com"},
        ).get_json()
        self.assertEqual(service["stableHandoffUrl"], "https://ai.motorinntoyotaofcarroll.com/service-scheduler")

        active_env = {
            "MOTORINN_XTIME_CARROLL_URL": "https://consumer.xtime.com/scheduling/?webkey=verified-key",
            "MOTORINN_XTIME_CARROLL_ACTIVE": "true",
            "MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION": "carroll",
        }
        with patch.dict("server.os.environ", active_env, clear=False):
            active = self.client.get(
                "/service-scheduler",
                headers={"Host": "ai.motorinntoyotaofcarroll.com"},
            )
        self.assertEqual(active.status_code, 302)
        self.assertEqual(active.headers["Location"], active_env["MOTORINN_XTIME_CARROLL_URL"])

        with patch.dict("server.os.environ", {
            **active_env,
            "MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION": "wrong-location",
        }, clear=False):
            invalid = self.client.get(
                "/service-scheduler",
                headers={"Host": "ai.motorinntoyotaofcarroll.com"},
            )
        self.assertEqual(invalid.status_code, 503)
        self.assertEqual(invalid.get_json()["error"]["code"], "source_unavailable")

    def test_xtime_activation_requires_an_explicit_gate_and_valid_consumer_url(self) -> None:
        env = {
            "MOTORINN_XTIME_CARROLL_URL": "https://consumer.xtime.com/scheduling/?webkey=dealer-key",
            "MOTORINN_XTIME_CARROLL_ACTIVE": "true",
            "MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION": "carroll",
        }
        with patch.dict("server.os.environ", env, clear=False):
            active = self.client.get("/api/v1/service-information", headers={"Host": "ai.motorinntoyotaofcarroll.com"})

        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.get_json()["authoritativeSystem"], "Xtime Schedule by Cox Automotive")
        self.assertEqual(active.get_json()["actionUrl"], env["MOTORINN_XTIME_CARROLL_URL"])
        self.assertTrue(active.get_json()["providerTransition"]["active"])

        with patch.dict("server.os.environ", {**env, "MOTORINN_XTIME_CARROLL_ACTIVE": "false"}, clear=False):
            staged = self.client.get("/api/v1/service-information", headers={"Host": "ai.motorinntoyotaofcarroll.com"})
        self.assertEqual(staged.get_json()["providerTransition"]["status"], "planned")
        self.assertTrue(staged.get_json()["providerTransition"]["configured"])
        self.assertFalse(staged.get_json()["providerTransition"]["active"])
        self.assertEqual(staged.get_json()["authoritativeSystem"], "DealerOn appointment request form")

        with patch.dict("server.os.environ", {
            "MOTORINN_XTIME_CARROLL_URL": "https://evil.example/scheduling/?webkey=dealer-key",
            "MOTORINN_XTIME_CARROLL_ACTIVE": "true",
        }, clear=False):
            invalid = self.client.get("/api/v1/service-information", headers={"Host": "ai.motorinntoyotaofcarroll.com"})
        self.assertEqual(invalid.status_code, 503)
        self.assertEqual(invalid.get_json()["error"]["code"], "source_unavailable")

        for malformed_url in (
            "https://[",
            "https://user:secret@consumer.xtime.com:444/scheduling/?webkey=k",
            "https://consumer.xtime.com/scheduling/?webkey=k\r\nX-Evil: yes",
            " https://consumer.xtime.com/scheduling/?webkey=k",
            "https://consumer.xtime.com/scheduling/?webkey=k&variant=a&variant=b",
        ):
            with self.subTest(malformed_url=malformed_url), patch.dict("server.os.environ", {
                **env,
                "MOTORINN_XTIME_CARROLL_URL": malformed_url,
            }, clear=False):
                malformed = self.client.get("/api/v1/service-information", headers={"Host": "ai.motorinntoyotaofcarroll.com"})
                self.assertEqual(malformed.status_code, 503)
                self.assertEqual(malformed.get_json()["error"]["code"], "source_unavailable")

    def test_invalid_vehicle_inputs_do_not_touch_authoritative_sources(self) -> None:
        with patch("server.match_rows") as source:
            invalid_search = self.client.get("/api/v1/vehicles?limit=26", headers={"Host": "ai.motorinnofcarroll.com"})
            invalid_detail = self.client.get("/api/v1/vehicles/not-a-vin", headers={"Host": "ai.motorinnofcarroll.com"})
        self.assertEqual(invalid_search.status_code, 400)
        self.assertEqual(invalid_detail.status_code, 400)
        source.assert_not_called()

    def test_all_public_api_failures_remain_typed_json(self) -> None:
        cases = [
            ("/api/v1/locations", "server.agent_access.locations"),
            ("/api/v1/service-information", "server.agent_access.service_information"),
            ("/api/v1/parts-information", "server.agent_access.parts_information"),
        ]
        for path, target in cases:
            with self.subTest(path=path), patch(target, side_effect=RuntimeError("internal detail must not escape")):
                response = self.client.get(path, headers={"Host": "ai.motorinnofcarroll.com"})
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.content_type, "application/json")
            self.assertEqual(response.get_json()["error"], {
                "code": "internal_error", "message": "The request could not be completed", "retryable": False,
            })

        for invalid_fee in (-180, float("nan"), float("inf")):
            with self.subTest(documentary_fee=invalid_fee), patch("server.DOC_FEE", invalid_fee), patch("server.match_rows") as source:
                response = self.client.get("/api/v1/vehicles", headers={"Host": "ai.motorinnofcarroll.com"})
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.get_json()["error"]["code"], "internal_error")
            source.assert_not_called()

    def test_mcp_lists_only_read_tools_and_matches_http_result(self) -> None:
        headers = {
            "Host": "ai.motorinnofcarroll.com",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }
        initialize = self.client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        })
        listed = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in listed.get_json()["result"]["tools"]}

        self.assertEqual(initialize.status_code, 200)
        self.assertEqual(initialize.get_json()["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(names, {"search_vehicles", "get_vehicle", "list_locations", "get_service_information", "get_parts_information"})
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in listed.get_json()["result"]["tools"]))
        self.assertTrue(all("outputSchema" in tool for tool in listed.get_json()["result"]["tools"]))
        definitions = {tool["name"]: tool for tool in listed.get_json()["result"]["tools"]}
        self.assertEqual(definitions["search_vehicles"]["inputSchema"]["properties"]["query"]["minLength"], 1)

        catalog, inventory = self.inventory_sources()
        with catalog, inventory:
            http = self.client.get("/api/v1/vehicles?condition=new&limit=10", headers={"Host": "ai.motorinnofcarroll.com"}).get_json()
            mcp = self.client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "search_vehicles", "arguments": {"condition": "new", "limit": 10}},
            }).get_json()["result"]
        self.assertEqual(mcp["structuredContent"], http)
        self.assertEqual(json.loads(mcp["content"][0]["text"]), http)
        Draft202012Validator(definitions["search_vehicles"]["outputSchema"]).validate(mcp["structuredContent"])

        with patch("server.match_rows") as source:
            invalid = self.client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "search_vehicles", "arguments": {"limit": 26}},
            }).get_json()["result"]
            wrong_type = self.client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "get_parts_information", "arguments": "not-an-object"},
            }).get_json()["result"]
        source.assert_not_called()
        self.assertTrue(invalid["isError"])
        self.assertNotIn("structuredContent", invalid)
        self.assertTrue(wrong_type["isError"])
        self.assertNotIn("structuredContent", wrong_type)

        negotiated = self.client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 6, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        })
        self.assertEqual(negotiated.get_json()["result"]["protocolVersion"], "2025-11-25")

    def test_mcp_rejects_untrusted_origins_and_does_not_offer_get_stream(self) -> None:
        rejected = self.client.post(
            "/mcp",
            headers={"Host": "ai.motorinnofcarroll.com", "Origin": "https://evil.example", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        no_stream = self.client.get("/mcp", headers={"Host": "ai.motorinnofcarroll.com", "Accept": "text/event-stream"})

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(no_stream.status_code, 405)
        self.assertEqual(no_stream.headers["Allow"], "POST")

    def test_mcp_bounds_bodies_rate_limits_discovery_and_validates_request_ids(self) -> None:
        headers = {"Host": "ai.motorinnofcarroll.com", "Content-Type": "application/json"}
        oversized = self.client.post("/mcp", headers=headers, data=b'{' + b' ' * (256 * 1024) + b'}')
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.get_json()["error"]["code"], "invalid_request")

        explicit_null = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": None, "method": "ping"})
        invalid_id = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": {}, "method": "ping"})
        self.assertEqual(explicit_null.status_code, 200)
        self.assertIn("result", explicit_null.get_json())
        self.assertEqual(invalid_id.status_code, 400)
        self.assertEqual(invalid_id.get_json()["error"]["code"], -32600)

        with server._query_rate_lock:
            server._query_rate_limits.clear()
        for request_id in range(60):
            allowed = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": request_id, "method": "tools/list"})
            self.assertEqual(allowed.status_code, 200)
        limited = self.client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 61, "method": "tools/list"})
        self.assertEqual(limited.status_code, 429)

    def test_all_mcp_read_tools_match_http_including_xtime_transition_states(self) -> None:
        headers = {"Host": "ai.motorinntoyotaofcarroll.com", "MCP-Protocol-Version": "2025-11-25"}

        def call(name, arguments=None):
            return self.client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": name, "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }).get_json()["result"]

        catalog, inventory = self.inventory_sources()
        with catalog, inventory:
            pairs = [
                (self.client.get(f"/api/v1/vehicles/{TOYOTA_VIN.lower()}", headers=headers).get_json(), call("get_vehicle", {"vin": TOYOTA_VIN.lower()})),
                (self.client.get("/api/v1/locations", headers=headers).get_json(), call("list_locations")),
                (self.client.get("/api/v1/service-information", headers=headers).get_json(), call("get_service_information")),
                (self.client.get("/api/v1/parts-information", headers=headers).get_json(), call("get_parts_information")),
            ]
        for http_payload, tool_result in pairs:
            self.assertEqual(tool_result["structuredContent"], http_payload)

        active_env = {
            "MOTORINN_XTIME_CARROLL_URL": "https://consumer.xtime.com/scheduling/?webkey=verified-key",
            "MOTORINN_XTIME_CARROLL_ACTIVE": "true",
            "MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION": "carroll",
        }
        with patch.dict("server.os.environ", active_env, clear=False):
            active_http = self.client.get("/api/v1/service-information", headers=headers).get_json()
            active_mcp = call("get_service_information")
        self.assertEqual(active_mcp["structuredContent"], active_http)

        with patch.dict("server.os.environ", {**active_env, "MOTORINN_XTIME_CARROLL_URL": "https://["}, clear=False):
            invalid_http = self.client.get("/api/v1/service-information", headers=headers)
            invalid_mcp = call("get_service_information")
        self.assertEqual(invalid_http.status_code, 503)
        self.assertTrue(invalid_mcp["isError"])
        self.assertNotIn("structuredContent", invalid_mcp)
        self.assertEqual(json.loads(invalid_mcp["content"][0]["text"])["error"]["code"], "source_unavailable")

        strict_http = self.client.get("/api/v1/vehicles?condition=NEW", headers=headers)
        strict_mcp = call("search_vehicles", {"condition": "NEW"})
        self.assertEqual(strict_http.status_code, 400)
        self.assertTrue(strict_mcp["isError"])


if __name__ == "__main__":
    unittest.main()
