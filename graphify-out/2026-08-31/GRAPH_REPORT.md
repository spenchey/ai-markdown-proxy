# Graph Report - ai-markdown-proxy  (2026-08-31)

## Corpus Check
- 43 files · ~28,085 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 459 nodes · 830 edges · 49 communities (28 shown, 21 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 12 edges (avg confidence: 0.7)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `89f2937c`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- server.py
- agent_access.py
- health_monitor.py
- What It Serves
- Agent Access Foundation v1
- AgentAccessTests
- ProxyTests
- build_static_query_documents
- AgentQueryTests
- Transaction security contract
- Xtime Schedule and DealerOn integration runbook
- Motor Inn Auto Group — Contact and Regular Hours
- Motor Inn of Carroll — Contact and Regular Hours
- Motor Inn Toyota Of Carroll — Contact and Regular Hours
- Motor Inn Auto Group — Dealership Facts
- Motor Inn of Carroll — Dealership Facts
- Motor Inn Toyota Of Carroll — Dealership Facts
- manifest.json
- Motor Inn Auto Group — Finance and Trade
- Motor Inn Auto Group — Policies and Data Use
- Motor Inn Auto Group — Service and Parts
- Motor Inn of Carroll — Finance and Trade
- Motor Inn of Carroll — Policies and Data Use
- Motor Inn of Carroll — Service and Parts
- Motor Inn Toyota Of Carroll — Finance and Trade
- Motor Inn Toyota Of Carroll — Policies and Data Use
- Motor Inn Toyota Of Carroll — Service and Parts
- DealerOn Implementation Request
- main
- parse_agent_query
- DealerOnDiscoveryHandoffTests
- README.md
- deploy.sh
- deploy-monitoring.sh
- __init__.py
- user-data.sh
- xtime_preflight.py
- parse_agent_query
- DealerOn site and page requirements
- DealerOn acceptance checklist
- user-data.sh
- Any
- datetime
- RuntimeError
- Any
- Path
- Any
- datetime
- RuntimeError

## God Nodes (most connected - your core abstractions)
1. `AgentAccessTests` - 26 edges
2. `Site` - 22 edges
3. `ReadConformanceHarness` - 20 edges
4. `resolve_site()` - 20 edges
5. `HttpResult` - 14 edges
6. `serve_agent_query()` - 14 edges
7. `vehicle_search()` - 13 edges
8. `What It Serves` - 13 edges
9. `api_error()` - 12 edges
10. `ProxyTests` - 12 edges

## Surprising Connections (you probably didn't know these)
- `_post_slack()` --indirect_call--> `response()`  [INFERRED]
  infra/health_monitor.py → tests/test_read_conformance.py
- `FixtureTransport` --uses--> `HttpResult`  [INFERRED]
  tests/test_read_conformance.py → read_conformance.py
- `ReadConformanceTests` --uses--> `HttpResult`  [INFERRED]
  tests/test_read_conformance.py → read_conformance.py
- `FixtureTransport` --uses--> `ReadConformanceHarness`  [INFERRED]
  tests/test_read_conformance.py → read_conformance.py
- `ReadConformanceTests` --uses--> `ReadConformanceHarness`  [INFERRED]
  tests/test_read_conformance.py → read_conformance.py

## Import Cycles
- None detected.

## Communities (49 total, 21 thin omitted)

### Community 0 - "server.py"
Cohesion: 0.07
Nodes (96): Exception, Response, agent_query_error(), agent_query_health(), api_error(), api_inventory_detail(), api_inventory_search(), api_response() (+88 more)

### Community 1 - "agent_access.py"
Cohesion: 0.14
Nodes (36): _available_read_operations(), _base_price(), _bounded_text(), _canonical_catalog_url(), _condition(), ConfigurationUnavailable, _cursor_fingerprint(), _decimal() (+28 more)

### Community 3 - "What It Serves"
Cohesion: 0.11
Nodes (18): AI-Readable Mirror for Motor Inn Auto Group, Architecture, Cost, Cross-agent read conformance, Deploy to AWS, `GET /` and `GET /sitemap.xml`, `GET /__health`, `GET /llms?query=...` and `GET /llms/json?query=...` (+10 more)

### Community 4 - "Agent Access Foundation v1"
Cohesion: 0.12
Nodes (15): Agent Access Foundation v1, Confirmed test seams, Current progress, Definition of done for this slice, Deployment boundary, Error contract, `GET /api/v1/locations`, `GET /api/v1/parts-information` (+7 more)

### Community 6 - "ProxyTests"
Cohesion: 0.40
Nodes (10): _aws(), evaluate_result(), lambda_handler(), _load_state(), _post_slack(), _publish_metrics(), _request(), _save_state() (+2 more)

### Community 8 - "AgentQueryTests"
Cohesion: 0.20
Nodes (9): Approval contract, Audit and privacy contract, Boundary, Failure and isolation tests, Idempotency contract, OAuth and identity requirements, Receipt contract, State invariant (+1 more)

### Community 9 - "Transaction security contract"
Cohesion: 0.20
Nodes (9): Correct operating model, Cutover and rollback, DealerOn installation request, Pre-activation checks, Required Cox/Xtime inputs, Runtime configuration, Stable Motor Inn entry points, Transaction boundary (+1 more)

### Community 11 - "Motor Inn Auto Group — Contact and Regular Hours"
Cohesion: 0.25
Nodes (7): Business model, DealerOn site and page requirements, Global discovery installation, Parts pages, Return package, Service scheduling pages, Vehicle search and vehicle pages

### Community 13 - "Motor Inn Toyota Of Carroll — Contact and Regular Hours"
Cohesion: 0.29
Nodes (6): Location, Motor Inn Auto Group — Contact and Regular Hours, Parts hours, Public phone details, Sales hours, Service hours

### Community 14 - "Motor Inn Auto Group — Dealership Facts"
Cohesion: 0.29
Nodes (6): Location, Motor Inn of Carroll — Contact and Regular Hours, Parts hours, Public phone details, Sales hours, Service hours

### Community 15 - "Motor Inn of Carroll — Dealership Facts"
Cohesion: 0.29
Nodes (6): Location, Motor Inn Toyota Of Carroll — Contact and Regular Hours, Parts hours, Public phone details, Sales hours, Service hours

### Community 16 - "Motor Inn Toyota Of Carroll — Dealership Facts"
Cohesion: 0.29
Nodes (6): DealerOn acceptance checklist, Discovery, Evidence and rollback, Parts access, Service access, Vehicle access

### Community 17 - "manifest.json"
Cohesion: 0.40
Nodes (4): files, generatedAt, schema, sourcePackage

### Community 18 - "Motor Inn Auto Group — Finance and Trade"
Cohesion: 0.33
Nodes (5): Aliases and relationships, Authoritative human sources, Identity, Motor Inn Auto Group — Dealership Facts, Public phone details

### Community 19 - "Motor Inn Auto Group — Policies and Data Use"
Cohesion: 0.33
Nodes (5): Aliases and relationships, Authoritative human sources, Identity, Motor Inn of Carroll — Dealership Facts, Public phone details

### Community 20 - "Motor Inn Auto Group — Service and Parts"
Cohesion: 0.50
Nodes (3): Capabilities, Motor Inn Auto Group — Service and Parts, Take the next step

### Community 21 - "Motor Inn of Carroll — Finance and Trade"
Cohesion: 0.33
Nodes (5): Aliases and relationships, Authoritative human sources, Identity, Motor Inn Toyota Of Carroll — Dealership Facts, Public phone details

### Community 23 - "Motor Inn of Carroll — Service and Parts"
Cohesion: 0.70
Nodes (4): main(), preflight(), _requirement_satisfied(), _safe_location_status()

### Community 24 - "Motor Inn Toyota Of Carroll — Finance and Trade"
Cohesion: 0.50
Nodes (3): Available resources, Canonical forms and tools, Motor Inn Auto Group — Finance and Trade

### Community 25 - "Motor Inn Toyota Of Carroll — Policies and Data Use"
Cohesion: 0.50
Nodes (3): Canonical policy resources, Machine-readable content rules, Motor Inn Auto Group — Policies and Data Use

### Community 26 - "Motor Inn Toyota Of Carroll — Service and Parts"
Cohesion: 0.50
Nodes (3): Capabilities, Motor Inn Toyota Of Carroll — Service and Parts, Take the next step

### Community 27 - "DealerOn Implementation Request"
Cohesion: 0.50
Nodes (3): Available resources, Canonical forms and tools, Motor Inn of Carroll — Finance and Trade

### Community 28 - "main"
Cohesion: 0.50
Nodes (3): Canonical policy resources, Machine-readable content rules, Motor Inn of Carroll — Policies and Data Use

### Community 29 - "parse_agent_query"
Cohesion: 0.50
Nodes (3): Capabilities, Motor Inn of Carroll — Service and Parts, Take the next step

### Community 30 - "DealerOnDiscoveryHandoffTests"
Cohesion: 0.50
Nodes (3): Available resources, Canonical forms and tools, Motor Inn Toyota Of Carroll — Finance and Trade

### Community 31 - "README.md"
Cohesion: 0.50
Nodes (3): Canonical policy resources, Machine-readable content rules, Motor Inn Toyota Of Carroll — Policies and Data Use

### Community 32 - "deploy.sh"
Cohesion: 0.50
Nodes (3): Acceptance Criteria, DealerOn Implementation Request, Required URLs

### Community 37 - "parse_agent_query"
Cohesion: 0.10
Nodes (29): Protocol, _content_type(), _error_code(), exit_code(), _finding(), HttpResult, load_client_evidence(), _mcp_payload() (+21 more)

## Knowledge Gaps
- **112 isolated node(s):** `files`, `generatedAt`, `schema`, `sourcePackage`, `deploy-monitoring.sh script` (+107 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `InvalidRequest` connect `agent_access.py` to `parse_agent_query`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `parse_agent_query()` connect `parse_agent_query` to `server.py`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `ReadConformanceHarness` (e.g. with `FixtureTransport` and `ReadConformanceTests`) actually correct?**
  _`ReadConformanceHarness` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `files`, `generatedAt`, `schema` to the rest of the system?**
  _112 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `server.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06637806637806638 - nodes in this community are weakly interconnected._
- **Should `agent_access.py` be split into smaller, more focused modules?**
  _Cohesion score 0.14264264264264265 - nodes in this community are weakly interconnected._
- **Should `health_monitor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08831908831908832 - nodes in this community are weakly interconnected._