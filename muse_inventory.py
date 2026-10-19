"""Conservative Muse inventory projection; kept disabled pending external gates."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit


# Deliberately not configurable by environment. This adapter is not registered
# in either MCP profile and cannot be enabled without a code review.
MUSE_INVENTORY_ENABLED = False
DEFAULT_LOCATION_ID = "carroll"
DEFAULT_MAX_AGE_SECONDS = 36 * 60 * 60
KNOWN_NON_PRICE_SEARCH_FILTERS = frozenset({
    "location_ids", "condition", "make", "model", "min_year", "max_year", "body_style", "limit", "cursor",
})


class UnsupportedInventoryFilter(ValueError):
    """Raised when a requested filter cannot be applied without guessing."""


def validate_inventory_filters(filters: Mapping[str, Any]) -> None:
    """Reject price bounds until the source's advertised cash basis is known."""
    unsupported = set(filters) - KNOWN_NON_PRICE_SEARCH_FILTERS - {"max_price_minor"}
    if unsupported:
        raise UnsupportedInventoryFilter(f"unsupported inventory filters: {', '.join(sorted(unsupported))}")
    if "max_price_minor" in filters:
        raise UnsupportedInventoryFilter(
            "max_price_minor is unsupported while source price basis and conditions are unverified"
        )


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("checked_at must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_vehicle_id(location_id: str, source_id: Any) -> str:
    normalized = str(source_id or "").strip()
    if not normalized:
        raise ValueError("the existing public result ID is required")
    digest = hashlib.sha256(f"{location_id}\0{normalized}".encode("utf-8")).hexdigest()[:32]
    return f"{location_id}_{digest}"


def _https_url(value: Any, name: str) -> str:
    normalized = str(value or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError(f"{name} must be a public HTTPS URL")
    return normalized


def map_public_vehicle(
    vehicle: Mapping[str, Any],
    *,
    checked_at: datetime,
    location_id: str = DEFAULT_LOCATION_ID,
) -> dict[str, Any]:
    """Map the current public projection without inferring unsupported facts.

    Availability, price, and upstream timestamps are deliberately unknown.
    Photos and unknown feature-like attributes are omitted from this projection.
    """
    year = vehicle.get("year")
    if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2100:
        raise ValueError("year is outside the Muse contract range")
    condition = vehicle.get("condition")
    if not isinstance(condition, str) or condition not in {"new", "used", "certified"}:
        raise ValueError("condition is not supported by the Muse contract")
    make = str(vehicle.get("make") or "").strip()
    model = str(vehicle.get("model") or "").strip()
    if not make or not model:
        raise ValueError("make and model are required by the Muse contract")
    freshness = vehicle.get("sourceFreshness")
    if not isinstance(freshness, Mapping):
        raise ValueError("source freshness envelope is required")
    # Reading the current basis flags is an allowlist check: do not convert the
    # timestamps themselves into supplier source_updated_at or ingested_at.
    expected_timestamp_basis = {
        "dealerVaultTimestampBasis": "s3_object_last_modified",
        "publicCatalogTimestampBasis": "http_last_modified_or_retrieval_time",
    }
    if any(freshness.get(key) != value for key, value in expected_timestamp_basis.items()):
        raise ValueError("source timestamp basis is missing or unsupported")
    source_url = _https_url(vehicle.get("canonicalUrl"), "source_url")
    checked = _iso_timestamp(checked_at)
    public_price = {
        "amount_minor": None,
        "currency": "USD",
        "basis": "call_for_price",
        "conditions": ["Price basis and conditions are unverified; confirm current terms with the dealership."],
        "included_fees": [],
        "excluded_taxes_fees": [],
        "valid_until": None,
        "description": "Price amount withheld because the source basis and conditions are unverified.",
    }
    freshness_output = {
        "location_id": location_id,
        "snapshot_id": None,
        "source_updated_at": None,
        "ingested_at": None,
        "checked_at": checked,
        "basis": "ingestion_only",
        "state": "unknown",
        "max_age_seconds": DEFAULT_MAX_AGE_SECONDS,
    }
    return {
        "vehicle_id": _stable_vehicle_id(location_id, vehicle.get("id")),
        "location_id": location_id,
        "stock_number": vehicle.get("stockNumber") or None,
        "vin": vehicle.get("vin") or None,
        "year": year,
        "make": make,
        "model": model,
        "trim": vehicle.get("trim") or None,
        "condition": condition,
        "body_style": None,
        "drivetrain": None,
        "powertrain": None,
        "fuel": None,
        "exterior_color": None,
        "interior_color": None,
        "odometer": None,
        "features": [],
        "source_url": source_url,
        "image_urls": [],
        "availability": "unknown",
        "public_price": public_price,
        "freshness": freshness_output,
        "warnings": ["Availability and freshness are unknown; this record is informational only."],
    }
