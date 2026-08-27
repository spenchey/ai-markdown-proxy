# Agent Access Foundation v1

Status: approved and implemented on the isolated branch; production deployment pending
Branch: `codex/ai-agent-access-foundation`
Base: `origin/main` at `2031a87`

Machine-readable draft: `openapi/agent-access-v1.yaml`
Validation: `openapi-spec-validator 0.7.2` reports `OK`

## Purpose

Add a versioned, source-backed, read-only interface to the existing three AI mirrors without changing the meaning or authority of any service or parts journey. The implementation reuses the existing DealerVault/public-catalog match gate and site isolation.

This phase does not create appointments, parts requests, carts, orders, payments, customer records, or authentication. Transaction tools remain out of scope until their authoritative source contracts pass the separate proof gates.

## Deployment boundary

The v1 read API is exposed on each existing AI hostname:

- `ai.motorinnautogroup.com`
- `ai.motorinnofcarroll.com`
- `ai.motorinntoyotaofcarroll.com`

The request hostname selects the site. A known production hostname cannot be overridden with a query parameter. Results cannot combine rooftop identities.

The future protected transaction gateway is a separate service boundary and is not implied by these routes.

## Proposed HTTP seams

### `GET /openapi.json`

Returns an OpenAPI 3.1.2 document for the current hostname. It describes only implemented read operations and their real response schemas.

Required behavior:

- `Content-Type: application/json`;
- explicit version and server URL for the resolved AI host;
- no write operation or unimplemented transaction path;
- cacheable with an ETag or deterministic body;
- included in the discovery index, sitemap, and `llms.txt` resources.

### `GET /api/v1/vehicles`

Searches active vehicles after the existing DealerVault/public-catalog match and site make filter.

Parameters:

- `query`: optional lexical year/make/model/trim/stock/VIN query, maximum 200 characters;
- `condition`: optional `new` or `used`;
- `make`, `model`: optional case-insensitive exact filters;
- `minPrice`, `maxPrice`: optional non-negative decimal filters;
- `limit`: 1 through 25, default 10;
- `cursor`: opaque stable pagination cursor.

Public vehicle projection:

- stable result ID;
- VIN and stock number;
- year, make, model, trim, condition;
- advertised price including the configured documentary fee, or `null` when undisclosed;
- currency `USD`;
- public availability label;
- rooftop key and display name;
- canonical VDP URL and public image URL;
- DealerVault and public-catalog timestamps;
- response schema identifier.

Forbidden fields include customer/lead data, cost, appraisal, wholesale values, internal notes, raw DealerVault rows, credentials, or unvalidated source columns.

### `GET /api/v1/vehicles/{vin}`

Returns one active, site-valid vehicle through the same public projection.

Required behavior:

- VIN comparison is normalized and exact;
- unknown, inactive, stale, or wrong-rooftop vehicles return a typed error and never leak another site's row;
- no source field bypasses the projection.

### `GET /api/v1/locations`

Returns the resolved rooftop identity and its public canonical location/contact resource. The first implementation may derive its structured fields only where the validated static content has an unambiguous source. Ambiguous Toyota phone numbers must remain unresolved rather than guessed.

### `GET /api/v1/service-information`

Returns public service information and the canonical customer journey:

- group: service locations;
- Chevrolet: external GM Online Service Scheduling handoff;
- Toyota: DealerOn appointment-request form.

The response must state `capabilityState` as `information_only` for the group location chooser, `external_handoff` for a scheduler handoff, or `requested_only` for a follow-up request. It cannot advertise live slots or confirmed booking.

Motor Inn plans to move to Xtime Schedule by Cox Automotive in September 2026. Motor Inn has one service location in Carroll and three branded website entry points. The runtime therefore has one Carroll Xtime consumer URL and activation gate, while each AI host retains its own stable `/service-scheduler` URL. It reports the transition as `planned` until an operator supplies a valid `https://consumer.xtime.com/scheduling?...&webkey=...` URL, verifies the Carroll location binding, and activates it. An invalid active configuration fails closed. This is a website handoff seam, not an Xtime appointment API. See `docs/xtime-dealeron-integration.md`.

### `GET /api/v1/parts-information`

Returns public parts department information and the canonical DealerOn request form. It must state `capabilityState: requested_only` and explicitly report that fitment, stock, price, reservation, cart, payment, and order confirmation are unavailable through this API.

## Proposed MCP seam

After the HTTP schemas pass their tests, expose a remote MCP Streamable HTTP endpoint at `/mcp` with read-only tools generated from the same application services:

- `search_vehicles`
- `get_vehicle`
- `list_locations`
- `get_service_information`
- `get_parts_information`

Every tool must declare structured output and `readOnlyHint: true`. No transaction-shaped placeholder tool is allowed. MCP and HTTP results for the same fixture must be semantically equivalent.

## Error contract

All API errors use:

```json
{
  "schema": "motorinn.error.v1",
  "error": {
    "code": "source_unavailable",
    "message": "Public inventory sources are temporarily unavailable",
    "retryable": true
  }
}
```

Required codes:

- `invalid_request` — 400;
- `not_found` — 404;
- `rate_limited` — 429 with `Retry-After`;
- `source_unavailable` — 503;
- `internal_error` — 500 with no internal detail.

## Confirmed test seams

The public seam under test is the Flask HTTP interface. Tests observe only requests and responses through `app.test_client()` with patched authoritative source boundaries; they do not call private helpers or assert internal implementation details.

Proposed behavioral tests:

1. OpenAPI describes only implemented read operations for the selected host.
2. Vehicle search returns the independently specified public projection and source timestamps.
3. Chevrolet and Toyota new-vehicle results remain make-isolated.
4. Search/detail never return forbidden private fields.
5. Wrong-rooftop, inactive, missing, and stale vehicles fail closed.
6. Price filters use the disclosed public price including the documentary fee; undisclosed prices are never inferred.
7. Service information distinguishes Chevrolet external scheduling from Toyota request-only status.
8. Parts information is request-only and does not claim stock, fitment, cart, order, or payment support.
9. MCP and HTTP read results are equivalent after MCP is added.
10. Existing Markdown/query/discovery behavior remains unchanged.

## Definition of done for this slice

- the exact seams above are confirmed;
- red-green tests are implemented one behavior at a time;
- OpenAPI validates as 3.1.2 and matches the live route behavior;
- the full existing test suite remains green;
- the diff passes separate standards and spec reviews against this file;
- `graphify update .` refreshes the code graph;
- the work is committed on the isolated branch, not deployed.

## Current progress

- The HTTP/OpenAPI/MCP seams were approved by the owner on August 27, 2026.
- The OpenAPI 3.1.2 contract has been written, served per hostname, and validated structurally.
- The contract contains six `GET` operations and no mutation operation.
- The transaction security contract is documented in `docs/transaction-security-contract.md`.
- Runtime routes implement the public projection, typed errors, host isolation, staged Xtime handoff, and read-only MCP tools.
- HTTP and MCP return equivalent service results and equivalent vehicle-search results for the same fixture.
- The local suite passes 53 tests, including the single-Carroll service-location contract, three brand-specific stable handoffs, DealerOn organization handoff package, and secret-safe one-location Xtime preflight. The branch has not been deployed and no Xtime tenant or appointment was exercised.
