# AI Markdown Proxy for Motor Inn Auto Group

Converts DealerOn-powered dealership websites to AI-readable markdown, serving `llms.txt` and clean markdown pages for AI search agents (ChatGPT, Perplexity, Claude, etc.).

## Architecture

```
Internet (port 80) ──► [ EC2 t3.nano ] ──► DealerOn Sites
                           │
                           ├─ /llms.txt ────────────► Served directly (tells AI what pages exist)
                           ├─ /robots.txt ──────────► Served directly (allows AI bots)
                           ├─ /?site=motorinn... ──► Fetches live HTML, converts to markdown on-the-fly
                           └─ /__health ───────────► Health check
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

1. **Configure AWS CLI** (if not already done):
   ```bash
   aws configure
   ```

2. **Push the code to a GitHub repo:**
   ```bash
   git init && git add . && git commit -m "AI Markdown Proxy"
   git remote add origin https://github.com/YOUR-USER/ai-markdown-proxy.git
   git push -u origin main
   ```

3. **Launch EC2 instance:**
   ```bash
   ./deploy.sh
   ```

4. **Point subdomains at the EC2 IP:**
   - `ai.motorinnautogroup.com` ──► EC2 Public IP
   - `ai.motorinntoyotaofcarroll.com` ──► EC2 Public IP  
   - `ai.motorinnofcarroll.com` ──► EC2 Public IP

## What It Serves

### `GET /llms.txt`
Lists all pages on all three sites with descriptions. AI agents use this to know what's available.

### `GET /robots.txt`
Allows all AI bots (GPTBot, Claude-Web, PerplexityBot, CCBot) to crawl the site.

### `GET /?site=<site_id>&path=<path>` with `Accept: text/markdown`
Fetches the requested page from the live DealerOn site, converts HTML → markdown, and returns it.

**Sites:**
- `motorinnautogroup` → motorinnautogroup.com
- `motorinntoyota` → motorinntoyotaofcarroll.com  
- `motorinnchevy` → motorinnofcarroll.com

### `GET /__health`
Returns JSON health status.

## S3-Hosted Alternative

If you prefer not to run a server at all, the same `llms.txt` files can be generated statically and uploaded to S3:

1. Generate markdown for all key pages
2. Upload to S3 bucket with `text/markdown` content-type
3. Serve via CloudFront

## Cost

- **EC2 t3.nano**: ~$3.50/month (always-on)
- **Data transfer**: Minimal (text-only, cached)
- **Total**: Under $5/month
