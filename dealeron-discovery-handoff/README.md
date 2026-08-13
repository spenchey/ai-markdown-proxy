# DealerOn AI Discovery Handoff

DealerOn remains the canonical website and Google SEO source. The AWS-hosted
`ai.` subdomains are a separate read-only discovery layer for AI agents.

DealerOn should publish the files in each site folder at the matching website
root. Requirements:

- return HTTP `200` without a redirect;
- preserve the files exactly as supplied;
- serve `llms.txt` and `llms-full.txt` as `text/markdown; charset=utf-8`;
- merge the supplied crawler blocks into the existing root `robots.txt` without
  removing current DealerOn rules;
- do not proxy, iframe, canonicalize, or redirect the human site to the `ai.`
  subdomain.

The DNS records and HTTPS certificates for the `ai.` hosts are managed outside
DealerOn.
