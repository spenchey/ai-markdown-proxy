#!/usr/bin/env python3
"""Source-backed AI-readable mirror for Motor Inn's DealerOn websites."""

from __future__ import annotations

import csv
import hashlib
import html
import ipaddress
import io
import json
import logging
import math
import os
import re
import threading
import time
import unicodedata
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import boto3
import requests
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from bs4 import BeautifulSoup
from flask import Flask, Response, g, jsonify, redirect, request
from markdownify import markdownify

import agent_access


CONTENT_ROOT = Path(__file__).resolve().parent / "content"
OPENAPI_PATH = Path(__file__).resolve().parent / "openapi" / "agent-access-v1.yaml"
AUDIT_DATA_ROOT = Path(__file__).resolve().parent / "audit_data"
ARTICLE_ROOT = Path(__file__).resolve().parent / "articles"
ARTICLE_DATE_PUBLISHED = "2026-10-31"
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))
DYNAMIC_CACHE_TTL_SECONDS = int(os.environ.get("DYNAMIC_CACHE_TTL_SECONDS", "300"))
MAX_SOURCE_AGE_SECONDS = int(os.environ.get("MAX_SOURCE_AGE_SECONDS", str(36 * 3600)))
CATALOG_MONDAY_MAX_SOURCE_AGE_SECONDS = int(
    os.environ.get("CATALOG_MONDAY_MAX_SOURCE_AGE_SECONDS", str(54 * 3600))
)
CATALOG_SCHEDULE_TIME_ZONE = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class LinkRecord:
    source_url: str
    dest_url: str
    anchor_text: str
    rank: int
    dataset: str


def validated_documentary_fee(value: Any) -> float:
    try:
        fee = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("MOTORINN_DOCUMENTARY_FEE must be a finite nonnegative number") from exc
    if not math.isfinite(fee) or fee < 0:
        raise RuntimeError("MOTORINN_DOCUMENTARY_FEE must be a finite nonnegative number")
    return fee


DOC_FEE = validated_documentary_fee(os.environ.get("MOTORINN_DOCUMENTARY_FEE", "180"))
CATALOG_URL = os.environ.get(
    "MOTORINN_PUBLIC_CATALOG_URL",
    "https://motorinn-public-compliance-768571908844.s3.us-east-2.amazonaws.com/"
    "meta/service-to-sales-catalog/motorinn-meta-inventory-feed.csv",
)
INVENTORY_BUCKET = os.environ.get("MOTORINN_INVENTORY_BUCKET", "motorinn-dealervault-raw")
INVENTORY_KEY = os.environ.get(
    "MOTORINN_INVENTORY_KEY",
    "normalized/current_inventory_market/latest/current-inventory-market.json",
)
ALLOW_TRAINING_CRAWLERS = os.environ.get("ALLOW_TRAINING_CRAWLERS", "false").lower() == "true"
QUERY_MAX_CHARS = 200
QUERY_MAX_RESULTS = 8
QUERY_DEFAULT_RESULTS = 5
QUERY_RATE_LIMIT = 60
QUERY_RATE_WINDOW_SECONDS = 60.0
QUERY_RATE_MAX_CLIENTS = 10_000
LEAD_RATE_LIMIT = 10
LEAD_RATE_WINDOW_SECONDS = 60.0
LEAD_UPSTREAM_TOKEN_PATH = "https://{www}/api/lead/new"
LEAD_UPSTREAM_SAVE_PATH = "https://{www}/api/lead/save"
LEAD_WWW = {
    "motorinnofcarroll": ("www.motorinnofcarroll.com", "https://www.motorinnofcarroll.com/contactus.aspx"),
    "motorinnautogroup": ("www.motorinnautogroup.com", "https://www.motorinnautogroup.com/contactus.html"),
    "motorinntoyotaofcarroll": ("www.motorinntoyotaofcarroll.com", "https://www.motorinntoyotaofcarroll.com/contactus.html"),
}
LEAD_WWW.setdefault("motorinnofcarroll", LEAD_WWW["motorinnofcarroll"])


logger = logging.getLogger("ai-markdown-proxy")
logging.basicConfig(level=logging.INFO, format="%(message)s")


@dataclass(frozen=True)
class Site:
    key: str
    content_slug: str
    name: str
    ai_host: str
    base_url: str
    new_make: str | None
    offers_path: str


