# Xtime Schedule and DealerOn integration runbook

Status: scaffold implemented; Cox/Xtime tenant values and DealerOn installation pending
Provider: Xtime Schedule by Cox Automotive
Planned transition: September 2026; exact cutover date not yet approved

## Proven public pattern

Xtime Schedule is Cox Automotive's consumer scheduling and shop-capacity product. Cox describes online/mobile booking, real-time availability, configurable menus and pricing, reminders, and capacity management.

Live dealership pages use tenant-specific URLs under:

```text
https://consumer.xtime.com/scheduling/?...&webkey=<dealer-specific-value>
```

The `webkey` selects dealership configuration. A third party's value must never be copied. Cox/Xtime must supply one owner-approved URL for each Motor Inn rooftop.

DealerOn advertises online service scheduling through DMS integration and supports third-party website applications. DealerOn remains the owner of the human-site embed/link change; this repository owns only the public AI mirror and its machine-readable capability state.

## Required Cox/Xtime onboarding inputs

Obtain and record outside this repository:

1. Motor Inn account owner and Cox/Xtime support contacts;
2. tenant and rooftop identifiers;
3. one consumer scheduling URL/webkey for the group, Chevrolet, and Toyota journeys;
4. supported embedding or redirect instructions for DealerOn;
5. current partner/API documentation and authorization terms;
6. test environment, credentials workflow, allowed origins, and rate limits;
7. appointment create/get/reschedule/cancel schemas and durable confirmation semantics;
8. DMS synchronization, webhook/export timing, support SLA, and rollback path;
9. privacy, retention, consent, analytics, and data-processing terms.

Do not use the public browser application or a reverse-engineered endpoint as a transaction API.

## Runtime configuration

The public AI mirror has separate staged values and activation gates:

```text
MOTORINN_XTIME_GROUP_URL
MOTORINN_XTIME_GROUP_ACTIVE
MOTORINN_XTIME_GROUP_VERIFIED_ROOFTOP
MOTORINN_XTIME_CHEVY_URL
MOTORINN_XTIME_CHEVY_ACTIVE
MOTORINN_XTIME_CHEVY_VERIFIED_ROOFTOP
MOTORINN_XTIME_TOYOTA_URL
MOTORINN_XTIME_TOYOTA_ACTIVE
MOTORINN_XTIME_TOYOTA_VERIFIED_ROOFTOP
```

URLs are read at request time. An active URL must:

- use HTTPS;
- use the exact host `consumer.xtime.com`;
- use the `/scheduling` path;
- include exactly one non-empty `webkey` query parameter;
- contain no user information, fragment, non-standard port, or unknown query parameters.

Activation defaults to `false`. A valid configured URL with activation off is reported as `planned` and `configured`. Before activation, an operator must set the corresponding verified-rooftop value to the exact site key (`motorinnautogroup`, `motorinnchevy`, or `motorinntoyota`) after checking the Cox/DealerOn tenant identity. Setting activation to `true` switches the service handoff only when both the URL and rooftop binding are valid. An invalid, missing, or unverified active configuration returns a typed `503 source_unavailable` response rather than falling through or claiming success.

Never commit real tenant URLs, webkeys, credentials, customer data, or appointment payloads to this repository.

Production deployment reads the environment-file body from the encrypted SSM parameter `/motorinn/ai-markdown-proxy/runtime-env`, writes it mode `0600` on the host, and supplies it to the container with `--env-file`. The deployment fails if the parameter cannot be read, so a redeploy cannot silently erase the staged or active rooftop configuration. Verify only the expected variable names and service behavior; do not print the parameter value or public tenant URLs into logs.

## DealerOn installation request

For each of the three customer sites, DealerOn should:

1. install the exact Cox-provided Xtime configuration on the branded service appointment page;
2. preserve a normal HTTPS link that opens the scheduler when an iframe or script cannot load;
3. provide an accessible page heading, scheduler name, load/error state, and customer support fallback;
4. verify keyboard, screen-reader, mobile, cookie/consent, analytics, and Content Security Policy behavior;
5. preserve the existing AI-mirror alternate and footer links;
6. return the final public URL, site ID, release time, implementation owner, and rollback instructions.

The group page must not silently select a rooftop. It should require the customer to choose Chevrolet or Toyota unless Cox provides a verified group tenant that preserves the selected location.

## Pre-activation checks

With each URL configured but inactive:

```bash
curl -sS https://ai.motorinnautogroup.com/api/v1/service-information
curl -sS https://ai.motorinnofcarroll.com/api/v1/service-information
curl -sS https://ai.motorinntoyotaofcarroll.com/api/v1/service-information
```

Each response must report:

- `providerTransition.targetProvider` as `Xtime Schedule by Cox Automotive`;
- `providerTransition.status` as `planned`;
- `providerTransition.configured` as `true`;
- `providerTransition.rooftopBindingVerified` as `false` until the tenant check is recorded;
- `providerTransition.active` as `false`;
- the existing customer journey as the current `actionUrl`.

Then verify the three DealerOn pages independently. The dealership name, address, service department, OEM identity, timezone, and available services must match the selected rooftop.

## Cutover and rollback

Activate one rooftop at a time in an owner-approved window:

1. record the verified site key in `MOTORINN_XTIME_*_VERIFIED_ROOFTOP`, then enable the corresponding `MOTORINN_XTIME_*_ACTIVE=true` value;
2. verify the HTTP and MCP service-information results are equivalent;
3. follow the public action URL and complete a staff-supervised appointment;
4. record the Xtime appointment identifier and source-system timestamp;
5. retrieve, reschedule, and cancel it through supported Xtime operations;
6. reconcile it to the correct DMS/`SV_APPT` record when the feed arrives;
7. monitor wrong-rooftop, duplicate, timeout, stale-slot, and scheduler-load failures.

Rollback is setting the rooftop activation flag back to `false` and restoring the previous DealerOn service journey. A rollback does not cancel appointments already confirmed in Xtime; those remain authoritative Xtime records and need an operational reconciliation plan.

## Agent transaction boundary

The public API and MCP server expose information and an external handoff only. They do not expose live slots or appointment writes.

Protected transaction tools may be added only after Cox/Xtime provides a supported contract and the separate transaction security contract passes. A successful HTTP response, DealerOn page load, or form submission is not a confirmed appointment. Only a durable Xtime appointment identifier and authoritative state permit `confirmed`.
