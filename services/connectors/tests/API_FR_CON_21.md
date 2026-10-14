# Vendor-facing sites — public API these tests pin (FR-CON-21)

PRD supplement 2026-10-05 s6 (Could; an interpretation of "3rd-party vendor side websites" the user may refine).
Tests: `test_FR_CON_21_vendor_sites.py`, over the merged Lovable link route (`_handoff_lib.py`). FR-CON-18 (MCP
route) is not on this base; the brief goes through FR-CON-16/17: T3, a person approves, Tilo only makes a link.
No contract change: nothing is emitted, no event type is added.

## `tilo_connectors.vendor_site` (no network, no model)

- `vendor_spec(raw) -> VendorSiteSpec`: keys `needs`, `tracks`, `access`, optional `status_sources`; every value
  from a fixed vocabulary (`NEEDS`, `TRACKS`, `ACCESS`), no free text. `HandoffRefused`: `VS-01` any other field
  (a credential field is never one; the value is never echoed), `VS-02` a value outside the vocabulary, a bad or
  repeated status source (`web` needs an https page with no query, `connector` an id).
- `vendor_requirements(accepted, spec)`: the accepted requirements plus the fixed sentences as constraints; nothing
  else is added. `prepare_vendor_site(accepted=, spec=, **prepare_handoff kwargs)` is `prepare_handoff` over it, so
  BH-01..BH-09 (redactor, safety screen, declined texts, length, T3 gate) and DG-* apply unchanged.
- Access is by invite or link from the site's own sign-in (`ACCESS`); the brief sets up no vendor account, and no
  module here takes, types or stores a credential.
- `vendor_status(spec, records, run_id=, archive_head=None) -> VendorStatus`: per connected source, its latest
  recorded read in the run's raw archive (a `tool_call` record whose `payload.source` is exactly the connected
  kind and ref), `state` `read` with `archive_ref` `<run_id>/<seq>`, `read_at`, `fingerprint` and a 300 character
  `excerpt`, else `not_read` with no value (HR-1). A read of a page that was not connected is never shown. A record
  of another run or a broken hash chain is `VS-03`. A web ref matches exactly as archived (a read with a query
  string does not match the connected page).