SITES: dict[str, Site] = {
    "motorinnautogroup": Site(
        key="motorinnautogroup",
        content_slug="motorinnautogroup",
        name="Motor Inn Auto Group",
        ai_host="ai.motorinnautogroup.com",
        base_url="https://www.motorinnautogroup.com",
        new_make=None,
        offers_path="/specials.aspx",
    ),
    "motorinnchevy": Site(
        key="motorinnchevy",
        content_slug="motorinnofcarroll",
        name="Motor Inn of Carroll",
        ai_host="ai.motorinnofcarroll.com",
        base_url="https://www.motorinnofcarroll.com",
        new_make="CHEVROLET",
        offers_path="/newspecials.html",
    ),
    "motorinntoyota": Site(
        key="motorinntoyota",
        content_slug="motorinntoyotaofcarroll",
        name="Motor Inn Toyota Of Carroll",
        ai_host="ai.motorinntoyotaofcarroll.com",
        base_url="https://www.motorinntoyotaofcarroll.com",
        new_make="TOYOTA",
        offers_path="/newspecials.html",
    ),
}
HOST_TO_SITE = {site.ai_host: site.key for site in SITES.values()}
STATIC_FILES = {
    "llms.txt",
    "llms-full.txt",
    "dealership.md",
    "contact-hours.md",
    "service.md",
    "finance-trade.md",
    "policies.md",
}
DISCOVERY_PATHS = (
    "/",
    "/feed.json",
    "/llms.txt",
    "/llms-full.txt",
    "/agent-connection.md",
    "/dealership.md",
    "/contact-hours.md",
    "/service.md",
    "/finance-trade.md",
    "/policies.md",
    "/inventory.md",
    "/new-inventory.md",
    "/used-inventory.md",
    "/offers.md",
    "/openapi.json",
    "/api/v1/vehicles",
    "/api/v1/locations",
    "/api/v1/service-information",
    "/api/v1/parts-information",
    "/service-scheduler",
    "/mcp",
    "/mcp/customer",
    "/api",
    "/ai.txt",
    "/links/motorinnautogroup.html",
    "/links/motorinnofcarroll.html",
    "/links/motorinntoyotaofcarroll.html",
    "/skills.txt",
    "/.well-known/agents.json",
    "/.well-known/mcp.json",
    "/articles/used-trucks-towing-iowa",
)
AGENT_QUERY_EXAMPLES = (
    "/llms?query=service&limit=3",
    "/llms/json?query=service&limit=3",
)
MACHINE_FILES = STATIC_FILES | {"new-inventory.md", "used-inventory.md", "inventory.md", "offers.md", "robots.txt", "sitemap.xml"}
QUERY_STATIC_FILES = ("dealership.md", "contact-hours.md", "service.md", "finance-trade.md", "policies.md")
BOT_MARKERS = {
    "OAI-SearchBot": "openai-search",
    "ChatGPT-User": "openai-user",
    "GPTBot": "openai-training",
    "Claude-SearchBot": "anthropic-search",
    "ClaudeBot": "anthropic-training",
    "PerplexityBot": "perplexity-search",
    "Googlebot": "google-search",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
_page_cache: dict[str, dict[str, Any]] = {}
_catalog_cache: dict[str, Any] = {}
_inventory_cache: dict[str, Any] = {}
_query_rate_limits: dict[str, deque[float]] = {}
_query_rate_lock = threading.Lock()
_lead_rate_limits: dict[str, deque[float]] = {}
_lead_rate_lock = threading.Lock()


GBP_NAP = {
    "motorinnautogroup": {
        "name": "Motor Inn Toyota and Chevrolet of Carroll",
        "streetAddress": "1526 Le Clark Rd",
        "addressLocality": "Carroll",
        "addressRegion": "IA",
        "postalCode": "51401",
        "addressCountry": "US",
        "telephone": "+17127925000",
    },
    "motorinnchevy": {
        "name": "Motor Inn Chevrolet of Carroll",
        "streetAddress": "1526 Le Clark Rd",
        "addressLocality": "Carroll",
        "addressRegion": "IA",
        "postalCode": "51401",
        "addressCountry": "US",
        "telephone": "+17128827802",
    },
    "motorinntoyota": {
        "name": "Motor Inn Toyota and Chevrolet of Carroll",
        "streetAddress": "1526 Le Clark Rd",
        "addressLocality": "Carroll",
        "addressRegion": "IA",
        "postalCode": "51401",
        "addressCountry": "US",
        "telephone": "+17127925000",
    },
}
AGENT_READY_SCHEMA_VERSION = "v1"
AGENT_FLOWS = (
    {"name": "search-vehicles", "title": "Find vehicles", "openApiOperationId": "searchVehicles"},
    {"name": "get-vehicle", "title": "Get a vehicle", "openApiOperationId": "getVehicle"},
    {"name": "list-locations", "title": "List locations", "openApiOperationId": "listLocations"},
    {"name": "get-service-information", "title": "Get service information", "openApiOperationId": "getServiceInformation"},
    {"name": "get-parts-information", "title": "Get parts information", "openApiOperationId": "getPartsInformation"},
)
AGENT_NAMES = tuple(flow["name"] for flow in AGENT_FLOWS)
DEALERON_MCP_SERVER_VERSION = "2026-10-31"
DEALERON_MCP_ENDPOINT = "/mcp"
MCP_SERVER_INSTRUCTIONS = (
    "Use Motor Inn tools only for the dealership on this host. Use search_vehicles to find public inventory and get_vehicle only with an exact VIN from search_vehicles. Use list_locations for hours and contacts. Use get_service_information for service capability and its public next step. Use get_parts_information for parts capability only. Do not claim vehicle reservations, purchases, financing approvals, service bookings, part stock, fitment, or orders. Use search_public_website for validated policy and site pages. Use submit_lead only when the user asks for contact and supplies name, email, phone, and source; each submission creates a new lead and is not idempotent."
)
ASSETS_ROOT = Path(__file__).resolve().parent / "assets"
DEALER_PRIVACY_URLS = {
    "motorinnautogroup": "https://www.motorinnautogroup.com/privacy-policy",
    "motorinnchevy": "https://www.motorinnofcarroll.com/privacy.aspx",
    "motorinntoyota": "https://www.motorinntoyotaofcarroll.com/privacy.aspx",
}


def google_verification_tokens(site: Site) -> tuple[str, ...]:
    """Return the configured Google verification token for this site."""

    raw = os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip()
    if not raw:
        return ()
    if raw.startswith("{"):
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError:
            return ()
        if not isinstance(configured, dict):
            return ()
        value = configured.get(site.ai_host, configured.get("*"))
        return (value.strip(),) if isinstance(value, str) and value.strip() else ()
    return (raw,)


def google_connected_apps_certificate(site: Site) -> dict[str, Any]:
    return {"verification_tokens": list(google_verification_tokens(site))}


def connected_app_page(site: Site, title: str, body_html: str) -> Response:
    nap = GBP_NAP[site.key]
    customer_name = html.escape(nap["name"])
    address_line = html.escape(f"{nap['streetAddress']}, {nap['addressLocality']}, {nap['addressRegion']} {nap['postalCode']}")
    customer_website = html.escape(site.base_url)
    if title == "Privacy policy":
        body_html = f"""<h1>Privacy policy</h1>
          <p>This service does not require an account or login. It uses public dealership information.</p>
          <p>Lead submission may carry the name, email, phone, vehicle interest, message, and source provided by the person or their agent. Leads are forwarded to the dealership's existing contact-form system for customer follow-up.</p>
          <p>See the dealership's privacy policy for complete customer-data handling: <a href="{html.escape(DEALER_PRIVACY_URLS[site.key])}">{customer_name} privacy policy</a></p>
"""
    else:
        body_html = """<h1>Terms of service</h1>
          <p>This Motor Inn AI endpoint provides public dealership information and may create a customer lead when that is requested. No account is required.</p>
          <p>Do not use it for urgent vehicle or service needs. Purchases, financing, appointments, parts orders, and dealership commitments are confirmed only through Motor Inn staff or its published customer journeys.</p>
          <p>Tool results are generated from site-specific sources and freshness checks. Always confirm prices, eligibility, availability, appointments, and orders with Motor Inn before acting.</p>
          <p><a href="/privacy">Privacy policy</a></p>
"""
    html_page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,follow">
  <title>{html.escape(site.name)} · {html.escape(title)}</title>
  <style>
    body {{ margin: 0; background: #0B1F3A; color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif; }}
    main {{ box-sizing: border-box; max-width: 760px; margin: 0 auto; padding: 40px 24px; }}
    .mark {{ text-transform: uppercase; letter-spacing: .12em; font-weight: 700; font-size: 14px; }}
    h1 {{ margin: .2em 0 1em; font-size: 32px; }}
    p {{ line-height: 1.6; }}
    a {{ color: #8FCBFF; }}
    footer {{ margin-top: 32px; color: #C1D3E8; font-size: 14px; line-height: 1.6; }}
  </style>
</head>
<body>
  <main>
    <div class="mark">{customer_name}</div>
    {body_html}
    <footer>
      <address style="font-style: normal">{address_line}<br><a href="tel:{nap['telephone']}">{nap['telephone']}</a><br><a href="{customer_website}">Customer website</a></address>
    </footer>
  </main>
</body>
</html>
"""
    response = Response(html_page, content_type="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["X-Robots-Tag"] = "noindex, follow"
    return response


def local_business_schema(site: Site) -> dict[str, Any]:
    nap = GBP_NAP[site.key]
    return {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "@id": urljoin(site.base_url.rstrip("/") + "/", "#storefront"),
        "name": nap["name"],
        "telephone": nap["telephone"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": nap["streetAddress"],
            "addressLocality": nap["addressLocality"],
            "addressRegion": nap["addressRegion"],
            "postalCode": nap["postalCode"],
            "addressCountry": nap["addressCountry"],
        },
    }


def agents_json(site: Site) -> dict[str, Any]:
    base = f"https://{site.ai_host}"
    return {
        "$schema": "https://agents.spec.dev/S20251227/v1.json",
        "name": "Motor Inn Auto Group Agent Access",
        "description": f"Read-only public dealership API for {site.base_url}.",
        "version": "2026-10-29",
        "homePageUrl": site.base_url,
        "apiBaseUrl": base,
        "auth": "none",
        "capabilities": AGENT_NAMES,
        "flows": AGENT_FLOWS,
        "specUrl": f"{base}/openapi.json",
        "mcpBaseUrl": base,
    }


def mcp_server_card(site: Site) -> dict[str, Any]:
    return {
        "$schema": "https://spec.openapis.org/arap/mcp-server-card/v1.0.0",
        "name": site.name,
        "version": DEALERON_MCP_SERVER_VERSION,
        "description": "Read-only dealership information tools. It never transacts.",
        "servers": "https://server.modelcontextprotocol.io",
        "remotes": [{"url": f"https://{site.ai_host}{DEALERON_MCP_ENDPOINT}", "transport": "streamable-http"}],
        "auth": "none",
    }


class SourceUnavailable(RuntimeError):
    """Raised when a dynamic source cannot pass freshness or data checks."""


@dataclass(frozen=True)
class QueryDocument:
    id: str
    title: str
    body: str
    canonical_url: str
    source_url: str
    source_type: str
    freshness: str | None = None


@dataclass(frozen=True)
class QueryResult:
    id: str
    title: str
    snippet: str
    canonical_url: str
    source_url: str
    source_type: str
    freshness: str | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "snippet": self.snippet,
            "canonicalUrl": self.canonical_url,
            "sourceUrl": self.source_url,
            "sourceType": self.source_type,
            "freshness": self.freshness,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def source_age_seconds(value: datetime) -> float:
    return max(0.0, (utc_now() - value.astimezone(timezone.utc)).total_seconds())


def catalog_source_age_limit_seconds(now: datetime) -> int:
    """Allow the declared Mon-Sat feed cadence without hiding a missed run.

    The catalog is published at 4 PM America/Chicago Monday through Saturday.
    Monday is the only day that can legitimately see more than 36 hours of age,
    because there is no Sunday customer-marketing run.  A 54-hour Monday cap
    covers that expected interval but still fails Monday night if the scheduled
    Monday publication never occurs. DealerVault keeps the normal 36-hour cap.
    """

    local_now = now.astimezone(CATALOG_SCHEDULE_TIME_ZONE)
    if local_now.weekday() == 0:
        return max(MAX_SOURCE_AGE_SECONDS, CATALOG_MONDAY_MAX_SOURCE_AGE_SECONDS)
    return MAX_SOURCE_AGE_SECONDS


def classify_bot(user_agent: str) -> str:
    for marker, label in BOT_MARKERS.items():
        if marker.lower() in user_agent.lower():
            return label
    return "other"


def resolve_site() -> Site:
    host = request.host.split(":", 1)[0].lower()
    if host in HOST_TO_SITE:
        return SITES[HOST_TO_SITE[host]]
    requested = request.args.get("site", "motorinnautogroup")
    return SITES.get(requested, SITES["motorinnautogroup"])


def clean_query_string() -> str:
    pairs = [(key, value) for key, value in parse_qsl(request.query_string.decode(), keep_blank_values=True) if key != "site"]
    return urlencode(pairs, doseq=True)


def canonical_url(site: Site, path: str) -> str:
    target = urljoin(site.base_url.rstrip("/") + "/", path.lstrip("/"))
    query = clean_query_string()
    return f"{target}?{query}" if query else target


def normalize_query(value: str | None) -> str:
    if value is None:
        raise ValueError("query parameter is required")
    normalized = unicodedata.normalize("NFKC", value)
    if len(normalized) > QUERY_MAX_CHARS:
        raise ValueError(f"query must be at most {QUERY_MAX_CHARS} characters")
    normalized = "".join(" " if unicodedata.category(char).startswith("C") else char for char in normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        raise ValueError("query parameter must not be empty")
    return normalized


def lexical_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def lexical_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", lexical_text(value))


def query_limit(value: str | None) -> int:
    if value is None or value == "":
        return QUERY_DEFAULT_RESULTS
    try:
        limit = int(value)
    except ValueError as exc:
        raise ValueError(f"limit must be an integer from 1 to {QUERY_MAX_RESULTS}") from exc
    if not 1 <= limit <= QUERY_MAX_RESULTS:
        raise ValueError(f"limit must be from 1 to {QUERY_MAX_RESULTS}")
    return limit


def request_client_key() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    candidate = forwarded or request.remote_addr or "unknown"
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return "unknown"


def lead_rate_limit_allowed(client_key: str, now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    cutoff = current - LEAD_RATE_WINDOW_SECONDS
    with _lead_rate_lock:
        events = _lead_rate_limits.setdefault(client_key, deque())
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= LEAD_RATE_LIMIT:
            return False
        events.append(current)
        return True


def lead_upstream_token(www_host: str) -> str:
    response = requests.get(LEAD_UPSTREAM_TOKEN_PATH.format(www=www_host), timeout=20)
    response.raise_for_status()
    token = response.json()["token"]
    if not token:
        raise RuntimeError("upstream lead token missing")
    return token


def lead_upstream_payload(payload: dict[str, Any], entry_url: str = "https://www.motorinnofcarroll.com/contactus.aspx") -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    if " " in name:
        first_name, last_name = name.split(" ", 1)
    else:
        first_name, last_name = name, name
    message = str(payload.get("message", "")).strip()
    source = str(payload.get("source", "")).strip() or "AI Agent"
    marker = f"AI-MIRROR:{payload.get("_ai_host", "unknown")}"
    comments = f"{marker} | AI Agent ({source}) | {message}" if message else f"{marker} | AI Agent ({source})"
    return {
        "EntryUrl": entry_url,
        "LeadSource": 32,
        "LeadType": "9",
        "FirstName": first_name,
        "LastName": last_name,
        "Email": str(payload.get("email", "")).strip(),
        "Phone": str(payload.get("phone", "")).strip(),
        "Comments": comments,
        "IsPlatformForm": True,
        "GetBotDocUrl": False,
        "DisplayType": "in-page",
        "HoneypotFields": json.dumps({"fax_number": "", "address_line3": "", "ui_state": ""}),
        "LeadSourceName": f"AI-MIRROR:{payload.get("_ai_host", "unknown")}",
        "Campaign": "AI-MIRROR",
        "UtmSource": payload.get("_ai_host", "unknown"),
        "UtmMedium": "ai-agent",
        "UtmCampaign": f"ai-mirror-{payload.get("_site_key", "unknown")}",
        "Browser": "AI Agent Client",
        "OS": "unknown",
        "Device": "unknown",
    }


def submit_lead(arguments: dict[str, Any], site_key: str = "motorinnofcarroll", ai_host: str = "") -> dict[str, Any]:
    """Submit a lead through the same upstream field mapping."""
    source = arguments.pop("source", None) or "AI Agent"
    payload = dict(arguments)
    payload["source"] = source
    payload["_ai_host"] = ai_host
    try:
        www_host, entry_url = LEAD_WWW.get(site_key, LEAD_WWW["motorinnofcarroll"])
        token = lead_upstream_token(www_host)
        response = requests.post(
            LEAD_UPSTREAM_SAVE_PATH.format(www=www_host) + f"/{token}",
            json=lead_upstream_payload(payload, entry_url),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "MotorInn-AIReadableMirror/2.0 (+https://ai.motorinnofcarroll.com/llms.txt)",
            },
            timeout=20,
        )
        upstream_body = response.json()
    except requests.RequestException:
        return {"submitted": False, "reason": "Lead source unavailable"}
    reference = upstream_body.get("internalId") or upstream_body.get("leadId")
    if not reference:
        reference = str(uuid.uuid4())
    return {"submitted": True, "ref": str(reference), "leadSource": upstream_body.get("leadSource")}


@app.route("/lead", methods=["POST"])
@app.route("/api/v1/lead", methods=["POST"])
def serve_lead() -> Response:
    site = resolve_site()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "JSON object required"}), 400
    required = ("name", "email", "phone", "source")
    if any(not str(payload.get(key, "")).strip() for key in required):
        return jsonify({"ok": False, "error": "Missing required fields"}), 400
    client_key = request_client_key()
    if not lead_rate_limit_allowed(client_key):
        return jsonify({"ok": False, "error": "Too many requests"}), 429
    www_host, entry_url = LEAD_WWW.get(site.key, LEAD_WWW["motorinnofcarroll"])
    payload["_entry_url"] = entry_url
    payload["_ai_host"] = site.ai_host
    payload["_site_key"] = site.key
    upstream_payload = lead_upstream_payload(payload)
    upstream_payload["EntryUrl"] = entry_url
    try:
        token = lead_upstream_token(www_host)
        response = requests.post(
            LEAD_UPSTREAM_SAVE_PATH.format(www=www_host) + f"/{token}",
            json=upstream_payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "MotorInn-AIReadableMirror/2.0 (+https://ai.motorinnofcarroll.com/llms.txt)",
            },
            timeout=20,
        )
        upstream_body = response.json()
    except requests.RequestException:
        logger.exception("lead upstream request failed")
        return jsonify({"ok": False, "error": "Lead source unavailable"}), 503
    if response.status_code >= 400:
        return jsonify({
            "ok": False,
            "error": "Lead source rejected the request",
            "status": response.status_code,
            "upstream": upstream_body,
        }), response.status_code
    reference = upstream_body.get("internalId") or upstream_body.get("internal_id")
    if not reference:
        reference = upstream_body.get("leadId")
    if not reference:
        reference = str(uuid.uuid4())
    return jsonify({"ok": True, "ref": str(reference), "upstream": upstream_body}), 200


def submit_lead_tool(profile: str = "default") -> dict[str, Any]:
    """Return the MCP tool definition for lead submission."""
    return {
        "name": "submit_lead",
        "title": "Submit a customer lead",
        "description": "Create a lead for this dealership. This is the only write action available here.",
        "inputSchema": {
            "type": "object",
            "required": ["name", "email", "phone", "source"],
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "email": {"type": "string", "minLength": 5, "maxLength": 160},
                "phone": {"type": "string", "minLength": 7, "maxLength": 32},
                "vehicle": {"type": "string", "maxLength": 200},
                "message": {"type": "string", "maxLength": 2000},
                "source": {"type": "string", "minLength": 1, "maxLength": 120},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "required": ["ok", "ref"],
            "properties": {
                "ok": {"type": "boolean", "const": True},
                "ref": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    }


def query_rate_limit_allowed(client_key: str, now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    cutoff = current - QUERY_RATE_WINDOW_SECONDS
    with _query_rate_lock:
        if client_key not in _query_rate_limits and len(_query_rate_limits) >= QUERY_RATE_MAX_CLIENTS:
            expired = [key for key, values in _query_rate_limits.items() if not values or values[-1] <= cutoff]
            for key in expired:
                del _query_rate_limits[key]
            if len(_query_rate_limits) >= QUERY_RATE_MAX_CLIENTS:
                oldest_key = min(_query_rate_limits, key=lambda key: _query_rate_limits[key][-1])
                del _query_rate_limits[oldest_key]
        events = _query_rate_limits.setdefault(client_key, deque())
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= QUERY_RATE_LIMIT:
            return False
        events.append(current)
        return True


def sanitized_query_for_telemetry(query: str) -> str:
    sanitized = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[redacted-email]", query, flags=re.I)
    sanitized = re.sub(r"(?<!\w)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\w)", "[redacted-phone]", sanitized)
    sanitized = re.sub(r"\b[A-HJ-NPR-Z0-9]{17}\b", "[redacted-vin]", sanitized, flags=re.I)
    sanitized = re.sub(
        r"\b(?=[A-Z0-9_-]{12,}\b)(?=[A-Z0-9_-]*\d)[A-Z0-9_-]+\b",
        "[redacted-id]",
        sanitized,
        flags=re.I,
    )
    sanitized = re.sub(
        r"\b(?=[A-Za-z]{16,}\b)(?=[A-Za-z]*[A-Z])(?=[A-Za-z]*[a-z])[A-Za-z]+\b",
        "[redacted-id]",
        sanitized,
    )
    sanitized = re.sub(
        r"\b(my name is|i am|i'm|this is)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}",
        lambda match: f"{match.group(1)} [redacted-name]",
        sanitized,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", sanitized).strip()


def cache_get(cache: dict[str, dict[str, Any]], key: str, ttl: int) -> Any | None:
    entry = cache.get(key)
    if entry and (time.time() - entry["cached_at"]) < ttl:
        return entry["value"]
    return None


def cache_set(cache: dict[str, dict[str, Any]], key: str, value: Any, max_entries: int = 500) -> None:
    cache[key] = {"cached_at": time.time(), "value": value}
    if len(cache) > max_entries:
        oldest = min(cache, key=lambda item: cache[item]["cached_at"])
        del cache[oldest]


def fetch_page(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": "MotorInn-AIReadableMirror/2.0 (+https://ai.motorinnautogroup.com/llms.txt)",
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=20,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def clean_html_to_markdown(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript", "iframe", "svg", "link", "meta", "nav", "header", "footer", "aside"]):
        tag.decompose()
    for element in soup.find_all(True):
        if element.attrs is None or element.parent is None:
            continue
        classes = element.get("class", [])
        class_text = " ".join(classes) if isinstance(classes, list) else str(classes)
        element_id = str(element.get("id", "") or "")
        if re.search(r"nav|footer|header|sidebar|menu|breadcrumb|social", f"{class_text} {element_id}", re.I):
            element.decompose()
    for image in soup.find_all("img"):
        if image.get("src"):
            image["src"] = urljoin(base_url, image["src"])
    for anchor in soup.find_all("a"):
        if anchor.get("href"):
            anchor["href"] = urljoin(base_url, anchor["href"])
    body = soup.find("body") or soup
    markdown = markdownify(str(body), heading_style="ATX", bullets="-")
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def static_content(site: Site, filename: str) -> str:
    path = CONTENT_ROOT / site.content_slug / filename
    if not path.is_file():
        raise SourceUnavailable(f"validated content missing: {site.content_slug}/{filename}")
    content = path.read_text(encoding="utf-8")
    for machine_file in MACHINE_FILES:
        content = content.replace(f"{site.base_url}/{machine_file}", f"https://{site.ai_host}/{machine_file}")
    return content


def content_manifest_generated_at() -> str | None:
    try:
        manifest = json.loads((CONTENT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    generated_at = manifest.get("generatedAt")
    return str(generated_at) if generated_at else None


def llms_content(site: Site, filename: str) -> str:
    body = static_content(site, filename).rstrip()
    markdown_url = f"https://{site.ai_host}/llms?query=service&limit=3"
    json_url = f"https://{site.ai_host}/llms/json?query=service&limit=3"
    nudge = (
        "## Deterministic agent query\n\n"
        "Search only this site's rendered public and validated content. Results are excerpts with source links, not generated answers.\n\n"
        f"- [Markdown query example]({markdown_url})\n"
        f"- [JSON query example]({json_url})\n"
        f"- [OpenAPI 3.1 contract](https://{site.ai_host}/openapi.json)\n"
        f"- [Stable service scheduler handoff](https://{site.ai_host}/service-scheduler)\n"
        f"- [Customer agent connection guide](https://{site.ai_host}/agent-connection.md)\n"
        f"- [Customer agent MCP endpoint](https://{site.ai_host}/mcp/customer)\n"
        f"- [Existing read-only MCP endpoint](https://{site.ai_host}/mcp)"
    )
    return f"{body}\n\n{nudge}\n\n## Guides\n\n{_article_catalog_sections(site)}\n"


FEED_LINE = "# machine-readable: /feed.json"


def feed_items(site: Site) -> list[dict[str, str]]:
    """Build the machine-readable page feed from the site's existing llms.txt links."""
    text = static_content(site, "llms.txt")
    manifest_generated_at = content_manifest_generated_at()
    llms_mtime = datetime.fromtimestamp(
        (CONTENT_ROOT / site.content_slug / "llms.txt").stat().st_mtime, timezone.utc
    )
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(r"^\s*-\s*\[([^\]]+)\]\(([^)]+)\)(?::\s*(.+))?$", re.MULTILINE)
    for match in pattern.finditer(text):
        title = match.group(1).strip()
        url = match.group(2).strip()
        summary = re.sub(r"\s+", " ", (match.group(3) or "")).strip()
        if url in seen:
            continue
        seen.add(url)
        parsed = urlsplit(url)
        local_name = parsed.path.lstrip("/")
        candidate = CONTENT_ROOT / site.content_slug / local_name
        if candidate.is_file() and candidate.stat().st_mtime:
            updated = iso_timestamp(datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc))
        else:
            updated = manifest_generated_at or iso_timestamp(llms_mtime)
        items.append({"site": site.key, "url": url, "title": title, "updated": updated, "summary": summary})
    return items


def canonical_catalog_link(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def load_catalog() -> tuple[list[dict[str, str]], datetime]:
    cached = cache_get(_catalog_cache, "catalog", DYNAMIC_CACHE_TTL_SECONDS)
    if cached:
        return cached
    response = requests.get(CATALOG_URL, timeout=20)
    response.raise_for_status()
    modified_text = response.headers.get("Last-Modified")
    modified = parsedate_to_datetime(modified_text) if modified_text else utc_now()
    if source_age_seconds(modified) > catalog_source_age_limit_seconds(utc_now()):
        raise SourceUnavailable(f"public catalog stale: last modified {iso_timestamp(modified)}")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    if not rows:
        raise SourceUnavailable("public catalog is empty")
    value = (rows, modified)
    cache_set(_catalog_cache, "catalog", value, max_entries=1)
    return value


def load_private_inventory() -> tuple[list[dict[str, Any]], datetime]:
    cached = cache_get(_inventory_cache, "inventory", DYNAMIC_CACHE_TTL_SECONDS)
    if cached:
        return cached
    response = boto3.client("s3").get_object(Bucket=INVENTORY_BUCKET, Key=INVENTORY_KEY)
    modified = response["LastModified"]
    if source_age_seconds(modified) > MAX_SOURCE_AGE_SECONDS:
        raise SourceUnavailable(f"DealerVault inventory stale: last modified {iso_timestamp(modified)}")
    rows = json.loads(response["Body"].read().decode("utf-8"))
    if not isinstance(rows, list) or not rows:
        raise SourceUnavailable("DealerVault inventory export is empty")
    value = (rows, modified)
    cache_set(_inventory_cache, "inventory", value, max_entries=1)
    return value


def row_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("stock_number") or row.get("id") or "").upper(), str(row.get("vin") or "").upper()


def match_rows() -> tuple[list[dict[str, Any]], datetime, datetime]:
    catalog_rows, catalog_modified = load_catalog()
    inventory_rows, inventory_modified = load_private_inventory()
    stock_index: dict[str, set[int]] = {}
    vin_index: dict[str, set[int]] = {}
    for index, row in enumerate(inventory_rows):
        stock, vin = row_key(row)
        if stock:
            stock_index.setdefault(stock, set()).add(index)
        if vin:
            vin_index.setdefault(vin, set()).add(index)
    matched: list[dict[str, Any]] = []
    for public_row in catalog_rows:
        stock, vin = row_key(public_row)
        identifier_matches = []
        if stock:
            identifier_matches.append(stock_index.get(stock, set()))
        if vin:
            identifier_matches.append(vin_index.get(vin, set()))
        if not identifier_matches:
            continue
        candidate_indexes = set.intersection(*identifier_matches)
        if len(candidate_indexes) == 1 and public_row.get("link"):
            source_row = inventory_rows[next(iter(candidate_indexes))]
            matched.append({**public_row, "dealerVault": source_row})
    if not matched:
        raise SourceUnavailable("DealerVault and public catalog have no matching active units")
    return matched, catalog_modified, inventory_modified


def number(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").split()[0])
    except ValueError:
        return 0.0


def display_price(source: dict[str, Any]) -> float:
    base_price = number(source.get("internet_price")) or number(source.get("list_price")) or number(source.get("msrp"))
    return base_price + DOC_FEE if base_price > 0 else 0.0


def render_inventory(site: Site, condition: str) -> str:
    rows, catalog_modified, inventory_modified = match_rows()
    filtered = []
    for row in rows:
        if row.get("condition", "").lower() != condition:
            continue
        if condition == "new" and site.new_make and row.get("vehicle_make", "").upper() != site.new_make:
            continue
        filtered.append(row)
    filtered.sort(key=lambda item: (-int(number(item.get("vehicle_year"))), item.get("vehicle_make", ""), item.get("vehicle_model", "")))
    title = "New inventory" if condition == "new" else "Pre-owned inventory"
    lines = [
        f"# {site.name} - {title}",
        "",
        f"> Active units matched between the current DealerVault/Athena export and DealerOn's public catalog. Total: {len(filtered)}.",
        "",
        f"DealerVault last updated: {iso_timestamp(inventory_modified)}  ",
        f"Public catalog last updated: {iso_timestamp(catalog_modified)}",
        "",
    ]
    if not filtered:
        lines.extend(["No matching active inventory is currently published.", ""])
    for row in filtered:
        source = row["dealerVault"]
        vehicle = " ".join(
            part for part in [row.get("vehicle_year"), row.get("vehicle_make"), row.get("vehicle_model"), row.get("vehicle_trim")] if part
        )
        price = display_price(source)
        lines.extend([f"## {vehicle}", ""])
        if price:
            lines.append(f"- Price: ${price:,.0f}, including ${DOC_FEE:,.0f} documentation fee. Plus tax, title, and license.")
        if condition == "used" and number(source.get("odometer")):
            lines.append(f"- Mileage: {number(source.get('odometer')):,.0f} miles")
        dv = source if isinstance(source, dict) else {}
        trim_val = str(row.get("vehicle_trim") or dv.get("vehicle_trim") or "").strip()
        if trim_val:
            lines.append(f"- Trim: {trim_val}")
        for label, key in (("Body style", "vehicle_body"), ("Exterior color", "exterior_color"), ("Interior color", "interior_color"), ("Engine", "engine_desc"), ("Fuel type", "fuel_type"), ("Transmission", "transmission_desc")):
            val = str(dv.get(key) or "").strip()
            if val:
                lines.append(f"- {label}: {val}")
        lines.extend(
            [
                f"- VIN: {row.get('vin', '')}",
                f"- Availability: {row.get('availability', 'in stock')}",
                f"- [View current vehicle details]({canonical_catalog_link(row.get('link', ''))})",
            ]
        )
        if row.get("image_link"):
            lines.append(f"- [Current inventory photo]({row['image_link']})")
        lines.append("")
    lines.extend(
        [
            "Availability and equipment can change. Confirm current details on the linked vehicle page or with Motor Inn Auto Group.",
            "No customer or lead data is included in this resource.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


INVENTORY_CACHE_TTL_SECONDS = 24 * 3600


def inventory_table_markdown(site: Site) -> str:
    rows, catalog_modified, inventory_modified = match_rows()
    header = "| VIN | Year | Make | Model | Trim | Price | Miles | Body | Photo | Dealer comments |"
    separator = "|---|---:|---|---|---|---:|---:|---|---|---|"
    lines = [
        f"# {site.name} - Live inventory",
        "",
        f"> Active units matched between DealerVault/Athena and DealerOn's public catalog. Total: {len(rows)}.",
        "",
        f"DealerVault last updated: {iso_timestamp(inventory_modified)}  ",
        f"Public catalog last updated: {iso_timestamp(catalog_modified)}",
        "",
        header,
        separator,
    ]
    for row in rows:
        source = row["dealerVault"] if isinstance(row.get("dealerVault"), dict) else {}
        price = display_price(source)
        miles = number(source.get("odometer")) or number(row.get("odometer"))
        body = str(row.get("vehicle_body") or row.get("body_style") or source.get("vehicle_body") or "not stated").strip()
        comments = str(source.get("dealer_comments") or source.get("dealerComments") or row.get("dealer_comments") or "not published").strip()
        photo = row.get("image_link") or ""
        lines.append(
            "| "
            + " | ".join([
                str(row.get("vin") or "not stated"),
                str(row.get("vehicle_year") or "not stated"),
                str(row.get("vehicle_make") or "not stated"),
                str(row.get("vehicle_model") or "not stated"),
                str(row.get("vehicle_trim") or (source.get("vehicle_trim") if isinstance(source, dict) else None) or "not stated"),
                f"${price:,.0f}" if price else "not stated",
                f"{miles:,.0f}" if miles else "not stated",
                body,
                f"[photo]({photo})" if photo.startswith("http") else "not stated",
                " ".join(comments.split()),
            ])
            + " |"
        )
    lines.extend([
        "",
        "No customer or lead data is included in this resource.",
        "Availability and equipment can change. Confirm current details on the linked vehicle page or with Motor Inn Auto Group.",
    ])
    return "\n".join(lines).strip() + "\n"


def rendered_inventory_table(site: Site) -> str:
    key = f"inventory-table:{site.key}"
    body = cache_get(_page_cache, key, INVENTORY_CACHE_TTL_SECONDS)
    if body is None:
        body = inventory_table_markdown(site)
        cache_set(_page_cache, key, body)
    return body


def render_offers(site: Site) -> str:
    source_url = urljoin(site.base_url.rstrip("/") + "/", site.offers_path.lstrip("/"))
    markdown = clean_html_to_markdown(fetch_page(source_url), site.base_url)
    return (
        f"# {site.name} - Current offers\n\n"
        f"> Source: [{source_url}]({source_url}). Offer eligibility, expiration, and disclosures remain controlling.\n\n"
        f"{markdown}\n"
    )


def rendered_offers(site: Site) -> str:
    key = f"offers:{site.key}"
    body = cache_get(_page_cache, key, 900)
    if body is None:
        body = render_offers(site)
        cache_set(_page_cache, key, body)
    return body


def markdown_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            return markdown_plain_text(match.group(1)) or fallback
    return fallback


def markdown_plain_text(value: str) -> str:
    value = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"<https?://[^>]+>", "", value)
    value = re.sub(r"^[#>*+\-\s]+", "", value)
    value = value.replace("`", "").replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", value).strip()


def first_public_url(body: str, fallback: str) -> str:
    match = re.search(r"https?://[^\s)>\]]+", body)
    return match.group(0) if match else fallback


def inventory_freshness(body: str) -> str | None:
    timestamps = re.findall(r"(?:DealerVault|Public catalog) last updated:\s*([^\s]+)", body)
    parsed: list[datetime] = []
    for value in timestamps:
        try:
            parsed.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            continue
    return iso_timestamp(min(parsed)) if parsed else None


def build_static_query_documents(site: Site) -> list[QueryDocument]:
    freshness = content_manifest_generated_at()
    documents: list[QueryDocument] = []
    for filename in QUERY_STATIC_FILES:
        body = static_content(site, filename)
        documents.append(
            QueryDocument(
                id=f"{site.key}:{filename.removesuffix('.md')}",
                title=markdown_title(body, filename),
                body=body,
                canonical_url=first_public_url(body, site.base_url),
                source_url=f"https://{site.ai_host}/{filename}",
                source_type="static",
                freshness=freshness,
            )
        )
    return documents


def build_query_documents(site: Site) -> list[QueryDocument]:
    documents = build_static_query_documents(site)
    for condition in ("new", "used"):
        filename = f"{condition}-inventory.md"
        try:
            body = render_inventory(site, condition)
        except Exception as exc:  # noqa: BLE001
            logger.warning(json.dumps({"event": "query_source_unavailable", "site": site.key, "sourceType": "inventory", "error": str(exc)}))
            continue
        documents.append(
            QueryDocument(
                id=f"{site.key}:{condition}-inventory",
                title=markdown_title(body, filename),
                body=body,
                canonical_url=urljoin(site.base_url.rstrip("/") + "/", "searchnew.aspx" if condition == "new" else "searchused.aspx"),
                source_url=f"https://{site.ai_host}/{filename}",
                source_type="inventory",
                freshness=inventory_freshness(body),
            )
        )
    try:
        offers_body = rendered_offers(site)
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({"event": "query_source_unavailable", "site": site.key, "sourceType": "offers", "error": str(exc)}))
    else:
        documents.append(
            QueryDocument(
                id=f"{site.key}:offers",
                title=markdown_title(offers_body, "Current offers"),
                body=offers_body,
                canonical_url=urljoin(site.base_url.rstrip("/") + "/", site.offers_path.lstrip("/")),
                source_url=f"https://{site.ai_host}/offers.md",
                source_type="offers",
            )
        )
    return documents


def lexical_score(query: str, document: QueryDocument) -> int:
    query_text = lexical_text(query)
    tokens = list(dict.fromkeys(lexical_tokens(query)))
    if not tokens:
        return 0
    title = lexical_text(document.title)
    body = lexical_text(document.body)
    score = 0
    if query_text in title:
        score += 80
    if query_text in body:
        score += 30
    for token in tokens:
        score += title.count(token) * 12
        score += min(body.count(token), 12) * 2
    combined_tokens = set(lexical_tokens(f"{document.title} {document.body}"))
    if all(token in combined_tokens for token in tokens):
        score += 20
    return score


def result_snippet(query: str, document: QueryDocument, max_chars: int = 320) -> str:
    tokens = list(dict.fromkeys(lexical_tokens(query)))
    candidates: list[tuple[int, int, str]] = []
    for index, line in enumerate(document.body.splitlines()):
        plain = markdown_plain_text(line)
        if not plain or plain == document.title:
            continue
        searchable = lexical_text(plain)
        score = sum(searchable.count(token) for token in tokens)
        if tokens and all(token in searchable for token in tokens):
            score += 5
        candidates.append((score, -index, plain))
    if not candidates:
        return document.title[:max_chars]
    snippet = max(candidates, key=lambda item: (item[0], item[1], item[2]))[2]
    if len(snippet) <= max_chars:
        return snippet
    return snippet[: max_chars - 1].rstrip() + "..."


def rank_query_documents(query: str, documents: list[QueryDocument], limit: int) -> list[QueryResult]:
    ranked = [(lexical_score(query, document), document) for document in documents]
    ranked = [(score, document) for score, document in ranked if score > 0]
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [
        QueryResult(
            id=document.id,
            title=document.title,
            snippet=result_snippet(query, document),
            canonical_url=document.canonical_url,
            source_url=document.source_url,
            source_type=document.source_type,
            freshness=document.freshness,
        )
        for _, document in ranked[:limit]
    ]


def query_public_content(site: Site, query: str, limit: int) -> list[QueryResult]:
    return rank_query_documents(query, build_query_documents(site), limit)


def query_payload(site: Site, results: list[QueryResult]) -> dict[str, Any]:
    return {
        "schema": "motorinn.llmsQuery.v1",
        "site": {"key": site.key, "name": site.name, "host": site.ai_host},
        "resultCount": len(results),
        "noResults": not results,
        "results": [result.public_dict() for result in results],
    }


def query_markdown(site: Site, results: list[QueryResult]) -> str:
    lines = [f"# {site.name} query results", "", f"Results: {len(results)}", ""]
    if not results:
        lines.extend(["No matching published content was found.", ""])
    for result in results:
        lines.extend(
            [
                f"## {result.title}",
                "",
                result.snippet,
                "",
                f"- Result ID: `{result.id}`",
                f"- Source type: `{result.source_type}`",
                f"- Source: {result.source_url}",
                f"- Canonical: {result.canonical_url}",
            ]
        )
        if result.freshness:
            lines.append(f"- Freshness: {result.freshness}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def log_query_telemetry(site: Site, query: str, results: list[QueryResult], started_at: float) -> None:
    sanitized_query = sanitized_query_for_telemetry(query)
    logger.info(
        json.dumps(
            {
                "event": "llms_query",
                "timestamp": iso_timestamp(utc_now()),
                "sanitizedQuery": sanitized_query,
                "queryHash": hashlib.sha256(sanitized_query.casefold().encode("utf-8")).hexdigest(),
                "bot": classify_bot(request.headers.get("User-Agent", "")),
                "host": request.host.split(":", 1)[0].lower(),
                "resultCount": len(results),
                "topResultIds": [result.id for result in results[:3]],
                "noResults": not results,
                "latencyMs": round((time.perf_counter() - started_at) * 1000, 1),
                "site": site.key,
            },
            sort_keys=True,
        )
    )


def parse_agent_query() -> tuple[str, int]:
    query_values = request.args.getlist("query")
    if len(query_values) != 1:
        raise ValueError("exactly one query parameter is required")
    limit_values = request.args.getlist("limit")
    if len(limit_values) > 1:
        raise ValueError("limit must be provided at most once")
    return normalize_query(query_values[0]), query_limit(limit_values[0] if limit_values else None)


def agent_query_error(message: str, status: int, *, as_json: bool) -> Response:
    if as_json:
        response = jsonify({"error": message, "status": status})
        response.status_code = status
    else:
        response = markdown_response(f"# Query error\n\n{message}\n", status=status, max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def serve_agent_query(*, as_json: bool) -> Response:
    if not query_rate_limit_allowed(request_client_key()):
        response = agent_query_error("query rate limit exceeded", 429, as_json=as_json)
        response.headers["Retry-After"] = "60"
        return response
    started_at = time.perf_counter()
    try:
        query, limit = parse_agent_query()
    except ValueError as exc:
        return agent_query_error(str(exc), 400, as_json=as_json)
    site = resolve_site()
    try:
        results = query_public_content(site, query, limit)
    except Exception as exc:  # noqa: BLE001
        results = []
        log_query_telemetry(site, query, results, started_at)
        logger.error(json.dumps({"event": "query_layer_failure", "site": site.key, "error": str(exc)}))
        return agent_query_error("published query sources are temporarily unavailable", 503, as_json=as_json)
    log_query_telemetry(site, query, results, started_at)
    if as_json:
        response = jsonify(query_payload(site, results))
    else:
        response = markdown_response(query_markdown(site, results), max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def agent_query_health() -> dict[str, Any]:
    checked_sites = []
    for site in SITES.values():
        results = rank_query_documents("service", build_static_query_documents(site), 1)
        if not results:
            raise SourceUnavailable(f"agent query static canary failed for {site.key}")
        checked_sites.append(site.ai_host)
    return {
        "status": "ok",
        "checkedSites": sorted(checked_sites),
        "defaultResults": QUERY_DEFAULT_RESULTS,
        "maxResults": QUERY_MAX_RESULTS,
        "maxQueryChars": QUERY_MAX_CHARS,
        "rateLimitPerMinute": QUERY_RATE_LIMIT,
    }


def markdown_response(body: str, *, canonical: str | None = None, status: int = 200, max_age: int = 3600) -> Response:
    response = Response(body, status=status, content_type="text/markdown; charset=utf-8")
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    response.headers["Vary"] = "Accept"
    if canonical:
        response.headers["Link"] = f'<{canonical}>; rel="canonical"'
    return response


def text_response(body: str, *, max_age: int = 3600) -> Response:
    response = Response(body, content_type="text/plain; charset=utf-8")
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    return response


def xml_response(body: str, *, max_age: int = 3600) -> Response:
    response = Response(body, content_type="application/xml; charset=utf-8")
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    return response


@lru_cache(maxsize=1)
def link_records() -> tuple[LinkRecord, ...]:
    records: list[LinkRecord] = []
    for dataset_dir in sorted(AUDIT_DATA_ROOT.glob("*/")):
        links_path = dataset_dir / "links.csv"
        if not links_path.exists():
            continue
        with links_path.open(newline="", encoding="utf-8") as source:
            for rank, row in enumerate(csv.DictReader(source)):
                records.append(
                    LinkRecord(
                        source_url=row["source_url"],
                        dest_url=row["dest_url"],
                        anchor_text=row["anchor_text"],
                        rank=rank,
                        dataset=dataset_dir.name,
                    )
                )
    return tuple(records)


def link_records_for_site(site: Site) -> tuple[LinkRecord, ...]:
    canonical_host = urlsplit(site.base_url).hostname or ""
    dataset_name = f"{site.content_slug}.com"
    records = (
        record
        for record in link_records()
        if url_host(record.source_url) in {canonical_host, site.ai_host}
    )
    return tuple(sorted(records, key=lambda record: (record.dataset != dataset_name, record.rank)))


def related_link_records(site: Site, source_path: str) -> tuple[LinkRecord, ...]:
    normalized_path = "/" + source_path.lstrip("/")
    return tuple(
        record
        for record in link_records_for_site(site)
        if urlsplit(record.source_url).path == normalized_path
    )


def mirror_href(site: Site, target_url: str) -> str:
    target = urlsplit(target_url)
    canonical_host = urlsplit(site.base_url).hostname or ""
    if url_host(target_url) in {canonical_host, site.ai_host}:
        return urlunsplit(("", "", target.path or "/", target.query, target.fragment))
    return target_url


def url_host(target_url: str) -> str | None:
    parsed = urlsplit(target_url)
    if parsed.hostname:
        return parsed.hostname
    return urlsplit(f"https://{target_url}").hostname


@lru_cache(maxsize=10)
def hub_urls_for_site(site: Site) -> tuple[str, ...]:
    hub_path = AUDIT_DATA_ROOT / f"{site.content_slug}.com" / "hubs.md"
    if not hub_path.exists():
        return ()
    urls: list[str] = []
    for line in hub_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*-\s+URL:\s*(\S+)", line)
        if match:
            urls.append(match.group(1))
    return tuple(urls)


def source_is_hub(site: Site, source_path: str) -> bool:
    normalized_path = "/" + source_path.lstrip("/")
    hub_paths = {urlsplit(url).path for url in hub_urls_for_site(site)}
    return normalized_path in hub_paths


@lru_cache(maxsize=32)
def article_catalog() -> tuple[dict[str, str], ...]:
    return (
        {
            "slug": "used-trucks-towing-iowa",
            "title": "Used Trucks for Towing in Iowa: How to Pick a Truck You Can Trust",
            "description": (
                "Use tow ratings, payload, hitch setup and service records to shop used trucks for towing in Iowa. "
                "Compare Silverado 1500, F-150 and Ram 1500 ranges."
            ),
            "published": ARTICLE_DATE_PUBLISHED,
        },
    )


def article_href(site: Site, slug: str) -> str:
    return f"https://{site.ai_host}/articles/{slug}"


def article_links_path(site: Site) -> str:
    return f"/links/{site.key}.html"


def article_contact_url(site: Site) -> str:
    if site.base_url == "https://www.motorinnofcarroll.com":
        return f"{site.base_url}/contactus.aspx"
    return f"{site.base_url}/contactus.html"


def _article_catalog_sections(site: Site) -> str:
    return "\n".join(
        f"- [{record['title']}]({article_href(site, record['slug'])}): {record['description']}"
        for record in article_catalog()
    )


def _article_page_html(site: Site, record: dict[str, str]) -> str:
    source = BeautifulSoup((ARTICLE_ROOT / f"{record['slug']}.html").read_text(encoding="utf-8"), "html.parser")
    article_url = article_href(site, record["slug"])
    for anchor in source.find_all("a"):
        href = anchor.get("href")
        if not href:
            continue
        parsed = urlsplit(href)
        hostname = parsed.hostname or "www.motorinnautogroup.com"
        if parsed.path == "/used-trucks" and hostname == "www.motorinnautogroup.com":
            anchor["href"] = "/used-inventory.md"
        elif parsed.path == "/contactus" and hostname == "www.motorinnautogroup.com":
            anchor["href"] = article_contact_url(site)
    source.append(BeautifulSoup(
        f'<footer class="article-footer"><p>Automated readers can find related pages at '
        f'<a href="{article_links_path(site)}">{site.name} related pages</a>.</p></footer>',
        "html.parser",
    ))
    page_schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": record["title"],
        "description": record["description"],
        "author": {"@type": "Organization", "name": "Motor Inn Auto Group"},
        "publisher": {
            "@type": "Organization",
            "name": "Motor Inn Auto Group",
            "url": "https://www.motorinnautogroup.com",
        },
        "datePublished": record["published"],
        "dateModified": record["published"],
        "mainEntityOfPage": article_url,
        "isAccessibleForFree": True,
    }
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(record['title'])}</title>
    <meta name="description" content="{html.escape(record['description'])}">
    <meta name="robots" content="index,follow">
    <link rel="canonical" href="{html.escape(article_url)}">
    <script type="application/ld+json">{json.dumps(page_schema, ensure_ascii=False)}</script>
  </head>
  <body>
    <main>{source}</main>
  </body>
</html>
"""


def article_html(site: Site, slug: str) -> str:
    record = next((entry for entry in article_catalog() if entry["slug"] == slug), None)
    if record is None:
        return ""
    return _article_page_html(site, record)


def related_links_page(site: Site) -> str:
    records = link_records_for_site(site)
    visible_top20 = records[:20]
    remainder = records[20:]

    def anchor_list(items: list["LinkRecord"]) -> str:
        return "\n".join(
            '        <li><a href="{}" rel="internal follow">{}</a></li>'.format(
                html.escape(mirror_href(site, record.dest_url)),
                html.escape(record.anchor_text),
            )
            for record in items
        )

    top_markup = "<ul>\n{}\n      </ul>".format(anchor_list(visible_top20)) if visible_top20 else "<p>No top-20 links are assigned to this host.</p>"
    remainder_markup = "<ul>\n{}\n      </ul>".format(anchor_list(remainder)) if remainder else "<p>No additional links are assigned to this host.</p>"
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,follow">
    <link rel="canonical" href="https://{site.ai_host}/links/{site.key}.html">
    <title>{html.escape(site.name)} related pages</title>
  </head>
  <body>
    <section id="related-pages">
      <main>
        <h1>{html.escape(site.name)} related pages</h1>
        <h2>Top 20</h2>
        {top_markup}
        <h2>All supporting links</h2>
        {remainder_markup}
      </main>
    </section>
    <section id="guides">
      <main>
        <h2>Guides</h2>
        <ul>
{'\n'.join(f'          <li><a href="{article_href(site, record["slug"])}">{html.escape(record["title"])}</a></li>' for record in article_catalog())}
        </ul>
      </main>
    </section>
  </body>
</html>
"""


def inject_related_links(page_html: str, site: Site, source_path: str) -> str:
    records = related_link_records(site, source_path)
    soup = BeautifulSoup(page_html, "html.parser")
    section = soup.new_tag("section", id="related-pages")
    heading = soup.new_tag("h2")
    heading.string = "Explore" if source_is_hub(site, source_path) else "Related pages"
    section.append(heading)
    if records:
        item_list = soup.new_tag("ul")
        for record in records:
            item = soup.new_tag("li")
            anchor = soup.new_tag("a", href=mirror_href(site, record.dest_url), rel="internal follow")
            anchor.string = record.anchor_text
            item.append(anchor)
            item_list.append(item)
        section.append(item_list)
    soup.find("body").append(section)
    return str(soup)


def sitemap_xml(site: Site) -> str:
    eligible_paths = DISCOVERY_PATHS + AGENT_QUERY_EXAMPLES
    urls = "\n".join(
        f"  <url><loc>{html.escape(f'https://{site.ai_host}{path}')}</loc></url>"
        for path in eligible_paths
        if path not in {"/mcp", "/mcp/customer", "/service-scheduler"}
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n'


def discovery_html(site: Site) -> str:
    nap = GBP_NAP[site.key]
    nap_line = f'{nap["name"]} · {nap["streetAddress"]}, {nap["addressLocality"]}, {nap["addressRegion"]} {nap["postalCode"]} · <a href="tel:{nap["telephone"]}">{nap["telephone"]}</a>'
    business_json = json.dumps(local_business_schema(site), indent=2)
    links = "\n".join(
        f'        <li><a href="{html.escape(path)}">{html.escape(path)}</a></li>'
        for path in DISCOVERY_PATHS + AGENT_QUERY_EXAMPLES
        if path != "/"
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,follow">
    <link rel="canonical" href="{html.escape(site.base_url)}">
    <title>{html.escape(site.name)} AI-readable resources</title>
  </head>
  <body>
    <main>
      <h1>{html.escape(site.name)} AI-readable resources</h1>
      <p>Source-backed dealership, inventory, offer, service, and contact information for automated readers.</p>
      <p><a href="{html.escape(site.base_url)}">Visit the customer website</a></p>
      <ul>
{links}
        <li><a href="/sitemap.xml">/sitemap.xml</a></li>
      </ul>
    </main>
    <footer>
      <address>{nap_line}</address>
      <script type="application/ld+json">
      {business_json}
      </script>
    </footer>
  </body>
</html>
"""


def gbp_review_operations_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,follow">
    <link rel="canonical" href="https://ai.motorinnautogroup.com/gbp-review-operations">
    <title>Motor Inn Auto Group GBP Review Operations</title>
  </head>
  <body>
    <main>
      <h1>Motor Inn Auto Group GBP Review Operations</h1>
      <p>This is the official home page for the Motor Inn Auto Group GBP Review Operations application.</p>
      <p>The application lets authorized dealership staff read Google Business Profile feedback, prepare a reply for review, and maintain the dealership's local-business presence.</p>
      <p>Every customer-facing reply remains approval-gated. The application does not publish marketing content, send customer campaigns, or expose private customer data on this site.</p>
      <p>Access is limited to Motor Inn Auto Group staff who have been assigned Google Business Profile permissions by the business owner.</p>
      <p>Questions about this application: <a href="mailto:spencer.heywood@motorinnmail.com">spencer.heywood@motorinnmail.com</a>.</p>
      <p><a href="https://www.motorinnautogroup.com/privacy-policy">Privacy Policy</a> · <a href="https://www.motorinnautogroup.com/terms">Terms of Service</a></p>
    </main>
  </body>
</html>
"""


def ai_txt(site: Site) -> str:
    nap = GBP_NAP[site.key]
    lines = [
        f"# {site.name} - AI-readable site index",
        "",
        "> This site exists to provide source-backed read-only data for AI agents. It is not a Google ranking shortcut.",
        "",
        "## Capabilities",
        "- Vehicles: search and get VIN details through the read-only API.",
        "- Locations: one Carroll storefront with brand-specific contact resources.",
        "- Service information: current public service journey. It never creates an appointment.",
        "- Parts information: current parts request journey. It never creates an order.",
        "- Static contact and hours source: `/contact-hours.md`.",
    ]
    lines.extend(["", "## Guides", _article_catalog_sections(site)])
    return "\n".join(lines) + "\n"


def skills_txt(site: Site) -> str:
    rows = [
        ("search inventory", "/api/v1/vehicles", "GET"),
        ("get one vehicle by VIN", "/api/v1/vehicles/{vin}", "GET"),
        ("get dealership location", "/api/v1/locations", "GET"),
        ("get service information", "/api/v1/service-information", "GET"),
        ("get parts information", "/api/v1/parts-information", "GET"),
        ("submit a lead", "/api/v1/lead", "POST"),
    ]
    lines = [
        f"# {site.name} - Skills",
        "",
        "> Actions are read-only. They do not make appointments or orders.",
        "",
        "| Skill | Path | Method |",
        "|---|---|---|",
    ]
    lines.extend(f"| {skill} | `{path}` | {method} |" for skill, path, method in rows)
    return "\n".join(lines) + "\n"


def api_catalog(site: Site) -> dict[str, Any]:
    nap = GBP_NAP[site.key]
    return {
        "schema": "motorinn.apiCatalog.v1",
        "site": {
            "key": site.key,
            "name": nap["name"],
            "host": site.ai_host,
            "canonicalUrl": site.base_url,
        },
        "agent": {
            "openapiUrl": f"https://{site.ai_host}/openapi.json",
            "mcpUrl": f"https://{site.ai_host}/mcp",
            "agentsUrl": f"https://{site.ai_host}/.well-known/agents.json",
            "mcpcardUrl": f"https://{site.ai_host}/.well-known/mcp.json",
            "aiCatalog": f"https://{site.ai_host}/ai.txt",
            "skillsIndex": f"https://{site.ai_host}/skills.txt",
            "humanSite": site.base_url,
            "contactPage": urljoin(site.base_url.rstrip("/") + "/", "contactus.aspx"),
        },
        "actions": {
            "submit_lead": {
                "path": "/lead",
                "method": "POST",
                "docsOpenapiOperationId": "submitLead",
            },
            "search_vehicles": {
                "path": "/api/v1/vehicles",
                "method": "GET",
                "docsOpenapiOperationId": "searchVehicles",
            },
            "get_vehicle": {
                "path": "/api/v1/vehicles/{vin}",
                "method": "GET",
                "docsOpenapiOperationId": "getVehicle",
            },
            "list_locations": {
                "path": "/api/v1/locations",
                "method": "GET",
                "docsOpenapiOperationId": "listLocations",
            },
            "get_service_information": {
                "path": "/api/v1/service-information",
                "method": "GET",
                "docsOpenapiOperationId": "getServiceInformation",
            },
            "get_parts_information": {
                "path": "/api/v1/parts-information",
                "method": "GET",
                "docsOpenapiOperationId": "getPartsInformation",
            },
        },
        "business": {
            "@type": "LocalBusiness",
            "name": nap["name"],
            "telephone": nap["telephone"],
            "address": {
                "@type": "PostalAddress",
                "streetAddress": nap["streetAddress"],
                "addressLocality": nap["addressLocality"],
                "addressRegion": nap["addressRegion"],
                "postalCode": nap["postalCode"],
                "addressCountry": nap["addressCountry"],
            },
        },
    }


def api_catalog_linkset(site: Site) -> dict[str, Any]:
    base = f"https://{site.ai_host}"
    return {
        "linkset": [
            {
                "anchor": f"{base}/api",
                "service-desc": {"href": f"{base}/openapi.json"},
                "service-doc": {"href": f"{base}/api"},
                "status": {"href": f"{base}/__health"},
            }
        ]
    }


def robots_txt(site: Site) -> str:
    training_policy = "Allow: /" if ALLOW_TRAINING_CRAWLERS else "Disallow: /"
    return f"""User-agent: *
Allow: /
Disallow: /__health
Disallow: /__cache

User-agent: OAI-SearchBot
Allow: /

User-agent: Claude-SearchBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: GPTBot
{training_policy}

User-agent: ClaudeBot
{training_policy}

User-agent: Google-Extended
{training_policy}

Sitemap: https://{site.ai_host}/sitemap.xml

# Per RFC 9493: allow search, allow use with training, disallow modification.
# This is a preference signal, not an enforcement mechanism.
Content-Signal: ai-train=no, search=yes, ai-input=no
"""


@app.before_request
def start_request() -> None:
    g.started_at = time.perf_counter()


@app.after_request
def finish_request(response: Response) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    elapsed_ms = round((time.perf_counter() - getattr(g, "started_at", time.perf_counter())) * 1000, 1)
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "timestamp": iso_timestamp(utc_now()),
                "host": request.host.split(":", 1)[0],
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "contentType": response.headers.get("Content-Type", ""),
                "latencyMs": elapsed_ms,
                "bot": classify_bot(request.headers.get("User-Agent", "")),
            },
            sort_keys=True,
        )
    )
    return response


def api_response(payload: dict[str, Any], status: int = 200, *, cache_seconds: int = 0) -> Response:
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = f"public, max-age={cache_seconds}" if cache_seconds else "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def api_error(code: str, message: str, status: int, *, retryable: bool = False) -> Response:
    response = api_response(
        {
            "schema": "motorinn.error.v1",
            "error": {"code": code, "message": message, "retryable": retryable},
        },
        status,
    )
    if status == 429:
        response.headers["Retry-After"] = "60"
    return response


@app.errorhandler(413)
def request_too_large(_error: Exception) -> Response:
    return api_error("invalid_request", "Request body exceeds 256 KiB", 413)


def request_rate_limited() -> Response | None:
    if query_rate_limit_allowed(request_client_key()):
        return None
    return api_error("rate_limited", "Request rate limit exceeded", 429, retryable=True)


def api_inventory_search(site: Site, params: dict[str, Any]) -> dict[str, Any]:
    validated = agent_access.validate_vehicle_search(site, params)
    documentary_fee = validated_documentary_fee(DOC_FEE)
    rows, catalog_modified, inventory_modified = match_rows()
    return agent_access.vehicle_search(site, rows, catalog_modified, inventory_modified, validated, documentary_fee)


def api_inventory_detail(site: Site, vin: str) -> dict[str, Any] | None:
    normalized_vin = agent_access.validate_vehicle_vin(vin)
    documentary_fee = validated_documentary_fee(DOC_FEE)
    rows, catalog_modified, inventory_modified = match_rows()
    return agent_access.vehicle_detail(site, rows, catalog_modified, inventory_modified, normalized_vin, documentary_fee)


def openapi_document(site: Site) -> dict[str, Any]:
    document = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    document["servers"] = [{"url": f"https://{site.ai_host}", "description": f"{site.name} read-only mirror"}]
    return document


@lru_cache(maxsize=None)
def mcp_component_schema(name: str) -> dict[str, Any]:
    document = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    schemas = document["components"]["schemas"]

    def expand(value: Any) -> Any:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
                return expand(schemas[reference.rsplit("/", 1)[-1]])
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    schema = expand(schemas[name])
    # MCP Tool.outputSchema requires a top-level JSON Schema type. OpenAPI
    # permits an allOf-only schema root, so make the object type explicit in
    # the MCP projection without changing the source OpenAPI contract.
    if "type" not in schema and "allOf" in schema:
        schema = {"type": "object", **schema}
    return schema


@lru_cache(maxsize=3)
def mcp_tools(profile: str = "default") -> list[dict[str, Any]]:
    read_annotations = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    inventory_annotations = {**read_annotations, "openWorldHint": True}
    tools = [
        {
            "name": "search_vehicles",
            "title": "Search Motor Inn vehicles",
            "description": "Search active public vehicles matched between DealerVault and the public catalog for this rooftop.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 200},
                    "condition": {"type": "string", "enum": ["new", "used"]},
                    "make": {"type": "string", "minLength": 1, "maxLength": 80},
                    "model": {"type": "string", "minLength": 1, "maxLength": 120},
                    "minPrice": {"type": "number", "minimum": 0},
                    "maxPrice": {"type": "number", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
                    "cursor": {"type": "string", "minLength": 1, "maxLength": 512},
                },
                "additionalProperties": False,
            },
            "outputSchema": mcp_component_schema("VehicleSearchResponse"),
            "annotations": inventory_annotations,
        },
        {
            "name": "get_vehicle",
            "title": "Get one Motor Inn vehicle",
            "description": "Get one active public vehicle by exact VIN for this rooftop.",
            "inputSchema": {
                "type": "object",
                "required": ["vin"],
                "properties": {"vin": {"type": "string", "pattern": "^[A-HJ-NPR-Za-hj-npr-z0-9]{17}$"}},
                "additionalProperties": False,
            },
            "outputSchema": mcp_component_schema("VehicleResponse"),
            "annotations": inventory_annotations,
        },
        {
            "name": "list_locations",
            "title": "List Motor Inn location information",
            "description": "Get the shared Carroll physical location and validated contact resources for this brand site.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "outputSchema": mcp_component_schema("LocationResponse"),
            "annotations": read_annotations,
        },
        {
            "name": "get_service_information",
            "title": "Get Motor Inn service information",
            "description": "Get the current public service journey and its capability state. This tool never confirms an appointment.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "outputSchema": mcp_component_schema("ServiceInformationResponse"),
            "annotations": read_annotations,
        },
        {
            "name": "get_parts_information",
            "title": "Get Motor Inn parts information",
            "description": "Get the current parts-request journey. This tool does not check fitment or stock and does not create an order.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "outputSchema": mcp_component_schema("CapabilityInformationResponse"),
            "annotations": read_annotations,
        },
    ]
    submit_lead_tool = {
        "name": "submit_lead",
        "title": "Submit a customer lead",
        "description": "Create a lead for this dealership. This is the only write action available here.",
        "inputSchema": {
            "type": "object",
            "required": ["name", "email", "phone", "source"],
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "email": {"type": "string", "minLength": 5, "maxLength": 160},
                "phone": {"type": "string", "minLength": 7, "maxLength": 32},
                "vehicle": {"type": "string", "maxLength": 200},
                "message": {"type": "string", "maxLength": 2000},
                "source": {"type": "string", "minLength": 1, "maxLength": 120},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "required": ["ok", "ref"],
            "properties": {
                "ok": {"type": "boolean", "const": True},
                "ref": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    }
    if profile not in {"default", "context-only", "customer"}:
        raise ValueError("unknown MCP profile")

    context_tool = {
        "name": "search_public_website",
        "title": "Search public Motor Inn website information",
        "description": "Search only validated static website pages for this brand. Inventory and offers are excluded.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": QUERY_MAX_CHARS},
                "limit": {"type": "integer", "minimum": 1, "maximum": QUERY_MAX_RESULTS, "default": QUERY_DEFAULT_RESULTS},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "required": ["schema", "site", "resultCount", "noResults", "results"],
            "properties": {
                "schema": {"type": "string", "const": "motorinn.llmsQuery.v1"},
                "site": {
                    "type": "object",
                    "required": ["key", "name", "host"],
                    "properties": {
                        "key": {"type": "string"},
                        "name": {"type": "string"},
                        "host": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "resultCount": {"type": "integer", "minimum": 0},
                "noResults": {"type": "boolean"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "title", "snippet", "canonicalUrl", "sourceUrl", "sourceType", "freshness"],
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "snippet": {"type": "string"},
                            "canonicalUrl": {"type": "string", "format": "uri"},
                            "sourceUrl": {"type": "string", "format": "uri"},
                            "sourceType": {"type": "string", "const": "static"},
                            "freshness": {"type": ["string", "null"]},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
        "annotations": read_annotations,
    }
    context_names = {"list_locations", "get_service_information", "get_parts_information"}
    context_tools = [tool for tool in tools if tool["name"] in context_names] + [context_tool]
    if profile == "context-only":
        return context_tools
    return tools + [context_tool, submit_lead_tool]


def mcp_success(request_id: Any, result: dict[str, Any]) -> Response:
    return api_response({"jsonrpc": "2.0", "id": request_id, "result": result})


def mcp_error(request_id: Any, code: int, message: str, status: int = 200, data: dict[str, Any] | None = None) -> Response:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return api_response({"jsonrpc": "2.0", "id": request_id, "error": error}, status)


def mcp_tool_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True, separators=(",", ":"))}],
    }
    if is_error:
        result["isError"] = True
    else:
        result["structuredContent"] = payload
    return result


def mcp_call_tool(site: Site, name: str, arguments: dict[str, Any], profile: str = "default") -> dict[str, Any]:
    definition = next((tool for tool in mcp_tools(profile) if tool["name"] == name), None)
    if definition is None:
        raise KeyError(name)
    try:
        Draft202012Validator(definition["inputSchema"]).validate(arguments)
    except ValidationError as exc:
        raise agent_access.InvalidRequest(f"Invalid {name} arguments: {exc.message}") from exc
    if name == "search_public_website":
        try:
            query = normalize_query(arguments["query"])
            limit = query_limit(arguments.get("limit"))
        except ValueError as exc:
            raise agent_access.InvalidRequest(str(exc)) from exc
        results = rank_query_documents(query, build_static_query_documents(site), limit)
        return query_payload(site, results)
    if name == "search_vehicles":
        allowed = {"query", "condition", "make", "model", "minPrice", "maxPrice", "limit", "cursor"}
        if set(arguments) - allowed:
            raise agent_access.InvalidRequest("search_vehicles received an unsupported argument")
        return api_inventory_search(site, arguments)
    if name == "get_vehicle":
        if set(arguments) != {"vin"}:
            raise agent_access.InvalidRequest("get_vehicle requires only vin")
        payload = api_inventory_detail(site, str(arguments.get("vin", "")))
        if payload is None:
            raise LookupError("Vehicle not found")
        return payload
    if name == "list_locations":
        if arguments:
            raise agent_access.InvalidRequest("list_locations does not accept arguments")
        return agent_access.locations(site, static_content(site, "contact-hours.md"))
    if name == "get_service_information":
        if arguments:
            raise agent_access.InvalidRequest("get_service_information does not accept arguments")
        return agent_access.service_information(site, os.environ)
    if name == "get_parts_information":
        if arguments:
            raise agent_access.InvalidRequest("get_parts_information does not accept arguments")
        return agent_access.parts_information(site)
    if name == "submit_lead":
        payload = {
            "name": arguments["name"],
            "email": arguments["email"],
            "phone": arguments["phone"],
            "vehicle": arguments.get("vehicle"),
            "message": arguments.get("message", ""),
            "source": arguments.get("source", site.ai_host),
        }
        return submit_lead(payload, site_key=site.key, ai_host=site.ai_host)
    raise KeyError(name)


def mcp_origin_allowed(site: Site) -> bool:
    origin = request.headers.get("Origin")
    if not origin:
        return True
    configured = {
        item.strip().rstrip("/")
        for item in os.environ.get("MOTORINN_MCP_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    }
    allowed = configured | {f"https://{site.ai_host}", site.base_url.rstrip("/")}
    return origin.rstrip("/") in allowed


@app.route("/openapi.json")
def serve_openapi() -> Response:
    site = resolve_site()
    try:
        document = openapi_document(site)
        serialized = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        etag = hashlib.sha256(serialized.encode()).hexdigest()
        if request.if_none_match.contains(etag):
            response = Response(status=304)
        else:
            response = Response(serialized, content_type="application/json")
        response.set_etag(etag)
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "agent_api_failure", "operation": "get_openapi", "site": site.key, "error": str(exc)}))
        return api_error("internal_error", "The request could not be completed", 500)


@app.route("/api/v1/vehicles")
def serve_api_vehicles() -> Response:
    limited = request_rate_limited()
    if limited:
        return limited
    site = resolve_site()
    try:
        return api_response(api_inventory_search(site, request.args.to_dict(flat=True)), cache_seconds=60)
    except agent_access.InvalidRequest as exc:
        return api_error("invalid_request", str(exc), 400)
    except SourceUnavailable:
        return api_error("source_unavailable", "Public inventory sources are temporarily unavailable", 503, retryable=True)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "agent_api_failure", "operation": "search_vehicles", "site": site.key, "error": str(exc)}))
        return api_error("internal_error", "The request could not be completed", 500)


@app.route("/api/v1/vehicles/<vin>")
def serve_api_vehicle(vin: str) -> Response:
    limited = request_rate_limited()
    if limited:
        return limited
    site = resolve_site()
    try:
        payload = api_inventory_detail(site, vin)
        if payload is None:
            return api_error("not_found", "Vehicle not found", 404)
        return api_response(payload, cache_seconds=60)
    except agent_access.InvalidRequest as exc:
        return api_error("invalid_request", str(exc), 400)
    except SourceUnavailable:
        return api_error("source_unavailable", "Public inventory sources are temporarily unavailable", 503, retryable=True)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "agent_api_failure", "operation": "get_vehicle", "site": site.key, "error": str(exc)}))
        return api_error("internal_error", "The request could not be completed", 500)


