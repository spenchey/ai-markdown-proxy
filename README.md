# AI-Readable Mirror for Motor Inn Auto Group

Serves validated site-specific `llms.txt` and Markdown resources for Motor Inn's three DealerOn sites. Dynamic inventory is published only when a unit matches the current DealerVault/Athena export and DealerOn's public catalog.

This is an AI-agent readability layer, not a Google ranking shortcut. The canonical DealerOn HTML pages remain the Google/Search Console source of truth.

## Architecture

```
AI subdomain (HTTPS) ──► [ EC2 t3.nano ] ──► DealerOn pages
                           │
                           ├─ validated static Markdown package
                           ├─ DealerVault/Athena active-inventory gate
                           ├─ DealerOn public VDP and image enrichment
                           ├─ versioned public OpenAPI + read-only MCP
                           ├─ staged Xtime Schedule handoff configuration
                           ├─ on-demand HTML-to-Markdown conversion
                           └─ structured CloudWatch logs and health checks
```

## Quick Start (Local)

```bash
cd ai-markdown-proxy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PORT=8081 python server.py
```

Test it:
```bash
# llms.txt
curl http://localhost:8081/llms.txt

# Fetch a page as markdown
curl -H "Accept: text/markdown" "http://localhost:8081/?site=motorinnautogroup"
```

## Deploy to AWS

`./deploy.sh` updates the existing instance through Systems Manager, attaches least-privilege inventory access, creates 30-day CloudWatch log groups, removes public SSH, assigns a stable Elastic IP, and runs Caddy for automatic HTTPS renewal. The Flask/Gunicorn application is bound only to `127.0.0.1:8080`; Caddy is the public ingress.

Point these subdomains at the reported Elastic IP:
   - `ai.motorinnautogroup.com` ──► EC2 Public IP
   - `ai.motorinntoyotaofcarroll.com` ──► EC2 Public IP  
   - `ai.motorinnofcarroll.com` ──► EC2 Public IP

After DNS resolves, Caddy obtains and renews certificates automatically. Deploy the external health monitor with:

```bash
./deploy-monitoring.sh
```

The monitor checks each host's full source health, `llms.txt`, inventory, and crawler policy every 15 minutes. It records status, latency, HTTP code, and source freshness in CloudWatch. After two consecutive hard failures it alerts `#seo-monitoring`; it also posts one recovery notice.

Each `ai.` hostname has its own HTML discovery index, sitemap, crawler policy,
`llms.txt`, Markdown resources, and health monitoring. Submit each AI sitemap
directly in Google Search Console after DNS resolves. The optional
`dealeron-discovery-handoff/` package can improve discovery from the human site,
but DealerOn participation is not required for the mirror to operate or be
submitted to search engines.

## What It Serves

### `GET /llms.txt` and `GET /llms-full.txt`
Returns the validated package for the request hostname. Site identities and content are not combined.

### `GET /llms?query=...` and `GET /llms/json?query=...`
Returns deterministic lexical matches from the matching site's rendered public/static resources. The Markdown and JSON forms use the same ranked result set. `limit` defaults to 5 and accepts 1 through 8; queries are required and limited to 200 characters.

Inventory matches are searched only after the existing DealerVault/public-catalog gate has rendered the public inventory document. Raw DealerVault fields never enter the search corpus. Requests are limited in memory to 60 per minute per client IP within the single-process application container. A deployment that scales beyond one container must add an equivalent shared ingress limiter; the application does not claim a fleet-global limit. Structured `llms_query` telemetry keeps normal topic terms, redacts common customer identifiers, hashes the sanitized normalized query, and does not record client IPs. Query responses use `Cache-Control: no-store`.

### `GET /robots.txt`
Allows citation/search crawlers. Model-training crawlers remain blocked unless `ALLOW_TRAINING_CRAWLERS=true` is an explicit owner decision.

