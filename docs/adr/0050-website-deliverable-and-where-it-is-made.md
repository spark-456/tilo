# ADR-0050: The website deliverable (one sandboxed HTML file) and where each deliverable is made

- Status: **Accepted** (16 Oct 2026). The owner wrote in the supervisor chat, verbatim: "This is my YES to the
  website output (ADR + contract change to allow a self-contained HTML deliverable, sandboxed preview, no network,
  security review)"; the direction is quoted verbatim below.
- Deciders: owner (scope and approval), supervisor (acceptance), architect (design), security reviewer (WEB-1,
  WEB-2, WEB-3, WEB-5)
- Requirements: FR-AGT-16 (deliverables Tilo builds), FR-CON-16, FR-CON-17, FR-CON-19, FR-CON-20, FR-CON-22,
  FR-INT-15, FR-AGT-13; PRD 9.4 (HR-1), 10.4, 12.4, 16.2; ADR-0018 (artifact store), ADR-0029 decision 9 (AppSpec)
- Number: 0050. 0049 (`docs/adr/0049-memory-notes-morning-brief-and-grounding.md`) is the highest on any branch on
  16 Oct; no branch mentions ADR-0050. New rule ids WS-01 to WS-15 (`contracts/website.rules.md`), MK-01 to MK-08
  (`contracts/makers.rules.md`) and AR-10; questions BQ-WEBSITE-1 to BQ-WEBSITE-7.

## Context

A live run asked for "a cool looking website showing over 40 different timezones live". The brief could only say
`app`, which is the AppSpec quiz (ADR-0029 decision 9), so the run failed. The contracts refuse a website outright:
`deliverable_format` has no website and `media_type` is closed ("no HTML or SVG"). What exists: the Lovable link
route (FR-CON-16, -17: `build_handoff`, T3, `services/connectors/src/tilo_connectors/handoff.py`), and Canva
declared but not activated (FR-CON-19, `config/canva.yaml`, waiting for the workspace owner's Canva app).

The owner, verbatim (16 Oct 2026, relayed): "use lovable for an intensive massive site, use tilo's own capability
for smaller websites, give the user an option to select from the connectors or mcp tools or choose native and then
ppt's and pdfs can be offered as an option to canva or tilo itself as well, that we aren't ruining options for the
user", and "This is my YES to the website output (ADR + contract change to allow a self-contained HTML deliverable,
sandboxed preview, no network, security review)."

## Decision

1. **The format (common 1.8.0).** `deliverable_format` gains `website`; `media_type` gains `text/html` for one case
   only. `app` stays the quiz. The Director's prompt says: a quiz or practice test is `app`, any other site is
   `website` (WEB-1).
2. **Who writes it and where it lives (artifact 1.2.0, AR-10, WS-01).** A native website is one self-contained HTML
   file of at most 524,288 bytes, written by the run's final `writer` unit (`unit_type` `deliver`, the unit that
   `tilo_harness.deliverable.render_format` already routes), stored as an ordinary artifact version (origin `unit`,
   versioned, hashed, redacted and screened like any text, AR-07). Code picks `text/html` from the role and the
   brief, never from the model. An upload, a fetch or a render never stores HTML (schema).
3. **Static checks, in code (WS-02 to WS-09).** Before the store keeps the bytes, a deterministic checker tokenises
   the file and refuses: anything over the cap or not UTF-8; `base`, `link`, frames, `object`, `embed`, `form`,
   `meta` other than charset and viewport; external or relative URLs in any URL attribute, `srcset` or CSS `url()`
   (only fragments and `data:` images, fonts and media pass); `@import`; script `src`, modules and `import`; network,
   navigation and eval-class names in scripts and handlers; and, as a separate raw scan, any `://`, `javascript:`,
   `data:text/html`, `<base` or `http-equiv`. A failure is a reason code the writer's retry gets (FR-AGT-13); a model
   never overrides it. The store's put runs the same checker for every `text/html` version, so no path stores
   unchecked HTML.
4. **Preview: an opaque origin with no network (WS-10 to WS-12).** Options weighed for Firebase Hosting plus Cloud
   Run in `asia-southeast1`:
   - `srcdoc`, `blob:` or `data:` frames in the web app: they inherit the app's CSP (`script-src 'self'`, no
     inline), so the site's own scripts never run, and loosening the app's CSP to fix that weakens all of Tilo.
     Refused.
   - A Cloud Storage bucket: objects cannot carry a CSP header, every bucket shares `storage.googleapis.com`, and
     the URL would carry a signed token. Refused.
   - A signed preview URL on tilo-api: needs one HMAC secret shared by every instance (a new Secret Manager secret
     and an infra apply) and puts a bearer-like token in request logs. Not chosen.
   - A dedicated host (a new Cloud Run service or a second Firebase Hosting site): the strongest separation, but new
     infra, IAM and deploys before 18 Oct; the isolation it adds over an opaque origin is small. Upgrade path
     (BQ-WEBSITE-1).
   - **Chosen: a fixed preview shell on tilo-api's own host**, which is already cross-site to the web app. The shell
     is static (no data, no token, no sign-in), sent with `Content-Security-Policy: sandbox allow-scripts;
     default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:;
     media-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'; worker-src 'none';
     object-src 'none'; manifest-src 'none'; frame-ancestors <web origins>` plus nosniff, `no-referrer`, `no-store`
     and an all-off `Permissions-Policy`. The CSP `sandbox` directive makes its origin opaque even when opened alone;
     the web app frames it with `sandbox="allow-scripts"` (never `allow-same-origin`, forms, popups, modals,
     downloads or top navigation). The web app reads the bytes through the owner-scoped result route with the
     person's bearer token, checks the SHA-256 against the version record, and posts the text once to the shell,
     which writes it into its own document, so the page keeps the shell's CSP and sandbox. No token is ever in a
     URL and no new secret or service is needed. The web app's CSP adds tilo-api's origin to `frame-src` only.
   - Residual risk: CSP cannot stop a frame from navigating itself, and a navigation can carry what the page shows
     in its URL. The checker refuses navigation APIs and external URLs (WS-05, WS-07) and the web app closes a frame
     that loads a second time (WS-12). What could leak is only what the page shows the person (BQ-WEBSITE-4).