@app.route("/api/v1/locations")
def serve_api_locations() -> Response:
    site = resolve_site()
    try:
        return api_response(agent_access.locations(site, static_content(site, "contact-hours.md")), cache_seconds=3600)
    except SourceUnavailable:
        return api_error("source_unavailable", "Public location information is temporarily unavailable", 503, retryable=True)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "agent_api_failure", "operation": "list_locations", "site": site.key, "error": str(exc)}))
        return api_error("internal_error", "The request could not be completed", 500)


@app.route("/api/v1/service-information")
def serve_api_service_information() -> Response:
    site = resolve_site()
    try:
        return api_response(agent_access.service_information(site, os.environ), cache_seconds=60)
    except agent_access.ConfigurationUnavailable as exc:
        logger.error(json.dumps({"event": "xtime_configuration_invalid", "site": site.key, "error": str(exc)}))
        return api_error("source_unavailable", "The configured service scheduling handoff is unavailable", 503, retryable=True)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "agent_api_failure", "operation": "get_service_information", "site": site.key, "error": str(exc)}))
        return api_error("internal_error", "The request could not be completed", 500)


@app.route("/service-scheduler")
def serve_service_scheduler_handoff() -> Response:
    site = resolve_site()
    try:
        destination = agent_access.service_information(site, os.environ)["actionUrl"]
        response = redirect(destination, code=302)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
    except agent_access.ConfigurationUnavailable as exc:
        logger.error(json.dumps({"event": "xtime_configuration_invalid", "site": site.key, "error": str(exc)}))
        return api_error("source_unavailable", "The configured service scheduling handoff is unavailable", 503, retryable=True)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "agent_api_failure", "operation": "service_scheduler_handoff", "site": site.key, "error": str(exc)}))
        return api_error("internal_error", "The request could not be completed", 500)


