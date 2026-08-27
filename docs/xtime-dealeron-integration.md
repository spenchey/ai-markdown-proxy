# Xtime Schedule and DealerOn integration runbook

Status: one-location scaffold implemented; official Cox/Xtime configuration and DealerOn installation pending
Provider: Xtime Schedule by Cox Automotive
Service location: Carroll, 1526 Le Clark Road, Carroll, IA 51401
Planned transition: September 2026; exact cutover date not yet approved

## Correct operating model

Motor Inn has three separate customer-facing brands/sites but only one physical service location: Carroll. All service scheduling must resolve to that Carroll operation. The brands retain separate human and AI entry points for navigation, analytics, OEM presentation, and customer continuity; they do not represent three Xtime locations.

Xtime Schedule is Cox Automotive's scheduling product. Public dealership implementations use Cox-provided configuration under `https://consumer.xtime.com/scheduling` with a dealership-specific `webkey`. Do not copy another dealer's value or reverse-engineer the browser application. Cox/Xtime must supply Motor Inn's official Carroll configuration.

DealerOn owns the human-site embed/link installation. This repository owns the public AI mirror, stable handoff URLs, and machine-readable capability state.

## Stable Motor Inn entry points

These addresses are safe to publish before the official Xtime configuration arrives:

```text
https://ai.motorinnautogroup.com/service-scheduler
https://ai.motorinnofcarroll.com/service-scheduler
https://ai.motorinntoyotaofcarroll.com/service-scheduler
```

Each address preserves its brand identity but resolves to the same Carroll service location. While Xtime is inactive, it redirects to that brand's existing scheduling journey. After one verified Carroll activation, all three redirect to the official Carroll Xtime journey. Redirects use `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and `X-Robots-Tag: noindex, nofollow`.

`GET /api/v1/service-information` and the matching MCP tool expose the brand-specific address as `stableHandoffUrl` and the same structured `serviceLocation`. This is an external browser handoff, not an appointment API.

## Required Cox/Xtime inputs

Obtain and record outside this repository:

1. Motor Inn account owner and Cox/Xtime support contacts;
2. the official Carroll tenant/location identifier and consumer URL/webkey;
3. supported DealerOn embed or redirect instructions for all three branded sites;
4. current partner/API documentation and authorization terms;
5. test environment, credential workflow, allowed origins, and rate limits;
6. appointment create/get/reschedule/cancel schemas and durable confirmation semantics;
7. DMS synchronization, webhook/export timing, support SLA, and rollback path;
8. privacy, retention, consent, analytics, and data-processing terms.

Do not use the public browser application or an inferred endpoint as a transaction API.

## Runtime configuration

The public AI mirror uses one staged Carroll configuration:

```text
MOTORINN_XTIME_CARROLL_URL
MOTORINN_XTIME_CARROLL_ACTIVE
MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION
```

The URL must use HTTPS, the exact host `consumer.xtime.com`, the `/scheduling` path, exactly one non-empty `webkey`, no user information, no fragment, no non-standard port, and no unknown query parameters.

Activation defaults to `false`. After an operator verifies that Cox's configuration belongs to Motor Inn's Carroll location, set `MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION=carroll`. Set `MOTORINN_XTIME_CARROLL_ACTIVE=true` only in the approved cutover window. Any malformed or unverified active configuration fails closed with `503 source_unavailable`.

Never commit real webkeys, credentials, customer data, or appointment payloads. Production reads the encrypted SSM parameter `/motorinn/ai-markdown-proxy/runtime-env`, writes it mode `0600`, and supplies it to the container with `--env-file`. Verification must inspect only expected variable names and public behavior, never parameter values.

## DealerOn installation request

On each human site, DealerOn should:

1. install the exact Cox-provided Carroll Xtime configuration on the branded service appointment page;
2. preserve a normal HTTPS fallback link when the embed cannot load;
3. clearly state that service is performed at the Carroll location and show its address;
4. provide an accessible heading, scheduler name, loading/error state, and customer-support fallback;
5. verify keyboard, screen-reader, mobile, consent, analytics, and Content Security Policy behavior;
6. preserve the site's matching AI-mirror alternate/footer links;
7. return final public URLs, release time, implementation owner, acceptance evidence, and rollback instructions.

DealerOn must not invent three Xtime locations. The three pages may retain brand-specific labels such as “Schedule Chevrolet service” or “Schedule Toyota service,” but the destination and displayed service address must be Carroll.

## Pre-activation checks

Run the safe validator; it reports fixed identifiers and Motor Inn-owned URLs but never prints the Xtime URL or webkey:

```bash
.venv/bin/python tools/xtime_preflight.py --require configured
.venv/bin/python tools/xtime_preflight.py --require verified
.venv/bin/python tools/xtime_preflight.py --require active
```

Exit code `0` means the single Carroll configuration meets the requested stage. Exit code `2` means it does not or the configuration is invalid.

Before activation, verify all three public service-information responses. Each must contain the same `serviceLocation`, `providerTransition.locationKey: carroll`, and `providerTransition.locationBindingVerified` state, while retaining its own `site` and `stableHandoffUrl`.

```bash
curl -sS https://ai.motorinnautogroup.com/api/v1/service-information
curl -sS https://ai.motorinnofcarroll.com/api/v1/service-information
curl -sS https://ai.motorinntoyotaofcarroll.com/api/v1/service-information
curl -sSI https://ai.motorinnautogroup.com/service-scheduler
curl -sSI https://ai.motorinnofcarroll.com/service-scheduler
curl -sSI https://ai.motorinntoyotaofcarroll.com/service-scheduler
```

## Cutover and rollback

In an owner-approved window:

1. verify the official Cox configuration against the Carroll account/location;
2. record `MOTORINN_XTIME_CARROLL_VERIFIED_LOCATION=carroll` and run the `verified` preflight;
3. enable `MOTORINN_XTIME_CARROLL_ACTIVE=true` and run the `active` preflight;
4. verify equivalent HTTP and MCP service-information results on all three hosts;
5. complete one staff-supervised appointment through each branded entry point and verify each reaches the same Carroll scheduler without losing source attribution;
6. record the durable Xtime appointment identifiers and reconcile them to the correct DMS/`SV_APPT` records;
7. test retrieve, reschedule, cancel, duplicate, timeout, stale-slot, and scheduler-load behavior.

Rollback is setting the one Carroll activation flag back to `false` and restoring the prior DealerOn journeys. Rollback does not cancel appointments already confirmed in Xtime; those remain authoritative Xtime records and require operational reconciliation.

## Transaction boundary

The public API and MCP server expose information and a browser handoff only. They do not expose live slots or appointment writes. Protected tools may be added only after Cox/Xtime supplies a supported contract and the separate transaction-security contract passes. A page load or form submission is not a confirmed appointment; only a durable Xtime appointment identifier and authoritative state permit `confirmed`.