### `GET /` and `GET /sitemap.xml`
The root is a crawlable, `noindex,follow` discovery index with a canonical link
to the matching DealerOn customer site. The sitemap contains only the matching
AI hostname's machine-readable resources, so the three dealership identities
remain isolated.

### `GET /new-inventory.md` and `GET /used-inventory.md`
Matches the latest DealerVault/Athena inventory export against public DealerOn VDPs and photos. A missing or stale source returns `503`; it never publishes guessed facts.

### `GET /offers.md`
Converts the site's current DealerOn offer page and links back to the controlling source and disclosures.

### `GET /openapi.json` and `GET /api/v1/*`
Serves a hostname-scoped OpenAPI 3.1.2 contract plus read-only vehicle search/detail, location, service-information, and parts-information routes. Inventory uses the same DealerVault/public-catalog match gate as the Markdown output and returns a fixed public projection with source timestamps. Invalid, stale, or cross-rooftop requests fail with typed JSON errors.

### `GET|POST /mcp`
Implements a stateless MCP Streamable HTTP endpoint with five read-only tools: `search_vehicles`, `get_vehicle`, `list_locations`, `get_service_information`, and `get_parts_information`. `GET` returns 405 because the server does not offer an unsolicited SSE stream. POST requests validate any supplied `Origin`, and tool results include both structured content and a JSON text block.

### Staged Xtime Schedule handoff

Motor Inn plans to move service scheduling to Xtime Schedule by Cox Automotive. Motor Inn has one service location in Carroll, presented through three branded website entry points. The public mirror can advertise and activate one validated Carroll Xtime consumer URL without adding appointment writes:

Each AI host now exposes a permanent `GET /service-scheduler` handoff. Before
cutover it redirects to that brand's current scheduling journey; after a
verified activation it redirects to the approved Xtime journey. This keeps the
public address stable while the authoritative scheduling provider changes.

```text
MOTORINN_XTIME_CARROLL_URL
MOTORINN_XTIME_CARROLL_ACTIVE
MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION
```

Activation defaults to false. An active URL must use `https://consumer.xtime.com/scheduling` and include a non-empty `webkey`; an invalid active configuration fails closed with `503`. Real tenant values must be supplied by Cox/Xtime and must not be committed. DealerOn owns the human-site installation. See `docs/xtime-dealeron-integration.md` for the cutover and rollback contract.

Operators can validate the gates without printing provider URLs or webkeys:

```bash
.venv/bin/python tools/xtime_preflight.py --require configured
.venv/bin/python tools/xtime_preflight.py --require verified
.venv/bin/python tools/xtime_preflight.py --require active
```

The command exits `0` only when the Carroll location satisfies the requested stage;
otherwise it exits `2` with safe JSON status. It never tests or claims that an
appointment can be written.

### Cross-agent read conformance

Run the non-mutating live canary to compare public AI pages, OpenAPI reads, and
MCP structured results across all three brand hosts:

```bash
.venv/bin/python tools/read_conformance.py
```

The report distinguishes a true interface mismatch (`fail`) from a consistent
fail-closed upstream outage (`degraded`). It can also compare deliberately
minimal, secret-free evidence captured from supported ChatGPT, Claude, Gemini,
Perplexity, and browser clients. See `docs/read-conformance-harness.md`.

### `GET /<path>` with `Accept: text/markdown`
Fetches the equivalent canonical DealerOn page and returns `text/markdown`. Normal browser requests redirect to the canonical human page.

**Sites:**
- `motorinnautogroup` → motorinnautogroup.com
- `motorinntoyota` → motorinntoyotaofcarroll.com  
- `motorinnchevy` → motorinnofcarroll.com

### `GET /__health`
Returns static health. `/__health/full` also proves DealerVault/public catalog freshness and matching.

## Cost

- **EC2 t3.nano**: ~$3.50/month (always-on)
- **Data transfer**: Minimal (text-only, cached)
- **Elastic IP**: no additional charge while attached
- **Logs and DNS**: minimal at this traffic level