@app.route("/api/v1/parts-information")
def serve_api_parts_information() -> Response:
    site = resolve_site()
    try:
        return api_response(agent_access.parts_information(site), cache_seconds=3600)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "agent_api_failure", "operation": "get_parts_information", "site": site.key, "error": str(exc)}))
        return api_error("internal_error", "The request could not be completed", 500)


def serve_mcp_profile(profile: str) -> Response:
    site = resolve_site()
    if not mcp_origin_allowed(site):
        return mcp_error(None, -32000, "Invalid Origin", status=403)
    if request.method == "GET":
        response = Response(status=405)
        response.headers["Allow"] = "POST"
        return response
    limited = request_rate_limited()
    if limited:
        return limited
    if not request.is_json:
        return mcp_error(None, -32700, "Content-Type must be application/json", status=400)
    message = request.get_json(silent=True)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return mcp_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request", status=400)
    has_request_id = "id" in message
    request_id = message.get("id")
    if has_request_id and (
        isinstance(request_id, bool)
        or not (request_id is None or isinstance(request_id, (str, int, float)))
    ):
        return mcp_error(None, -32600, "Invalid Request", status=400)
    method = message["method"]
    raw_params = message.get("params", {})
    if not isinstance(raw_params, dict):
        return mcp_error(message.get("id"), -32602, "params must be an object")
    params = raw_params
    if not has_request_id:
        return Response(status=202)
    if method == "initialize":
        requested_version = params.get("protocolVersion")
        supported = {"2025-11-25", "2025-06-18"}
        client_info = params.get("clientInfo")
        if (
            not isinstance(requested_version, str)
            or not isinstance(params.get("capabilities"), dict)
            or not isinstance(client_info, dict)
            or not isinstance(client_info.get("name"), str)
            or not isinstance(client_info.get("version"), str)
        ):
            return mcp_error(request_id, -32602, "initialize requires protocolVersion, capabilities, and clientInfo")
        negotiated_version = requested_version if requested_version in supported else "2025-11-25"
        return mcp_success(request_id, {
            "protocolVersion": negotiated_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "motorinn-agent-access", "version": "1.0.0"},
            "serverInstructions": MCP_SERVER_INSTRUCTIONS,
        })
    protocol_version = request.headers.get("MCP-Protocol-Version", "2025-03-26")
    if protocol_version not in {"2025-11-25", "2025-06-18", "2025-03-26"}:
        return mcp_error(request_id, -32602, "Unsupported MCP-Protocol-Version", status=400)
    if method == "ping":
        return mcp_success(request_id, {})
    if method == "tools/list":
        return mcp_success(request_id, {"tools": mcp_tools(profile)})
    if method != "tools/call":
        return mcp_error(request_id, -32601, "Method not found")
    name = params.get("name")
    raw_arguments = params.get("arguments", {})
    if not isinstance(raw_arguments, dict):
        error = {"schema": "motorinn.error.v1", "error": {"code": "invalid_request", "message": "tool arguments must be an object", "retryable": False}}
        return mcp_success(request_id, mcp_tool_result(error, is_error=True))
    arguments = raw_arguments
    try:
        return mcp_success(request_id, mcp_tool_result(mcp_call_tool(site, str(name), arguments, profile)))
    except KeyError:
        return mcp_error(request_id, -32602, "Unknown tool")
    except agent_access.InvalidRequest as exc:
        error = {"schema": "motorinn.error.v1", "error": {"code": "invalid_request", "message": str(exc), "retryable": False}}
        return mcp_success(request_id, mcp_tool_result(error, is_error=True))
    except agent_access.ConfigurationUnavailable:
        error = {"schema": "motorinn.error.v1", "error": {"code": "source_unavailable", "message": "The configured service scheduling handoff is unavailable", "retryable": True}}
        return mcp_success(request_id, mcp_tool_result(error, is_error=True))
    except LookupError as exc:
        error = {"schema": "motorinn.error.v1", "error": {"code": "not_found", "message": str(exc), "retryable": False}}
        return mcp_success(request_id, mcp_tool_result(error, is_error=True))
    except SourceUnavailable:
        error = {"schema": "motorinn.error.v1", "error": {"code": "source_unavailable", "message": "Public sources are temporarily unavailable", "retryable": True}}
        return mcp_success(request_id, mcp_tool_result(error, is_error=True))
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "mcp_tool_failure", "tool": name, "site": site.key, "error": str(exc)}))
        error = {"schema": "motorinn.error.v1", "error": {"code": "internal_error", "message": "The tool call could not be completed", "retryable": False}}
        return mcp_success(request_id, mcp_tool_result(error, is_error=True))


