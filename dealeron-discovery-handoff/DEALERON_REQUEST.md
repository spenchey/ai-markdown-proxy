# DealerOn Implementation Request

Please publish the supplied site-specific `llms.txt` and `llms-full.txt` files
at the root of each matching Motor Inn website and merge the supplied crawler
directives into its existing `robots.txt`. This is the discovery portion of the
broader AI Agent Website Access program covering vehicle search, service
scheduling, and parts requests. Please also complete the human-page work in
`SITE_PAGE_REQUIREMENTS.md` and return evidence using
`ACCEPTANCE_CHECKLIST.md`.

## Required URLs

- `https://www.motorinnautogroup.com/llms.txt`
- `https://www.motorinnautogroup.com/llms-full.txt`
- `https://www.motorinntoyotaofcarroll.com/llms.txt`
- `https://www.motorinntoyotaofcarroll.com/llms-full.txt`
- `https://www.motorinnofcarroll.com/llms.txt`
- `https://www.motorinnofcarroll.com/llms-full.txt`

## Acceptance Criteria

1. Each URL returns HTTP `200` with no redirect.
2. Each file is served as `text/markdown; charset=utf-8`.
3. Each human website points only to its matching `ai.` host.
4. Existing DealerOn pages, canonical tags, navigation, analytics, inventory,
   and Search Console configuration remain unchanged.
5. Existing `robots.txt` rules remain intact; only the supplied AI search and
   citation crawler blocks are added.
6. Inventory search/results and VDP links remain crawlable and usable without
   requiring an AI agent to execute a chat widget.
7. Each site's accessible service page states that the one physical service
   location is Carroll and links to that site's matching stable AI handoff.
8. Each site's parts page retains an accessible request path and links to its
   matching AI-readable parts-information resource.

The `ai.` hosts are an externally managed discovery and read-contract layer.
DealerOn does not need to host or implement Markdown conversion, dynamic
inventory generation, OpenAPI, MCP, or content negotiation for this request.
DealerOn must not add appointment or parts-order confirmation claims; those
remain unavailable until the authoritative providers support them.
