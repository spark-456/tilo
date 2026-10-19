# Agenda: designed but not in the PRD (WEB-9)

Every element below is built as designed on the typed fixtures (`park/api/fixtures/agenda.ts`, read through
`Api.getAgenda()`). The live Api rejects with `NotBuilt` until the endpoint exists, and the page then shows
"Not connected yet". AG-WEB folds these rows into plan section 8b.

| Element | Fixture source | Status |
| --- | --- | --- |
| Header sync pill "Google Calendar · synced just now" | none (copy only) | Built, static. No calendar sync status in any contract |
| Find a time (header button and the "Find a time" suggestion pin): banner "K1 Level 3 gate review · 30 min · Alex, Jin, Priya, Tom", three dashed slots, Cancel | `agenda.slots` | Built. Booking calls `Api.bookSlot(slot)`, adds a hero-filled event, posts the "K1 gate review booked" pin, toasts; a second press toasts "Already booked for ...". No availability or invite endpoint backs it |
| Team board and My board, Pinboard (cork, sticky notes) and Grouped (TILO SUGGESTS, NEEDS SOMEONE, THIS WEEK, DONE) styles | `agenda.pins` | Built. Pins added, checked off, dismissed and blocked live in page state only; nothing is written back |
| Tilo suggestions: "Block it" turns a pin into "Focus time" and toasts "Blocked 09:30–11:30 on Monday in Google Calendar"; "Not now" dismisses | `agenda.pins` (`suggested`, `kind`) | Built, page state only. No calendar write exists |
| Laptop Depot pin follows `dec.depot` ("Review and approve" opens the K1 world, then "Approved · £3,420 · K1 electric scooter", Done) | `agenda.pins[dec=depot]`, `app.dec` | Built. Navigation through `app.go("world", { id: "k1" })`; the approval itself is `app.decide("depot")` elsewhere |
| "Pin something..." (Enter or Pin it) adds a note with "Added just now" | none (page state) | Built, page state only. No pin store or API |
| Calendar chips Work, Personal, Tilo and the Weekend toggle (5 or 7 days) | `agenda.events`, `agenda.days`, `agenda.wkend` | Built. Day load ("3 events · 2.8 h") and the red now line at 09:12 are computed from the fixture; "16 events ... Tilo joins 4 still to come" follows the filters |
| Event detail panel: calendar, title, time, attendee avatars, Tilo face | `agenda.details`, `agenda.events` | Built. Attendee initials are the prototype's colour map |
| TILO'S BRIEF, "Ask Tilo for a brief" (toast "Tilo will brief you 15 minutes before ...", "Queued · arrives 15 min before") | `agenda.details[].brief`, `briefMeta` | Built. The brief text is fixture copy; nothing queues a brief |
| NOTES BY TILO and FOLLOW-UPS on past events | `agenda.details[].notes`, `actions` | Built, read only |
| Switches "Tilo joins and takes notes", "Turn action items into pins", "Brief before it starts" (toast "Tilo will join ...") | none (page state) | Built, page state only. No per-event preference store |
| The gate brief line "Laptop Depot budget is still waiting for sign-off." / "... was approved today." in the booked K1 gate review | `app.dec.depot` | Built. Page-produced copy from `dec`, as in the prototype |