@app.route("/mcp", methods=["GET", "POST"])
def serve_mcp() -> Response:
    return serve_mcp_profile("default")


@app.route("/mcp/context", methods=["GET", "POST"])
def serve_context_mcp() -> Response:
    return serve_mcp_profile("context-only")


@app.route("/mcp/customer", methods=["GET", "POST"])
def serve_customer_mcp() -> Response:
    return serve_mcp_profile("customer")


@app.route("/__health")
def health() -> Response:
    missing = [
        f"{site.content_slug}/{filename}"
        for site in SITES.values()
        for filename in STATIC_FILES
        if not (CONTENT_ROOT / site.content_slug / filename).is_file()
    ]
    status = "ok" if not missing else "failed"
    return jsonify({"status": status, "version": "2.0", "sites": sorted(HOST_TO_SITE), "missingContent": missing}), 200 if not missing else 503


@app.route("/__health/full")
def full_health() -> Response:
    try:
        site = resolve_site()
        rows, catalog_modified, inventory_modified = match_rows()
        query_health = agent_query_health()
        openapi_document(site)
        service = agent_access.service_information(site, os.environ)
        tools = mcp_tools()
        return jsonify(
            {
                "status": "ok",
                "matchedInventory": len(rows),
                "catalogUpdatedAt": iso_timestamp(catalog_modified),
                "dealerVaultUpdatedAt": iso_timestamp(inventory_modified),
                "agentQuery": query_health,
                "agentAccess": {
                    "status": "ok",
                    "serviceCapabilityState": service["capabilityState"],
                    "mcpReadToolCount": len(tools),
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "failed", "error": str(exc)}), 503


@app.route("/__cache")
def cache_stats() -> Response:
    return jsonify({"pageEntries": len(_page_cache), "catalogCached": bool(_catalog_cache), "inventoryCached": bool(_inventory_cache)})


@app.route("/ai.txt")
def serve_ai_txt() -> Response:
    return text_response(ai_txt(resolve_site()), max_age=3600)


@app.route("/skills.txt")
def serve_skills_txt() -> Response:
    return text_response(skills_txt(resolve_site()), max_age=3600)


@app.route("/.well-known/agents.json")
def serve_agents_json() -> Response:
    return api_response(agents_json(resolve_site()), cache_seconds=3600)


@app.route("/.well-known/mcp.json")
def serve_mcp_server_card() -> Response:
    return api_response(mcp_server_card(resolve_site()), cache_seconds=3600)


@app.route("/.well-known/api-catalog")
def serve_api_catalog_linkset() -> Response:
    response = api_response(api_catalog_linkset(resolve_site()), cache_seconds=3600)
    response.headers["Content-Type"] = "application/linkset+json"
    return response


@app.route("/api")
def serve_api_catalog() -> Response:
    site = resolve_site()
    response = api_response(api_catalog(site), cache_seconds=3600)
    response.headers["Link"] = f'<{urljoin("https://" + site.ai_host, "/api")}>; rel="service"'
    return response


@app.route("/robots.txt")
def serve_robots() -> Response:
    return text_response(robots_txt(resolve_site()))


@app.route("/sitemap.xml")
def serve_sitemap() -> Response:
    return xml_response(sitemap_xml(resolve_site()))


@app.route("/feed.json")
def serve_feed_json() -> Response:
    site = resolve_site()
    try:
        return api_response(feed_items(site), cache_seconds=3600)
    except SourceUnavailable as exc:
        logger.error(json.dumps({"event": "feed_source_failure", "site": site.key, "error": str(exc)}))
        return api_error("source_unavailable", "Validated site content is temporarily unavailable", 503, retryable=True)


@app.route("/llms.txt")
@app.route("/llms-full.txt")
def serve_llms() -> Response:
    return markdown_response(llms_content(resolve_site(), request.path.lstrip("/")))


@app.route("/agent-connection.md")
def serve_agent_connection_guide() -> Response:
    try:
        guide = (Path(__file__).parent / "docs" / "customer-agent-connection.md").read_text(encoding="utf-8")
        return markdown_response(guide, max_age=3600)
    except OSError as exc:
        logger.error(json.dumps({"event": "agent_connection_guide_unavailable", "error": str(exc)}))
        return api_error("source_unavailable", "The agent connection guide is temporarily unavailable", 503, retryable=True)


@app.route("/llms")
@app.route("/llms/")
def serve_llms_query() -> Response:
    return serve_agent_query(as_json=False)


@app.route("/llms/json")
def serve_llms_query_json() -> Response:
    return serve_agent_query(as_json=True)


@app.route("/new-inventory.md")
@app.route("/used-inventory.md")
def serve_inventory() -> Response:
    site = resolve_site()
    condition = "new" if request.path.startswith("/new-") else "used"
    try:
        canonical = urljoin(site.base_url + "/", "searchnew.aspx" if condition == "new" else "searchused.aspx")
        return markdown_response(render_inventory(site, condition), canonical=canonical, max_age=300)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "inventory_source_failure", "site": site.key, "error": str(exc)}))
        return markdown_response(f"# Inventory temporarily unavailable\n\n{exc}\n", status=503, max_age=0)


