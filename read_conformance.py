"""Read-only conformance checks for Motor Inn's public agent surfaces.

The harness intentionally performs only HTTP GET requests and MCP read-tool
POST requests.  It compares the authoritative JSON returned through OpenAPI
routes with MCP structured content, then verifies that the corresponding
public AI pages corroborate the discoverable facts and canonical links.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import requests


DEFAULT_HOSTS = (
    "ai.motorinnautogroup.com",
    "ai.motorinnofcarroll.com",
    "ai.motorinntoyotaofcarroll.com",
)
READ_TOOLS = {
    "search_vehicles",
    "get_vehicle",
    "list_locations",
    "get_service_information",
    "get_parts_information",
}
CLIENTS = {"chatgpt", "claude", "gemini", "perplexity", "browser"}
SENSITIVE_KEY = re.compile(
    r"(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|webkey)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> HttpResult: ...


class RequestsTransport:
    """Bounded network transport with no retries and no credentials."""

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MotorInn-Read-Conformance/1.0"})

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> HttpResult:
        if method not in {"GET", "POST"}:
            raise ValueError("The read conformance transport permits only GET and POST")
        if method == "POST" and urlparse(url).path != "/mcp":
            raise ValueError("POST is permitted only for the read-only MCP endpoint")
        try:
            response = self.session.request(
                method,
                url,
                json=json_body,
                headers={"MCP-Protocol-Version": "2025-11-25"} if method == "POST" else None,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            return HttpResult(
                0,
                {"X-Conformance-Error": type(exc).__name__},
                b"",
            )
        return HttpResult(response.status_code, dict(response.headers), response.content)


def _finding(check: str, status: str, detail: str, **evidence: Any) -> dict[str, Any]:
    result = {"check": check, "status": status, "detail": detail}
    if evidence:
        result["evidence"] = evidence
    return result


def _safe_json(result: HttpResult) -> Any | None:
    try:
        return result.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _content_type(result: HttpResult) -> str:
    return next(
        (value for key, value in result.headers.items() if key.casefold() == "content-type"),
        "",
    ).casefold()


def _normalized_public_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    tokens = ["rd" if token == "road" else token for token in normalized.split()]
    return " ".join(tokens)


def _error_code(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    return str(error.get("code")) if isinstance(error, Mapping) and error.get("code") else None


def _mcp_payload(message: Any) -> tuple[Any | None, str | None]:
    if not isinstance(message, Mapping):
        return None, "invalid_mcp_response"
    result = message.get("result")
    if not isinstance(result, Mapping):
        error = message.get("error")
        code = error.get("code") if isinstance(error, Mapping) else "invalid_mcp_response"
        return None, str(code)
    structured = result.get("structuredContent")
    if structured is not None:
        return structured, None
    content = result.get("content")
    if isinstance(content, list) and content and isinstance(content[0], Mapping):
        try:
            parsed = json.loads(str(content[0].get("text", "")))
        except json.JSONDecodeError:
            return None, "invalid_mcp_content"
        return None, _error_code(parsed) or "mcp_tool_error"
    return None, "invalid_mcp_result"


def _recursive_sensitive(value: Any, path: str = "$") -> list[str]:
    matches: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if SENSITIVE_KEY.search(str(key)):
                matches.append(child_path)
            matches.extend(_recursive_sensitive(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(_recursive_sensitive(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        parsed = urlparse(value)
        if parsed.query and SENSITIVE_KEY.search(parsed.query):
            matches.append(path)
    return matches


def load_client_evidence(paths: list[Path]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schema") != "motorinn.clientReadEvidence.v1":
            raise ValueError(f"{path}: unsupported client evidence schema")
        if document.get("client") not in CLIENTS:
            raise ValueError(f"{path}: unsupported client name")
        sensitive = _recursive_sensitive(document)
        if sensitive:
            raise ValueError(f"{path}: possible secret at {', '.join(sensitive)}")
        evidence.append(document)
    return evidence


class ReadConformanceHarness:
    def __init__(self, transport: Transport, *, vehicle_limit: int = 10) -> None:
        if not 1 <= vehicle_limit <= 25:
            raise ValueError("vehicle_limit must be between 1 and 25")
        self.transport = transport
        self.vehicle_limit = vehicle_limit

    @staticmethod
    def _base(host: str) -> str:
        if host not in DEFAULT_HOSTS:
            raise ValueError(f"Unsupported Motor Inn AI host: {host}")
        return f"https://{host}"

    def _get(self, base: str, path: str) -> HttpResult:
        return self.transport.request("GET", f"{base}{path}")

    def _mcp(self, base: str, method: str, params: Mapping[str, Any]) -> HttpResult:
        return self.transport.request(
            "POST",
            f"{base}/mcp",
            json_body={"jsonrpc": "2.0", "id": method, "method": method, "params": dict(params)},
        )

    def _mcp_tool(self, base: str, name: str, arguments: Mapping[str, Any]) -> HttpResult:
        return self._mcp(
            base,
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
        )

    def _contract_checks(self, host: str, base: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        openapi_result = self._get(base, "/openapi.json")
        openapi = _safe_json(openapi_result)
        if openapi_result.status != 200 or not isinstance(openapi, Mapping):
            findings.append(_finding("openapi_contract", "fail", "OpenAPI document was not valid JSON", httpStatus=openapi_result.status))
        else:
            servers = openapi.get("servers")
            server_urls = [item.get("url") for item in servers if isinstance(item, Mapping)] if isinstance(servers, list) else []
            paths = openapi.get("paths") if isinstance(openapi.get("paths"), Mapping) else {}
            required = {
                "/api/v1/vehicles",
                "/api/v1/vehicles/{vin}",
                "/api/v1/locations",
                "/api/v1/service-information",
                "/api/v1/parts-information",
            }
            mutating = sorted(
                f"{method.upper()} {path}"
                for path, operations in paths.items()
                if str(path).startswith("/api/v1/") and isinstance(operations, Mapping)
                for method in operations
                if str(method).casefold() in {"post", "put", "patch", "delete"}
            )
            missing = sorted(required - set(paths))
            status = "pass" if base in server_urls and not missing and not mutating else "fail"
            findings.append(_finding(
                "openapi_contract",
                status,
                "OpenAPI is host-scoped and read-only" if status == "pass" else "OpenAPI host scope or read-only paths did not match",
                serverUrls=server_urls,
                missingPaths=missing,
                mutatingOperations=mutating,
            ))

        listed_result = self._mcp(base, "tools/list", {})
        listed = _safe_json(listed_result)
        tools = listed.get("result", {}).get("tools") if isinstance(listed, Mapping) else None
        definitions = tools if isinstance(tools, list) else []
        names = {tool.get("name") for tool in definitions if isinstance(tool, Mapping)}
        unsafe = sorted(
            str(tool.get("name"))
            for tool in definitions
            if isinstance(tool, Mapping)
            and (
                tool.get("annotations", {}).get("readOnlyHint") is not True
                or tool.get("annotations", {}).get("destructiveHint") is not False
            )
        )
        mcp_status = "pass" if listed_result.status == 200 and names == READ_TOOLS and not unsafe else "fail"
        findings.append(_finding(
            "mcp_contract",
            mcp_status,
            "MCP exposes exactly five annotated read tools" if mcp_status == "pass" else "MCP tool inventory or annotations did not match",
            tools=sorted(str(name) for name in names),
            unsafeTools=unsafe,
        ))

        llms = self._get(base, "/llms.txt")
        llms_ok = (
            llms.status == 200
            and "text/markdown" in _content_type(llms)
            and f"{base}/openapi.json" in llms.text()
            and f"{base}/mcp" in llms.text()
        )
        findings.append(_finding(
            "public_discovery",
            "pass" if llms_ok else "fail",
            "llms.txt advertises this host's OpenAPI and MCP endpoints" if llms_ok else "llms.txt discovery links or media type did not match",
            httpStatus=llms.status,
            contentType=_content_type(llms),
            host=host,
        ))
        return findings

    def _equivalent_read(
        self,
        base: str,
        *,
        name: str,
        path: str,
        tool: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], Any | None, str | None]:
        http_result = self._get(base, path)
        http_payload = _safe_json(http_result)
        mcp_result = self._mcp_tool(base, tool, arguments or {})
        mcp_message = _safe_json(mcp_result)
        mcp_payload, mcp_error = _mcp_payload(mcp_message)
        http_error = _error_code(http_payload)
        if http_result.status == 200 and mcp_result.status == 200 and http_payload == mcp_payload:
            return _finding(name, "pass", "OpenAPI JSON and MCP structured content are identical", httpStatus=200), http_payload, None
        if http_error and mcp_error and http_error == mcp_error:
            status = "degraded" if http_error == "source_unavailable" else "pass"
            return _finding(name, status, f"OpenAPI and MCP returned the same typed error: {http_error}", httpStatus=http_result.status, errorCode=http_error), None, http_error
        return _finding(
            name,
            "fail",
            "OpenAPI and MCP results were not equivalent",
            httpStatus=http_result.status,
            httpError=http_error,
            mcpStatus=mcp_result.status,
            mcpError=mcp_error,
        ), http_payload, http_error

    def _page_contains(
        self,
        base: str,
        path: str,
        required: list[str],
        check: str,
    ) -> dict[str, Any]:
        result = self._get(base, path)
        page_text = _normalized_public_text(result.text())
        missing = [
            value
            for value in required
            if value and _normalized_public_text(value) not in page_text
        ]
        ok = result.status == 200 and "text/markdown" in _content_type(result) and not missing
        return _finding(
            check,
            "pass" if ok else "fail",
            f"{path} corroborates the structured result" if ok else f"{path} did not corroborate the structured result",
            httpStatus=result.status,
            missing=missing,
        )

    def _surface_checks(self, base: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        snapshot: dict[str, Any] = {}

        inventory, vehicles_payload, inventory_error = self._equivalent_read(
            base,
            name="vehicles_http_mcp",
            path=f"/api/v1/vehicles?limit={self.vehicle_limit}",
            tool="search_vehicles",
            arguments={"limit": self.vehicle_limit},
        )
        findings.append(inventory)
        new_page = self._get(base, "/new-inventory.md")
        used_page = self._get(base, "/used-inventory.md")
        if inventory_error == "source_unavailable":
            pages_degraded = new_page.status == 503 and used_page.status == 503
            findings.append(_finding(
                "vehicles_public_pages",
                "degraded" if pages_degraded else "fail",
                "Inventory pages fail closed with the structured surfaces" if pages_degraded else "Inventory page state does not match structured source availability",
                newStatus=new_page.status,
                usedStatus=used_page.status,
            ))
            snapshot["vehicles"] = {"errorCode": inventory_error}
        elif isinstance(vehicles_payload, Mapping):
            vehicles = vehicles_payload.get("vehicles") if isinstance(vehicles_payload.get("vehicles"), list) else []
            missing_vins: list[str] = []
            combined = f"{new_page.text()}\n{used_page.text()}".casefold()
            for vehicle in vehicles:
                if isinstance(vehicle, Mapping) and vehicle.get("vin") and str(vehicle["vin"]).casefold() not in combined:
                    missing_vins.append(str(vehicle["vin"]))
            pages_ok = new_page.status == 200 and used_page.status == 200 and not missing_vins
            findings.append(_finding(
                "vehicles_public_pages",
                "pass" if pages_ok else "fail",
                "Public inventory pages contain every returned VIN" if pages_ok else "Public inventory pages did not match vehicle results",
                missingVins=missing_vins,
                newStatus=new_page.status,
                usedStatus=used_page.status,
            ))
            snapshot["vehicles"] = {"vehicleVins": sorted(str(v.get("vin")) for v in vehicles if isinstance(v, Mapping) and v.get("vin"))}

        locations, locations_payload, _ = self._equivalent_read(
            base, name="locations_http_mcp", path="/api/v1/locations", tool="list_locations"
        )
        findings.append(locations)
        if isinstance(locations_payload, Mapping):
            location_items = locations_payload.get("locations") if isinstance(locations_payload.get("locations"), list) else []
            first = location_items[0] if location_items and isinstance(location_items[0], Mapping) else {}
            location = first.get("location") if isinstance(first.get("location"), Mapping) else {}
            address = location.get("address") if isinstance(location.get("address"), Mapping) else {}
            findings.append(self._page_contains(
                base,
                "/contact-hours.md",
                [str(address.get("streetAddress", "")), str(address.get("addressLocality", "")), str(address.get("postalCode", ""))],
                "locations_public_page",
            ))
            snapshot["locations"] = {"locationKeys": [location.get("key")] if location.get("key") else []}

        service, service_payload, _ = self._equivalent_read(
            base, name="service_http_mcp", path="/api/v1/service-information", tool="get_service_information"
        )
        findings.append(service)
        if isinstance(service_payload, Mapping):
            findings.append(self._page_contains(base, "/service.md", [str(service_payload.get("actionUrl", ""))], "service_public_page"))
            snapshot["service"] = {
                "actionUrls": [service_payload.get("actionUrl")],
                "capabilityState": service_payload.get("capabilityState"),
                "locationKeys": [service_payload.get("serviceLocation", {}).get("key")] if isinstance(service_payload.get("serviceLocation"), Mapping) else [],
            }

        parts, parts_payload, _ = self._equivalent_read(
            base, name="parts_http_mcp", path="/api/v1/parts-information", tool="get_parts_information"
        )
        findings.append(parts)
        if isinstance(parts_payload, Mapping):
            service_page = self._get(base, "/service.md")
            full_page = self._get(base, "/llms-full.txt")
            action_url = str(parts_payload.get("actionUrl", ""))
            corroborated = action_url and action_url.casefold() in f"{service_page.text()}\n{full_page.text()}".casefold()
            findings.append(_finding(
                "parts_public_page",
                "pass" if corroborated else "fail",
                "Public AI pages advertise the structured parts action" if corroborated else "Public AI pages do not advertise the structured parts action",
                actionUrl=action_url,
            ))
            snapshot["parts"] = {"actionUrls": [parts_payload.get("actionUrl")], "capabilityState": parts_payload.get("capabilityState")}

        return findings, snapshot

    @staticmethod
    def _client_checks(
        host: str,
        snapshot: Mapping[str, Any],
        evidence: list[dict[str, Any]],
        required_clients: set[str],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        matched_clients: set[str] = set()
        for document in evidence:
            if document.get("host") != host:
                continue
            client = str(document.get("client"))
            matched_clients.add(client)
            observations = document.get("observations")
            if not isinstance(observations, Mapping) or not observations:
                findings.append(_finding(f"client_{client}", "fail", "Client evidence observations must be a non-empty object"))
                continue
            differences: list[str] = []
            for surface, observed in observations.items():
                expected = snapshot.get(surface)
                if expected is None or not isinstance(observed, Mapping) or not isinstance(expected, Mapping):
                    differences.append(f"{surface}: unsupported observation")
                    continue
                for key, value in observed.items():
                    expected_value = expected.get(key)
                    if isinstance(value, list) and isinstance(expected_value, list):
                        observed_values = {json.dumps(item, sort_keys=True) for item in value}
                        expected_values = {json.dumps(item, sort_keys=True) for item in expected_value}
                        if not observed_values.issubset(expected_values):
                            differences.append(f"{surface}.{key}: contains unsupported values")
                    elif value != expected_value:
                        differences.append(f"{surface}.{key}: differs")
            findings.append(_finding(
                f"client_{client}",
                "pass" if not differences else "fail",
                "Captured client results are supported by live read surfaces" if not differences else "Captured client results differ from live read surfaces",
                differences=differences,
                capturedAt=document.get("capturedAt"),
            ))
        for client in sorted(required_clients - matched_clients):
            findings.append(_finding(f"client_{client}", "fail", "Required client evidence was not supplied"))
        return findings

    def run(
        self,
        hosts: list[str],
        *,
        client_evidence: list[dict[str, Any]] | None = None,
        required_clients: set[str] | None = None,
    ) -> dict[str, Any]:
        reports: list[dict[str, Any]] = []
        evidence = client_evidence or []
        required = required_clients or set()
        for host in hosts:
            base = self._base(host)
            findings = self._contract_checks(host, base)
            surface_findings, snapshot = self._surface_checks(base)
            findings.extend(surface_findings)
            findings.extend(self._client_checks(host, snapshot, evidence, required))
            host_status = "fail" if any(f["status"] == "fail" for f in findings) else "degraded" if any(f["status"] == "degraded" for f in findings) else "pass"
            reports.append({"host": host, "status": host_status, "findings": findings})
        status = "fail" if any(r["status"] == "fail" for r in reports) else "degraded" if any(r["status"] == "degraded" for r in reports) else "pass"
        return {
            "schema": "motorinn.readConformance.v1",
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": "read_only",
            "status": status,
            "hosts": reports,
        }


def exit_code(report: Mapping[str, Any]) -> int:
    return {"pass": 0, "fail": 2, "degraded": 3}.get(str(report.get("status")), 2)
