# DealerOn acceptance checklist

Complete once for each of the group, Chevrolet, and Toyota human websites.

## Discovery

- [ ] Root `llms.txt` returns 200 without redirect and uses UTF-8 text/Markdown.
- [ ] Root `llms-full.txt` returns 200 without redirect and uses UTF-8 text/Markdown.
- [ ] Files reference only the matching AI host.
- [ ] Existing robots rules remain; approved search/citation crawler rules are merged.
- [ ] Visible footer and alternate discovery links resolve to the matching AI host.

## Vehicle access

- [ ] Inventory search is usable without login or chat interaction.
- [ ] Search results link to canonical vehicle pages.
- [ ] A currently listed VIN can be found through both the human site and matching AI vehicle endpoint.
- [ ] Removed/wrong-brand vehicles are not returned as available.

## Service access

- [ ] The branded service page names the one Carroll service location and address.
- [ ] The brand's stable `/service-scheduler` entry point resolves correctly.
- [ ] Xtime embed/fallback is keyboard, screen-reader, mobile, consent, and CSP tested.
- [ ] A staff-supervised test produces a durable Xtime confirmation before the UI says confirmed.

## Parts access

- [ ] The parts page and request form are accessible without chat interaction.
- [ ] The matching AI parts-information endpoint resolves.
- [ ] Request states are not mislabeled as stock, fitment, reservation, payment, or confirmed order.

## Evidence and rollback

- [ ] Final public URLs, response headers, screenshots, release time, and implementation owner attached.
- [ ] Rollback steps tested and recorded.
- [ ] Any exception has an owner and target date.
