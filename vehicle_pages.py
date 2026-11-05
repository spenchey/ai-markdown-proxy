"""Per-VIN vehicle pages and answer pages for the AI mirrors.

Vehicle pages (/v/<vin>) render one authoritative machine-readable page per
in-stock unit from the same matched-row pipeline that feeds /inventory.md and
/api/v1/vehicles. Answer pages (/answers/<slug>) carry dealership facts for
questions with no VIN in them (financing, trade, service). Both are
markdown-first with an HTML projection, indexed from sitemap.xml, llms.txt
and the per-vehicle sections of the inventory pages.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANSWER_ROOT = Path(__file__).resolve().parent / "answer_pages"

VEHICLE_PAGE_FIELDS = (
    ("Body style", "vehicle_body"),
    ("Exterior color", "exterior_color"),
    ("Interior color", "interior_color"),
    ("Engine", "engine_desc"),
    ("Fuel type", "fuel_type"),
    ("Transmission", "transmission_desc"),
)


def normalize_vin(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def find_row(rows: list[dict[str, Any]], vin: str) -> dict[str, Any] | None:
    normalized = normalize_vin(vin)
    for row in rows:
        if normalize_vin(row.get("vin")) == normalized:
            return row
    return None


def render_vehicle_markdown(row: dict[str, Any], fee_label: str, dealer_name: str) -> str:
    """One VIN, one canonical page: every fact an assistant may quote."""
    source = row.get("dealerVault") if isinstance(row.get("dealerVault"), dict) else {}
    vehicle = " ".join(
        part for part in [
            row.get("vehicle_year"), row.get("vehicle_make"),
            row.get("vehicle_model"), row.get("vehicle_trim"),
        ] if part
    ).strip() or "Vehicle"
    vin = normalize_vin(row.get("vin"))
    price = row.get("display_price")
    if price in (None, "", 0):
        dv_price = (row.get("dealerVault") or {}).get("internet_price") or (row.get("dealerVault") or {}).get("list_price")
        try:
            price = float(dv_price)
        except (TypeError, ValueError):
            price = None
    lines = [
        f"# {vehicle} - VIN {vin}",
        "",
        f"> {vehicle} in stock at {dealer_name}. Facts come from the live inventory match; the linked dealer page is canonical for availability.",
        "",
        f"- VIN: {vin}",
    ]
    if price:
        try:
            lines.append(f"- Price: ${float(price):,.0f} ({fee_label})")
        except (TypeError, ValueError):
            pass
    miles = row.get("odometer") or source.get("odometer")
    if miles not in (None, "", 0):
        try:
            lines.append(f"- Mileage: {int(miles):,} miles")
        except (TypeError, ValueError):
            pass
    condition = str(row.get("condition") or "").lower()
    if condition:
        lines.append(f"- Condition: {condition}")
    trim = str(row.get("vehicle_trim") or source.get("vehicle_trim") or "").strip()
    if trim:
        lines.append(f"- Trim: {trim}")
    for label, key in VEHICLE_PAGE_FIELDS:
        val = str(source.get(key) or "").strip()
        if val:
            lines.append(f"- {label}: {val}")
    availability = str(row.get("availability") or "in stock")
    lines.append(f"- Availability: {availability}")
    link = str(row.get("canonical_link") or "").strip()
    if link:
        lines.append(f"- [Canonical vehicle page]({link})")
    if row.get("image_link"):
        lines.append(f"- [Photo]({row['image_link']})")
    lines += ["", "Confirm current details on the linked dealer page or by phone before acting."]
    return "\n".join(lines) + "\n"


def markdown_to_html(body: str, title: str, dealer_name: str) -> str:
    """Minimal md->html for the fact-block pages (headings, lists, links, bold)."""
    import re

    def inline(text: str) -> str:
        text = html.escape(text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        return text

    out: list[str] = []
    in_list = False
    for raw in body.splitlines():
        line = raw.rstrip()
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        "<style>body{margin:0;background:#0B1F3A;color:#fff;font-family:system-ui,sans-serif}"
        "main{box-sizing:border-box;max-width:760px;margin:0 auto;padding:40px 24px}"
        "h1{font-size:30px}a{color:#8FCBFF}li{line-height:1.6}</style></head><body><main>"
        f"<div class=mark>{html.escape(dealer_name)}</div>"
        + "\n".join(out)
        + "</main></body></html>"
    )


@dataclass(frozen=True)
class AnswerPage:
    slug: str
    title: str
    audience_query: str
    body: str
    dealer_keys: tuple[str, ...]

    def markdown(self) -> str:
        return self.body

    def summary(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "audience_query": self.audience_query,
            "path": f"/answers/{self.slug}",
            "dealer_keys": list(self.dealer_keys),
        }


def load_answer_pages() -> tuple[list[AnswerPage], str]:
    """Read answer_pages/<slug>.json (facts + dealer keys) + <slug>.md (body)."""
    pages: list[AnswerPage] = []
    generated = ""
    if not ANSWER_ROOT.is_dir():
        return pages, generated
    for meta_path in sorted(ANSWER_ROOT.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = (ANSWER_ROOT / (meta_path.stem + ".md")).read_text(encoding="utf-8")
        except (OSError, json.JSONDecodeError, KeyError):
            continue
        pages.append(AnswerPage(
            slug=str(meta["slug"]),
            title=str(meta["title"]),
            audience_query=str(meta.get("audience_query", "")),
            body=body,
            dealer_keys=tuple(meta.get("dealer_keys", ())),
        ))
        generated = str(meta.get("generated", generated))
    return pages, generated
