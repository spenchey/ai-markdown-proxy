# DealerOn Implementation Request

Please publish the supplied site-specific `llms.txt` and `llms-full.txt` files
at the root of each matching Motor Inn website and merge the supplied crawler
directives into its existing `robots.txt`.

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

The `ai.` hosts are already an externally managed, read-only discovery layer.
DealerOn does not need to host or implement Markdown conversion, dynamic
inventory generation, or content negotiation for this request.
