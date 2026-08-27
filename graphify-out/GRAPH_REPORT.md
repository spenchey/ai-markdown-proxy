# Graph Report - ai-markdown-proxy  (2026-08-27)

## Corpus Check
- 39 files · ~25,098 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 404 nodes · 754 edges · 40 communities (30 shown, 10 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS · INFERRED: 3 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e3f09dbf`
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

## God Nodes (most connected - your core abstractions)
1. `AgentAccessTests` - 26 edges
2. `Site` - 22 edges
3. `resolve_site()` - 20 edges
4. `vehicle_search()` - 15 edges
5. `serve_agent_query()` - 14 edges
6. `_text()` - 12 edges
7. `_vehicle_projection()` - 12 edges
8. `api_error()` - 12 edges
9. `ProxyTests` - 12 edges
10. `What It Serves` - 12 edges

## Surprising Connections (you probably didn't know these)
- `InvalidRequest` --inherits--> `ValueError`  [EXTRACTED]
  agent_access.py →   _Bridges community 1 → community 37_
- `api_response()` --references--> `Any`  [EXTRACTED]
  server.py →   _Bridges community 7 → community 0_
- `serve_agent_query()` --calls--> `parse_agent_query()`  [EXTRACTED]
  server.py → server.py  _Bridges community 37 → community 0_

## Import Cycles
- None detected.

## Communities (40 total, 10 thin omitted)

### Community 0 - "server.py"
Cohesion: 0.09
Nodes (71): Exception, Response, agent_query_error(), api_error(), api_response(), build_query_documents(), build_static_query_documents(), cache_get() (+63 more)

### Community 1 - "agent_access.py"
Cohesion: 0.16
Nodes (39): _available_read_operations(), _base_price(), _bounded_text(), _canonical_catalog_url(), _condition(), ConfigurationUnavailable, _cursor_fingerprint(), _decimal() (+31 more)

### Community 2 - "health_monitor.py"
Cohesion: 0.19
Nodes (12): _aws(), evaluate_result(), lambda_handler(), _load_state(), _post_slack(), _publish_metrics(), Any, _request() (+4 more)

### Community 3 - "What It Serves"
Cohesion: 0.11
Nodes (17): AI-Readable Mirror for Motor Inn Auto Group, Architecture, Cost, Deploy to AWS, `GET /` and `GET /sitemap.xml`, `GET /__health`, `GET /llms?query=...` and `GET /llms/json?query=...`, `GET /llms.txt` and `GET /llms-full.txt` (+9 more)

### Community 4 - "Agent Access Foundation v1"
Cohesion: 0.12
Nodes (15): Agent Access Foundation v1, Confirmed test seams, Current progress, Definition of done for this slice, Deployment boundary, Error contract, `GET /api/v1/locations`, `GET /api/v1/parts-information` (+7 more)

### Community 7 - "build_static_query_documents"
Cohesion: 0.16
Nodes (28): agent_query_health(), api_inventory_detail(), api_inventory_search(), canonical_catalog_link(), classify_bot(), display_price(), finish_request(), full_health() (+20 more)

### Community 9 - "Transaction security contract"
Cohesion: 0.20
Nodes (9): Approval contract, Audit and privacy contract, Boundary, Failure and isolation tests, Idempotency contract, OAuth and identity requirements, Receipt contract, State invariant (+1 more)

### Community 10 - "Xtime Schedule and DealerOn integration runbook"
Cohesion: 0.20
Nodes (9): Correct operating model, Cutover and rollback, DealerOn installation request, Pre-activation checks, Required Cox/Xtime inputs, Runtime configuration, Stable Motor Inn entry points, Transaction boundary (+1 more)

### Community 11 - "Motor Inn Auto Group — Contact and Regular Hours"
Cohesion: 0.29
Nodes (6): Location, Motor Inn Auto Group — Contact and Regular Hours, Parts hours, Public phone details, Sales hours, Service hours

### Community 12 - "Motor Inn of Carroll — Contact and Regular Hours"
Cohesion: 0.29
Nodes (6): Location, Motor Inn of Carroll — Contact and Regular Hours, Parts hours, Public phone details, Sales hours, Service hours

### Community 13 - "Motor Inn Toyota Of Carroll — Contact and Regular Hours"
Cohesion: 0.29
Nodes (6): Location, Motor Inn Toyota Of Carroll — Contact and Regular Hours, Parts hours, Public phone details, Sales hours, Service hours

### Community 14 - "Motor Inn Auto Group — Dealership Facts"
Cohesion: 0.33
Nodes (5): Aliases and relationships, Authoritative human sources, Identity, Motor Inn Auto Group — Dealership Facts, Public phone details

### Community 15 - "Motor Inn of Carroll — Dealership Facts"
Cohesion: 0.33
Nodes (5): Aliases and relationships, Authoritative human sources, Identity, Motor Inn of Carroll — Dealership Facts, Public phone details

### Community 16 - "Motor Inn Toyota Of Carroll — Dealership Facts"
Cohesion: 0.33
Nodes (5): Aliases and relationships, Authoritative human sources, Identity, Motor Inn Toyota Of Carroll — Dealership Facts, Public phone details

### Community 17 - "manifest.json"
Cohesion: 0.40
Nodes (4): files, generatedAt, schema, sourcePackage

### Community 18 - "Motor Inn Auto Group — Finance and Trade"
Cohesion: 0.50
Nodes (3): Available resources, Canonical forms and tools, Motor Inn Auto Group — Finance and Trade

### Community 19 - "Motor Inn Auto Group — Policies and Data Use"
Cohesion: 0.50
Nodes (3): Canonical policy resources, Machine-readable content rules, Motor Inn Auto Group — Policies and Data Use

### Community 20 - "Motor Inn Auto Group — Service and Parts"
Cohesion: 0.50
Nodes (3): Capabilities, Motor Inn Auto Group — Service and Parts, Take the next step

### Community 21 - "Motor Inn of Carroll — Finance and Trade"
Cohesion: 0.50
Nodes (3): Available resources, Canonical forms and tools, Motor Inn of Carroll — Finance and Trade

### Community 22 - "Motor Inn of Carroll — Policies and Data Use"
Cohesion: 0.50
Nodes (3): Canonical policy resources, Machine-readable content rules, Motor Inn of Carroll — Policies and Data Use

### Community 23 - "Motor Inn of Carroll — Service and Parts"
Cohesion: 0.50
Nodes (3): Capabilities, Motor Inn of Carroll — Service and Parts, Take the next step

### Community 24 - "Motor Inn Toyota Of Carroll — Finance and Trade"
Cohesion: 0.50
Nodes (3): Available resources, Canonical forms and tools, Motor Inn Toyota Of Carroll — Finance and Trade

### Community 25 - "Motor Inn Toyota Of Carroll — Policies and Data Use"
Cohesion: 0.50
Nodes (3): Canonical policy resources, Machine-readable content rules, Motor Inn Toyota Of Carroll — Policies and Data Use

### Community 26 - "Motor Inn Toyota Of Carroll — Service and Parts"
Cohesion: 0.50
Nodes (3): Capabilities, Motor Inn Toyota Of Carroll — Service and Parts, Take the next step

### Community 27 - "DealerOn Implementation Request"
Cohesion: 0.50
Nodes (3): Acceptance Criteria, DealerOn Implementation Request, Required URLs

### Community 28 - "main"
Cohesion: 0.83
Nodes (3): Path, main(), sha256()

### Community 36 - "xtime_preflight.py"
Cohesion: 0.70
Nodes (4): main(), preflight(), _requirement_satisfied(), _safe_location_status()

### Community 37 - "parse_agent_query"
Cohesion: 0.83
Nodes (4): normalize_query(), parse_agent_query(), query_limit(), ValueError

### Community 38 - "DealerOn site and page requirements"
Cohesion: 0.25
Nodes (7): Business model, DealerOn site and page requirements, Global discovery installation, Parts pages, Return package, Service scheduling pages, Vehicle search and vehicle pages

### Community 39 - "DealerOn acceptance checklist"
Cohesion: 0.29
Nodes (6): DealerOn acceptance checklist, Discovery, Evidence and rollback, Parts access, Service access, Vehicle access

## Knowledge Gaps
- **110 isolated node(s):** `files`, `generatedAt`, `schema`, `sourcePackage`, `deploy-monitoring.sh script` (+105 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What connects `files`, `generatedAt`, `schema` to the rest of the system?**
  _110 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `server.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08626434653831914 - nodes in this community are weakly interconnected._
- **Should `What It Serves` be split into smaller, more focused modules?**
  _Cohesion score 0.1111111111111111 - nodes in this community are weakly interconnected._
- **Should `Agent Access Foundation v1` be split into smaller, more focused modules?**
  _Cohesion score 0.125 - nodes in this community are weakly interconnected._
- **Should `AgentAccessTests` be split into smaller, more focused modules?**
  _Cohesion score 0.08831908831908832 - nodes in this community are weakly interconnected._