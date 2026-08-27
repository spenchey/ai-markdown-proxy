# DealerOn site and page requirements

## Business model

Motor Inn operates three separate branded websites and AI hosts. It has one physical service location: Carroll, at 1526 Le Clark Road, Carroll, IA 51401. Preserve each brand identity, but do not create three Xtime locations.

## Global discovery installation

For each human site:

- publish its supplied root `llms.txt` and `llms-full.txt` without redirects;
- merge the supplied crawler additions into the existing `robots.txt`;
- add a visible footer link such as “AI-readable site” to the matching `ai.` host;
- add `<link rel="alternate" type="text/markdown">` for the matching AI-readable resource where DealerOn supports it;
- do not point a site at either of the other brands' AI hosts;
- preserve canonical tags, inventory feeds, analytics, accessibility, and Google SEO behavior.

## Vehicle search and vehicle pages

- Keep search results and vehicle detail pages available as normal HTTPS links.
- Preserve VIN, stock number, condition, year, make, model, trim, price, mileage, photos, disclosures, and canonical VDP URL in rendered page content when known.
- Do not require a chat widget, login, or form submission to view listed inventory.
- Provide crawlable pagination/filter links or a canonical inventory results link.
- Never describe a listed unit as reserved, held, or physically available unless the authoritative inventory/commerce system confirms that state.

## Service scheduling pages

- Keep one accessible service appointment page on each branded site.
- State clearly that the service location is Carroll and render the Carroll address.
- Install the exact official Cox/Xtime Carroll configuration when Motor Inn supplies it; do not copy another dealer's webkey or infer a private API.
- Preserve an ordinary HTTPS fallback link and a phone/contact fallback if the embed fails.
- Link each brand page to its matching stable AI URL:
  - group: `https://ai.motorinnautogroup.com/service-scheduler`
  - Chevrolet: `https://ai.motorinnofcarroll.com/service-scheduler`
  - Toyota: `https://ai.motorinntoyotaofcarroll.com/service-scheduler`
- A submitted form is not a confirmed appointment. Only Xtime's durable appointment identifier/state may be presented as confirmation.

## Parts pages

- Keep a crawlable parts landing/request page on each branded site.
- Expose ordinary fields and labels for part description, VIN, contact method, and consent; do not hide the only path inside a chat widget.
- Preserve an accessible customer-support fallback.
- Link to the matching AI-readable `/api/v1/parts-information` resource.
- Do not claim fitment, stock, reservation, payment, or confirmed order unless the authoritative parts/commerce system returns that state.

## Return package

Return the final URLs, release timestamp, DealerOn owner, rollback steps, screenshots, HTTP headers, and completed acceptance checklist. Identify any CMS limitation explicitly rather than silently omitting a requirement.