@app.route("/inventory.md")
def serve_inventory_table() -> Response:
    site = resolve_site()
    try:
        body = rendered_inventory_table(site)
        canonical = urljoin(site.base_url + "/", "inventory.md")
        return markdown_response(body, canonical=canonical, max_age=INVENTORY_CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "inventory_table_source_failure", "site": site.key, "error": str(exc)}))
        return markdown_response(f"# Inventory temporarily unavailable\n\n{exc}\n", status=503, max_age=0)


@app.route("/offers.md")
def serve_offers() -> Response:
    site = resolve_site()
    try:
        body = rendered_offers(site)
        canonical = urljoin(site.base_url + "/", site.offers_path.lstrip("/"))
        return markdown_response(body, canonical=canonical, max_age=900)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "offer_source_failure", "site": site.key, "error": str(exc)}))
        return markdown_response(f"# Offers temporarily unavailable\n\n{exc}\n", status=503, max_age=0)


@app.route("/gbp-review-operations")
def gbp_review_operations() -> Response:
    site = resolve_site()
    if site.key != "motorinnautogroup":
        return Response("Not found\n", status=404, content_type="text/plain; charset=utf-8")
    response = Response(gbp_review_operations_html(), content_type="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["X-Robots-Tag"] = "noindex, follow"
    return response


@app.route("/links/<path:site_slug>.html")
def serve_links_index(site_slug: str) -> Response:
    site = next((candidate for candidate in SITES.values() if candidate.content_slug == site_slug), None)
    if site is None:
        return Response("Not found\n", status=404, content_type="text/plain; charset=utf-8")
    response = Response(related_links_page(site), content_type="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["X-Robots-Tag"] = "noindex, follow"
    return response


@app.route("/articles/<path:slug>")
def serve_article(slug: str) -> Response:
    body = article_html(resolve_site(), slug)
    if not body:
        return Response("Not found\n", status=404, content_type="text/plain; charset=utf-8")
    response = Response(body, content_type="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["X-Robots-Tag"] = "index, follow"
    return response


@app.route("/terms")
def serve_connected_app_terms() -> Response:
    site = resolve_site()
    return connected_app_page(site, "Terms of service", "")


@app.route("/privacy")
def serve_connected_app_privacy() -> Response:
    site = resolve_site()
    return connected_app_page(site, "Privacy policy", "")


@app.route("/assets/icon-512.png")
def serve_connected_app_icon() -> Response:
    site = resolve_site()
    try:
        payload = (ASSETS_ROOT / site.key / "icon-512.png").read_bytes()
    except OSError as exc:
        logger.error(json.dumps({"event": "connected_app_icon_missing", "site": site.key, "error": str(exc)}))
        return api_error("not_found", "Icon unavailable", 404)
    response = Response(payload, content_type="image/png")
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.route("/.well-known/google-connected-apps")
def serve_google_connected_apps_certificate() -> Response:
    return api_response(google_connected_apps_certificate(resolve_site()), cache_seconds=3600)


@app.route("/google-verification/<token>")
def serve_google_verification_token(token: str) -> Response:
    site = resolve_site()
    if token not in google_verification_tokens(site):
        return Response("Not found\n", status=404, content_type="text/plain; charset=utf-8")
    response = Response(token, content_type="text/plain; charset=utf-8")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response

@app.route("/<path:filename>")
def serve_static_or_proxy(filename: str) -> Response:
    site = resolve_site()
    if filename in STATIC_FILES:
        body = static_content(site, filename)
        return markdown_response(body, canonical=canonical_url(site, filename))
    wants_markdown = "text/markdown" in request.headers.get("Accept", "") or filename.endswith(".md")
    source_path = filename[:-3] if filename.endswith(".md") else filename
    source_url = canonical_url(site, source_path)
    if not wants_markdown:
        html_records = related_link_records(site, source_path)
        if html_records:
            page_html = fetch_page(source_url)
            response = Response(inject_related_links(page_html, site, source_path), content_type="text/html; charset=utf-8")
            response.headers["Cache-Control"] = "public, max-age=3600"
            return response
        return redirect(source_url, code=302)
    key = hashlib.sha256(f"{site.key}|{source_url}".encode()).hexdigest()
    try:
        body = cache_get(_page_cache, key, CACHE_TTL_SECONDS)
        if body is None:
            body = clean_html_to_markdown(fetch_page(source_url), site.base_url)
            cache_set(_page_cache, key, body)
        return markdown_response(body, canonical=source_url)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "upstream_failure", "url": source_url, "error": str(exc)}))
        return markdown_response(f"# Source temporarily unavailable\n\n{exc}\n", status=502, max_age=0)


