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

`./deploy.sh` updates the existing instance through Systems Manager, attaches least-privilege inventory access, creates a 30-day CloudWatch log group, removes public SSH, and assigns a stable Elastic IP.

Point these subdomains at the reported Elastic IP:
   - `ai.motorinnautogroup.com` ──► EC2 Public IP
   - `ai.motorinntoyotaofcarroll.com` ──► EC2 Public IP  
   - `ai.motorinnofcarroll.com` ──► EC2 Public IP

## What It Serves

### `GET /llms.txt` and `GET /llms-full.txt`
Returns the validated package for the request hostname. Site identities and content are not combined.

### `GET /robots.txt`
Allows citation/search crawlers. Model-training crawlers remain blocked unless `ALLOW_TRAINING_CRAWLERS=true` is an explicit owner decision.

### `GET /new-inventory.md` and `GET /used-inventory.md`
Matches the latest DealerVault/Athena inventory export against public DealerOn VDPs and photos. A missing or stale source returns `503`; it never publishes guessed facts.

### `GET /offers.md`
Converts the site's current DealerOn offer page and links back to the controlling source and disclosures.

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
