# Cross-agent read conformance harness

`tools/read_conformance.py` is a bounded, non-mutating canary for the three
Motor Inn AI hosts. It performs only public `GET` requests and JSON-RPC `POST`
requests to `/mcp` using the five tools whose contracts declare them read-only.

It checks:

- each hostname's OpenAPI document is host-scoped and contains no mutation;
- MCP exposes exactly the five approved read tools with safe annotations;
- OpenAPI JSON and MCP structured content are identical for vehicle search,
  location, service-information, and parts-information reads;
- inventory pages fail closed when the structured inventory source is
  unavailable, or contain every VIN returned by the structured interfaces;
- public contact/service pages corroborate location and action facts;
- `llms.txt` advertises the same hostname's OpenAPI and MCP endpoints; and
- optional, secret-free captures from supported clients do not invent facts.

Run the live canary:

```bash
.venv/bin/python tools/read_conformance.py
```

Exit `0` means all checks passed. Exit `2` means at least one interface is
inconsistent. Exit `3` means the interfaces agree but an authoritative source
is unavailable, so the system is correctly failing closed but is degraded.

## Supported client evidence

ChatGPT, Claude, Gemini, Perplexity, and browser-client results are captured
outside this repository because those sessions can require user accounts and
platform review. The harness accepts only deliberately minimal evidence; it
rejects common credential fields and URLs containing sensitive query values.

```json
{
  "schema": "motorinn.clientReadEvidence.v1",
  "client": "chatgpt",
  "host": "ai.motorinnofcarroll.com",
  "capturedAt": "2026-08-31T15:00:00Z",
  "observations": {
    "locations": {"locationKeys": ["carroll"]},
    "service": {
      "capabilityState": "external_handoff",
      "locationKeys": ["carroll"]
    }
  }
}
```

Require a capture during a certification run:

```bash
.venv/bin/python tools/read_conformance.py \
  --client-evidence evidence/chatgpt.json \
  --require-client chatgpt
```

Do not put prompts, customer data, authentication headers, provider webkeys,
tokens, or screenshots containing private account state in an evidence file.