@app.route("/")
def root() -> Response:
    site = resolve_site()
    if "text/markdown" not in request.headers.get("Accept", ""):
        related = related_link_records(site, "/")
        if related:
            response = Response(inject_related_links(fetch_page(site.base_url), site, "/"), content_type="text/html; charset=utf-8")
            response.headers["Cache-Control"] = "public, max-age=3600"
            response.headers["Link"] = (
                f'<{site.base_url}>; rel="canonical", '
                f'<https://{site.ai_host}/api>; rel="api-catalog", '
                f'<https://{site.ai_host}/openapi.json>; rel="service-desc", '
                f'<https://{site.ai_host}/skills.txt>; rel="service-doc", '
                f'<https://{site.ai_host}/links/{site.key}.html>; rel="links-index"'
            )
            response.headers["X-Robots-Tag"] = "noindex, follow"
            return response
        response = Response(discovery_html(site), content_type="text/html; charset=utf-8")
        response.headers["Cache-Control"] = "public, max-age=3600"
        response.headers["Link"] = (
            f'<{site.base_url}>; rel="canonical", '
            f'<https://{site.ai_host}/api>; rel="api-catalog", '
            f'<https://{site.ai_host}/openapi.json>; rel="service-desc", '
            f'<https://{site.ai_host}/skills.txt>; rel="service-doc", '
            f'<https://{site.ai_host}/ai.txt>; rel="describedby"'
        )
        response.headers["X-Robots-Tag"] = "noindex, follow"
        return response
    key = hashlib.sha256(f"{site.key}|{site.base_url}".encode()).hexdigest()
    try:
        body = cache_get(_page_cache, key, CACHE_TTL_SECONDS)
        if body is None:
            body = clean_html_to_markdown(fetch_page(site.base_url), site.base_url)
            cache_set(_page_cache, key, body)
        return markdown_response(body, canonical=site.base_url)
    except Exception as exc:  # noqa: BLE001
        return markdown_response(f"# Source temporarily unavailable\n\n{exc}\n", status=502, max_age=0)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