5. **Download (WS-13).** The existing owner-scoped result route serves `text/html; charset=utf-8` with
   `Content-Disposition: attachment; filename="<title>.html"`, nosniff, `no-store` and the same CSP. The web app
   saves it from an `application/octet-stream` Blob and never makes a `text/html` blob URL (that would run in the
   app's own origin).
6. **Honesty (WS-14, HR-1).** The preview and the download are the stored version that `artifact.delivered` names,
   byte for byte; nothing is re-rendered or injected. `artifact.created` 1.2.0 carries `text/html` with the cap.
7. **Where a deliverable is made (common `make_with`, plan 1.2.0, `config/makers.yaml`, MK-01 to MK-08).**
   `make_with` is `native`, `connector:<id>` or `mcp:<server>:<tool>`. `config/makers.yaml` lists, per format, the
   partners after native: `website` -> Lovable (`build_handoff`), `pptx` and `pdf` -> Canva (`create_design`). The
   approaches reply carries one `make_choice` per such deliverable (native first, then partners, each `ready` or
   `needs_setup` with a note). A partner that is not set up is shown, never hidden, suggested or selected. "Large
   site" is a config rule over the brief text the person saw: more than `max_native_pages` (3) pages named, or a
   need one offline file cannot meet (sign-in, a database, payments; list in config). A large site's first ready
   partner is suggested and, with `preselect_suggested: true`, selected before Start; the person can switch back to
   native on the start plan. No model judges size or picks the maker. The brief contract is unchanged, so the
   Director's output schema never offers `make_with`.
8. **The pick (MK-06, MK-07).** Start carries the person's selection per deliverable; tilo-api accepts only an
   option it offered that is still ready, and records one `plan.maker_chosen` per deliverable with a choice (actor
   the person, registry 1.6.0, not a side effect) in the same save as the budget grant. A pick authorises nothing:
   Lovable's `build_handoff` and Canva's `create_design` stay T3 behind their own cards, outbox entries and
   `data.transfer` out, with only accepted requirements and granted data (FR-CON-16, FR-CON-20).
   `artifact.delivered` 1.1.0 carries `make_with`; a partner-made deliverable names that partner's outbox entry
   (EV-14), and a website always says where it was made.
9. **Canva and MCP today.** Canva shows as `needs_setup` ("Needs the workspace owner's Canva app") until its entry
   moves into `config/connectors.yaml` and the person connects it. `config/mcp.yaml` allowlists no server yet, so no
   MCP option shows; the contract and loader take one as soon as a reviewed server is listed (BQ-WEBSITE-6).
10. **Tilo's own MCP server (mcp_tools 1.1.0).** `read_artifact` never hands out HTML text: the schema now holds
    MC-07's type half (text only for Markdown, CSV and JSON).

## Consequences

- Positive: the timezone request becomes a native website, previewed safely and downloadable; large sites go to
  Lovable by the person's visible choice; decks and PDFs offer Canva without hiding Tilo; every choice is recorded.
- Negative: the checker refuses some legitimate pages (links out, `fetch` of a public API, a variable named `top`).
  A site that needs the network or several real pages belongs to Lovable, which the start plan offers.
- Compatibility: every bump is additive (common 1.8.0, artifact 1.2.0, plan 1.2.0, mcp_tools 1.1.0,
  artifact.created 1.2.0, artifact.delivered 1.1.0, registry 1.6.0; new makers 1.0.0 and plan.maker_chosen 1.0.0);
  every older valid fixture and config still validates. Four invalid fixtures used `text/html` as the never-allowed
  example: two now use SVG or the HTML cap, two stay invalid under the new rules (an HTML upload; HTML text over
  MCP); `test_FR_MEM_12` pins moved to floors.
- Ripples handled here: `tilo_planning.questions._FORMATS` and `deliverable_kinds.FORMATS` gain `website` (a test
  pins them to the contract). Until WEB-1 ships, a `website` deliverable falls back to the writer's Markdown output
  (`render_format` returns None), which is no worse than today's failure. The store and the harness keep refusing
  `text/html` until WEB-1 adds the checked path, so their existing tests stay green.
- Not done here: no service code, no web code, no config/connectors.yaml change, no firebase.json change.

## Tickets

Detail and line budgets in `agy-bridge/tasks/WEBSITE-TICKETS.md`: WEB-1 writer path and checker (security review),
WEB-2 preview shell and download (security review), WEB-3 Result panel component (security review), WEB-4a the
maker choice in tilo-api (approaches reply, approve body, `plan.maker_chosen`), WEB-4b the choice on the start plan,
WEB-5 the Lovable route for large sites (security review), WEB-6 the Canva option behind "needs setup".

## Questions (docs/open-questions.md)

BQ-WEBSITE-1 preview host, BQ-WEBSITE-2 the large-site thresholds, BQ-WEBSITE-3 preselecting the suggestion,
BQ-WEBSITE-4 the self-navigation residual risk, BQ-WEBSITE-5 the size cap, BQ-WEBSITE-6 MCP options, BQ-WEBSITE-7
who may preview in a team-shared world.
