"""Versioned public-read services shared by HTTP and MCP transports."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit, urlunsplit


API_SCHEMA_VERSION = "v1"
XTIME_PROVIDER = "Xtime Schedule by Cox Automotive"
CARROLL_SERVICE_LOCATION = {
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
}
XTIME_CONSUMER_HOSTS = frozenset({"consumer.xtime.com"})
OWNED_PUBLIC_HOSTS = frozenset({
    "www.motorinnautogroup.com",
    "www.motorinnofcarroll.com",
    "www.motorinntoyotaofcarroll.com",
})


class InvalidRequest(ValueError):
    """Raised when public API input does not match the documented contract."""


class ConfigurationUnavailable(RuntimeError):
    """Raised when an operator-enabled provider handoff fails validation."""


def iso_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def site_identity(site: Any) -> dict[str, str]:
    return {
        "key": site.key,
        "name": site.name,
        "host": site.ai_host,
        "canonicalUrl": site.base_url,
    }


def source_freshness(catalog_modified: datetime, inventory_modified: datetime) -> dict[str, str]:
    return {
        "dealerVaultUpdatedAt": iso_timestamp(inventory_modified),
        "publicCatalogUpdatedAt": iso_timestamp(catalog_modified),
    }


def _text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _lexical(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", _text(value).casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _decimal(value: Any, name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidRequest(f"{name} must be a non-negative number") from exc
    if not parsed.is_finite() or parsed < 0:
        raise InvalidRequest(f"{name} must be a non-negative number")
    return parsed


def _integer(value: Any, name: str, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(str(value))
    except ValueError as exc:
        raise InvalidRequest(f"{name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise InvalidRequest(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _bounded_text(value: Any, name: str, maximum: int) -> str | None:
    if value is None:
        return None
    parsed = _text(value)
    if not parsed:
        raise InvalidRequest(f"{name} must not be empty")
    if len(parsed) > maximum:
        raise InvalidRequest(f"{name} must be at most {maximum} characters")
    return parsed


def _condition(value: Any) -> str | None:
    parsed = _bounded_text(value, "condition", 8)
    if parsed is not None and parsed not in {"new", "used"}:
        raise InvalidRequest("condition must be new or used")
    return parsed


def _base_price(source: Mapping[str, Any]) -> Decimal | None:
    for key in ("internet_price", "list_price", "msrp"):
        raw = source.get(key)
        if raw not in (None, ""):
            try:
                value = Decimal(str(raw).replace(",", "").split()[0])
            except (InvalidOperation, ValueError):
                continue
            if value > 0:
                return value
    return None


def _canonical_catalog_url(value: Any) -> str:
    public = _public_url(value)
    if public is None:
        return ""
    parsed = urlsplit(public)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _public_url(value: Any) -> str | None:
    try:
        parsed = urlsplit(_text(value))
        netloc = parsed.netloc
        port = parsed.port
    except ValueError:
        return None
    allowed_port = 443 if parsed.scheme == "https" else 80
    if (
        parsed.scheme not in {"http", "https"}
        or not netloc
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, allowed_port}
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _row_matches_public_schema(row: Mapping[str, Any]) -> bool:
    vin = _text(row.get("vin")).upper()
    year = _text(row.get("vehicle_year"))
    condition = _text(row.get("condition")).casefold()
    return (
        re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin) is not None
        and bool(_text(row.get("stock_number") or row.get("id")))
        and year.isdigit()
        and 1886 <= int(year) <= 2200
        and bool(_text(row.get("vehicle_make")))
        and bool(_text(row.get("vehicle_model")))
        and condition in {"new", "used"}
        and _public_url(row.get("link")) is not None
    )


def _row_is_site_valid(site: Any, row: Mapping[str, Any]) -> bool:
    condition = _text(row.get("condition")).casefold()
    row_host = (urlsplit(_text(row.get("link"))).hostname or "").casefold()
    site_host = (urlsplit(site.base_url).hostname or "").casefold()
    if site.new_make:
        if condition == "new":
            return (
                row_host in {site_host, "www.motorinnautogroup.com"}
                and _text(row.get("vehicle_make")).upper() == site.new_make
            )
        return condition == "used" and row_host == site_host
    return row_host in OWNED_PUBLIC_HOSTS


def _year_sort_value(row: Mapping[str, Any]) -> int:
    value = _text(row.get("vehicle_year"))
    return int(value) if value.isdigit() else 0


def _vehicle_projection(
    site: Any,
    row: Mapping[str, Any],
    catalog_modified: datetime,
    inventory_modified: datetime,
    documentary_fee: Decimal,
) -> dict[str, Any]:
    source = row.get("dealerVault") if isinstance(row.get("dealerVault"), Mapping) else {}
    base_price = _base_price(source)
    price = None
    if base_price is not None:
        price = {
            "amount": f"{base_price + documentary_fee:.2f}",
            "currency": "USD",
            "includesDocumentaryFee": True,
            "documentaryFeeAmount": f"{documentary_fee:.2f}",
        }
    year_text = _text(row.get("vehicle_year"))
    return {
        "id": _text(row.get("id") or row.get("vin") or row.get("stock_number")),
        "vin": _text(row.get("vin")).upper(),
        "stockNumber": _text(row.get("stock_number") or row.get("id")),
        "year": int(year_text) if year_text.isdigit() else 0,
        "make": _text(row.get("vehicle_make")),
        "model": _text(row.get("vehicle_model")),
        "trim": _text(row.get("vehicle_trim")) or None,
        "condition": _text(row.get("condition")).casefold(),
        "advertisedPrice": price,
        "availability": _text(row.get("availability")) or "availability not stated",
        "site": site_identity(site),
        "canonicalUrl": _canonical_catalog_url(row.get("link")),
        "imageUrl": _public_url(row.get("image_link")),
        "sourceFreshness": source_freshness(catalog_modified, inventory_modified),
    }


def _cursor_fingerprint(filters: Mapping[str, Any]) -> str:
    body = json.dumps(filters, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode()).hexdigest()[:20]


def _decode_cursor(value: Any, fingerprint: str) -> tuple[int, str | None]:
    if value in (None, ""):
        return 0, None
    text = _bounded_text(value, "cursor", 512)
    try:
        padded = text + "=" * (-len(text) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        offset = int(payload["offset"])
        source_fingerprint = payload.get("sourceFingerprint")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidRequest("cursor is invalid") from exc
    if payload.get("fingerprint") != fingerprint or offset < 0:
        raise InvalidRequest("cursor does not match the current filters")
    if source_fingerprint is not None and not isinstance(source_fingerprint, str):
        raise InvalidRequest("cursor is invalid")
    return offset, source_fingerprint


def _encode_cursor(offset: int, fingerprint: str, source_fingerprint: str) -> str:
    body = json.dumps(
        {"offset": offset, "fingerprint": fingerprint, "sourceFingerprint": source_fingerprint},
        sort_keys=True,
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")


def validate_vehicle_search(site: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    query = _bounded_text(params.get("query"), "query", 200)
    condition = _condition(params.get("condition"))
    make = _bounded_text(params.get("make"), "make", 80)
    model = _bounded_text(params.get("model"), "model", 120)
    minimum_price = _decimal(params.get("minPrice"), "minPrice")
    maximum_price = _decimal(params.get("maxPrice"), "maxPrice")
    if minimum_price is not None and maximum_price is not None and minimum_price > maximum_price:
        raise InvalidRequest("minPrice must not exceed maxPrice")
    limit = _integer(params.get("limit"), "limit", 10, 1, 25)
    filters = {
        "site": site.key,
        "query": query,
        "condition": condition,
        "make": make,
        "model": model,
        "minPrice": str(minimum_price) if minimum_price is not None else None,
        "maxPrice": str(maximum_price) if maximum_price is not None else None,
    }
    fingerprint = _cursor_fingerprint(filters)
    offset, cursor_source_fingerprint = _decode_cursor(params.get("cursor"), fingerprint)
    return {
        "query": query,
        "condition": condition,
        "make": make,
        "model": model,
        "minimum_price": minimum_price,
        "maximum_price": maximum_price,
        "limit": limit,
        "fingerprint": fingerprint,
        "offset": offset,
        "cursor_source_fingerprint": cursor_source_fingerprint,
    }


def validate_vehicle_vin(vin: Any) -> str:
    normalized = _text(vin).upper()
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", normalized):
        raise InvalidRequest("vin must be a valid 17-character VIN")
    return normalized


def vehicle_search(
    site: Any,
    matched_rows: list[dict[str, Any]],
    catalog_modified: datetime,
    inventory_modified: datetime,
    validated: Mapping[str, Any],
    documentary_fee: float,
) -> dict[str, Any]:
    query = validated["query"]
    condition = validated["condition"]
    make = validated["make"]
    model = validated["model"]
    minimum_price = validated["minimum_price"]
    maximum_price = validated["maximum_price"]
    limit = validated["limit"]
    fingerprint = validated["fingerprint"]
    offset = validated["offset"]
    source_version = f"{iso_timestamp(catalog_modified)}|{iso_timestamp(inventory_modified)}"
    source_fingerprint = hashlib.sha256(source_version.encode()).hexdigest()[:20]
    cursor_source_fingerprint = validated["cursor_source_fingerprint"]
    if cursor_source_fingerprint is not None and cursor_source_fingerprint != source_fingerprint:
        raise InvalidRequest("cursor is stale; restart the search")
    fee = Decimal(str(documentary_fee))

    filtered: list[dict[str, Any]] = []
    for row in matched_rows:
        if not _row_matches_public_schema(row) or not _row_is_site_valid(site, row):
            continue
        row_condition = _text(row.get("condition")).casefold()
        row_make = _text(row.get("vehicle_make"))
        row_model = _text(row.get("vehicle_model"))
        if condition and row_condition != condition:
            continue
        if make and _lexical(row_make) != _lexical(make):
            continue
        if model and _lexical(row_model) != _lexical(model):
            continue
        haystack = " ".join(
            _text(row.get(key))
            for key in ("vehicle_year", "vehicle_make", "vehicle_model", "vehicle_trim", "stock_number", "vin")
        )
        if query and _lexical(query) not in _lexical(haystack):
            continue
        source = row.get("dealerVault") if isinstance(row.get("dealerVault"), Mapping) else {}
        base_price = _base_price(source)
        public_price = base_price + fee if base_price is not None else None
        if minimum_price is not None and (public_price is None or public_price < minimum_price):
            continue
        if maximum_price is not None and (public_price is None or public_price > maximum_price):
            continue
        filtered.append(row)

    filtered.sort(
        key=lambda row: (
            -_year_sort_value(row),
            _lexical(row.get("vehicle_make")),
            _lexical(row.get("vehicle_model")),
            _text(row.get("vin")),
        )
    )
    page = filtered[offset : offset + limit]
    next_offset = offset + len(page)
    next_cursor = _encode_cursor(next_offset, fingerprint, source_fingerprint) if next_offset < len(filtered) else None
    return {
        "schema": "motorinn.vehicleSearch.v1",
        "site": site_identity(site),
        "resultCount": len(page),
        "nextCursor": next_cursor,
        "sourceFreshness": source_freshness(catalog_modified, inventory_modified),
        "vehicles": [
            _vehicle_projection(site, row, catalog_modified, inventory_modified, fee)
            for row in page
        ],
    }


def vehicle_detail(
    site: Any,
    matched_rows: list[dict[str, Any]],
    catalog_modified: datetime,
    inventory_modified: datetime,
    normalized_vin: str,
    documentary_fee: float,
) -> dict[str, Any] | None:
    fee = Decimal(str(documentary_fee))
    for row in matched_rows:
        if _text(row.get("vin")).upper() == normalized_vin and _row_matches_public_schema(row) and _row_is_site_valid(site, row):
            return {
                "schema": "motorinn.vehicle.v1",
                "site": site_identity(site),
                "vehicle": _vehicle_projection(site, row, catalog_modified, inventory_modified, fee),
            }
    return None


def locations(site: Any, contact_markdown: str) -> dict[str, Any]:
    source_url = f"https://{site.ai_host}/contact-hours.md"
    candidates: dict[str, list[str]] = {"sales": [], "service": [], "parts": [], "general": []}
    for line in contact_markdown.splitlines():
        match = re.match(r"-\s+([^:]+):\s+.*?((?:\d{3}-){2}\d{4})", line.strip(), flags=re.IGNORECASE)
        if not match:
            continue
        label, number = match.groups()
        lowered = label.casefold()
        department = next((name for name in ("sales", "service", "parts") if name in lowered), "general")
        if number not in candidates[department]:
            candidates[department].append(number)
    contacts = []
    for department in ("sales", "service", "parts", "general"):
        numbers = candidates[department]
        if not numbers:
            continue
        resolved = len(numbers) == 1
        contacts.append({
            "department": department,
            "number": numbers[0] if resolved else None,
            "status": "canonical" if resolved else "unresolved",
            "sourceUrl": source_url,
        })
    return {
        "schema": "motorinn.locations.v1",
        "site": site_identity(site),
        "locations": [{
            "site": site_identity(site),
            "contactResourceUrl": source_url,
            "contacts": contacts,
        }],
    }


def _available_read_operations() -> dict[str, bool]:
    return {
        "information": True,
        "request": False,
        "liveAvailability": False,
        "hold": False,
        "confirm": False,
        "reschedule": False,
        "cancel": False,
    }


def _valid_xtime_url(value: str | None) -> bool:
    if (
        not value
        or len(value) > 2048
        or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or hostname not in XTIME_CONSUMER_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        return False
    if parsed.path.rstrip("/") != "/scheduling":
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) - {"webkey", "WMODE", "skipredirect", "variant"}:
        return False
    if any(len(values) != 1 or not values[0] for values in query.values()):
        return False
    webkeys = query.get("webkey", [])
    return len(webkeys) == 1 and bool(webkeys[0].strip())


def xtime_configuration_preflight(environ: Mapping[str, str]) -> dict[str, Any]:
    """Return safe, independently evaluated Xtime activation gate state."""
    configured_url = environ.get("MOTORINN_XTIME_CARROLL_URL")
    active_raw = environ.get("MOTORINN_XTIME_CARROLL_ACTIVE", "false")
    verified_location = environ.get("MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION", "")
    active_flag_valid = active_raw.casefold() in {"true", "false"}
    active = active_flag_valid and active_raw.casefold() == "true"
    configured = _valid_xtime_url(configured_url)
    configured_value_present = bool(configured_url)
    verified = verified_location == CARROLL_SERVICE_LOCATION["key"]
    verified_value_present = bool(verified_location)

    error: str | None = None
    if not active_flag_valid:
        error = "invalid_activation_flag"
    elif configured_value_present and not configured:
        error = "invalid_staged_url"
    elif active and (not configured or not verified):
        error = "invalid_active_configuration"
    elif verified_value_present and not verified:
        error = "invalid_location_binding"

    status = {
        "targetProvider": XTIME_PROVIDER,
        "locationKey": CARROLL_SERVICE_LOCATION["key"],
        "status": "invalid" if error else ("active" if active else "planned"),
        "configured": configured,
        "locationBindingVerified": verified,
        "active": active,
        "configurationValid": error is None,
    }
    if error:
        status["error"] = error
    return status


def _xtime_transition(site: Any, environ: Mapping[str, str]) -> tuple[dict[str, Any], str | None]:
    configured_url = environ.get("MOTORINN_XTIME_CARROLL_URL")
    evaluation = xtime_configuration_preflight(environ)
    if evaluation.get("error") == "invalid_activation_flag" or (
        evaluation["active"] and not evaluation["configurationValid"]
    ):
        raise ConfigurationUnavailable(
            "active Xtime configuration requires a valid consumer URL and the explicitly verified Carroll location"
        )
    transition = {
        "targetProvider": evaluation["targetProvider"],
        "locationKey": evaluation["locationKey"],
        "status": "active" if evaluation["active"] else "planned",
        "configured": evaluation["configured"],
        "locationBindingVerified": evaluation["locationBindingVerified"],
        "active": evaluation["active"],
    }
    return transition, configured_url if evaluation["active"] else None


def service_information(site: Any, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    environment = environ if environ is not None else os.environ
    transition, active_xtime_url = _xtime_transition(site, environment)
    if active_xtime_url:
        capability_state = "external_handoff"
        action_url = active_xtime_url
        authority = XTIME_PROVIDER
        notice = "Complete booking in the linked Xtime journey. An appointment is confirmed only when Xtime returns its confirmation."
    elif site.key == "motorinnchevy":
        capability_state = "external_handoff"
        action_url = f"{site.base_url}/serviceappmt.aspx"
        authority = "GM Online Service Scheduling"
        notice = "Complete scheduling in the linked GM customer journey."
    elif site.key == "motorinntoyota":
        capability_state = "requested_only"
        action_url = f"{site.base_url}/serviceappmt.aspx"
        authority = "DealerOn appointment request form"
        notice = "The linked form requests staff follow-up and is not a confirmed appointment."
    else:
        capability_state = "information_only"
        action_url = f"{site.base_url}/service-locations.html"
        authority = "Motor Inn service locations"
        notice = "Choose a rooftop service location before starting its scheduling journey."
    return {
        "schema": "motorinn.capabilityInformation.v1",
        "site": site_identity(site),
        "serviceLocation": CARROLL_SERVICE_LOCATION,
        "domain": "service",
        "capabilityState": capability_state,
        "actionUrl": action_url,
        "stableHandoffUrl": f"https://{site.ai_host}/service-scheduler",
        "authoritativeSystem": authority,
        "availableOperations": _available_read_operations(),
        "notice": notice,
        "providerTransition": transition,
    }


def parts_information(site: Any) -> dict[str, Any]:
    return {
        "schema": "motorinn.capabilityInformation.v1",
        "site": site_identity(site),
        "domain": "parts",
        "capabilityState": "requested_only",
        "actionUrl": f"{site.base_url}/orderparts.aspx",
        "authoritativeSystem": "DealerOn parts request form",
        "availableOperations": _available_read_operations(),
        "notice": "The linked form requests staff follow-up and is not a stock check, fitment result, cart, payment, or confirmed order.",
    }
