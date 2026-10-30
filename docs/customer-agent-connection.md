# Connect an AI agent to Motor Inn

Motor Inn offers a public, read-only integration for MCP-compatible AI clients. Use the dealership's HTTPS URL as a **remote MCP server** and select Streamable HTTP when the client asks for a transport. There is no Motor Inn or Muse account to connect, and no API key is required for these public endpoints.

## Choose a dealership

| Website context | MCP server URL | Public HTTP contract |
| --- | --- | --- |
| Motor Inn of Carroll (Chevrolet) | `https://ai.motorinnofcarroll.com/mcp/customer` | `https://ai.motorinnofcarroll.com/openapi.json` |
| Motor Inn Toyota of Carroll | `https://ai.motorinntoyotaofcarroll.com/mcp/customer` | `https://ai.motorinntoyotaofcarroll.com/openapi.json` |
| Motor Inn Auto Group | `https://ai.motorinnautogroup.com/mcp/customer` | `https://ai.motorinnautogroup.com/openapi.json` |

In the AI client, add a remote MCP server, give it a name such as “Motor Inn,” paste the URL for the desired website context, and let the client discover the tools. A client can also use the corresponding public OpenAPI contract for direct HTTP integrations. MCP clients discover tools with the standard `tools/list` request; this page does not define a Muse-specific protocol or manifest.

## Available read-only tools

- `search_vehicles` and `get_vehicle` return the existing public inventory projection, using the chosen website's brand and rooftop rules.
- `list_locations`, `get_service_information`, and `get_parts_information` provide public dealership context.
- `search_public_website` searches validated static website pages for dealership, contact, service, finance/trade, and policy information. It does not search dynamic inventory or offers.
- `submit_lead` creates a lead. It requires name, email, phone, and source. It does not send customer emails.

The inventory response preserves the existing public projection. `advertisedPrice.sourceField` identifies whether the selected amount came from `internet_price`, `list_price`, or `msrp`; the projection includes the configured documentation fee. Do not interpret every returned price as an unconditional cash offer. Confirm current terms and eligibility with the dealership. Availability text is taken from the public catalog. Freshness timestamps describe the S3 object delivery time and the public catalog's HTTP `Last-Modified` or retrieval time, not a verified supplier source-update time. The API returns source-basis fields alongside those timestamps.

Search fails closed when its existing source-age checks fail. An empty result means no matching public listing was returned; a source-unavailable error means the sources could not be validated. Vehicle images link to the existing public listing and are not copied into a new data store.

These tools do not create leads, retrieve customer records, accept deposits, reserve or purchase vehicles, submit finance applications, or book service appointments. Service information includes links to the dealership's current customer journey only.

## Protocol notes

The endpoint uses MCP over Streamable HTTP with JSON-RPC POST requests and JSON responses. It negotiates MCP protocol versions `2025-11-25` and `2025-06-18`. If a client requests another version, the server selects `2025-11-25`; continue only if the client supports that version. GET returns `405 Method Not Allowed` because the server does not provide an unsolicited server-sent-events stream. That GET behavior is allowed by the `2025-11-25` Streamable HTTP specification. An MCP-compatible client should discover tools from the endpoint rather than assuming a Muse-specific tool manifest.

Requests from browser-based clients must use an allowed `Origin`; Motor Inn validates supplied origins. A server-side MCP client usually omits `Origin`. Do not remove or spoof the header to work around a rejection.

## Current status

The `/mcp/customer` route is implemented and covered by local contract tests. The site URLs above are the configured public hostnames, but this candidate change has not been deployed. The deployed service may not yet serve `/mcp/customer` until the normal release process publishes it.
