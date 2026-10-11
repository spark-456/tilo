# ADR-0037: Per-user profile and notification preferences

- Status: Proposed; requires user acceptance before any contract or event change.
- Decider: user; author: CX-MEETBOT, 12 October 2026.
- Requirements: FR-SET-01/02, FR-HIL-13; 12 Oct 05:00 supervisor assignment.
- Sources: `docs/prd-supplement-design-2026-10-06.md` section 1.5;
  `docs/open-questions.md` BQ-SET-1..4; `contracts/person.schema.json`;
  `services/channels/src/tilo_channels/quiet_hours.py`.

## Problem

Profile Save currently retains name, email, title, time zone, language and working
hours on the device. Notification choices are page state; liveApi's `setPref` is
an in-memory map. These are not durable settings across devices.

The Person contract has `additionalProperties: false`: it covers directory identity,
contact details, time zone, preferred channel, roles and memberships. It cannot hold
profile presentation fields, five notification rows or quiet hours. A Person write
would also affect contact resolution and directory identity. The existing channels
`PreferenceReader` accepts quiet-hour mappings but defines no durable profile contract.
No new route, store field, contract or event is implemented by this proposal.

## Proposed document and boundary

Add a separate, versioned UserSettings contract, with strict unknown-field refusal:

```text
UserSettings {
  owner_id, org_id, version,
  profile: {name, email, title, time_zone, language, working_hours},
  notifications: {
    decisions: {phone, email, slack}, spend: {phone, email, slack},
    finished: {phone, email, slack}, digest: {phone, email, slack},
    weekly: {phone, email, slack}
  },
  quiet_hours: {enabled, start, end, timezone, threshold},
  updated_at
}
```

This is a proposed shape, not an accepted schema. The contract lane must specify
field lengths, email validation, IANA zone validation, HH:MM ranges, working-hours
representation and the threshold's currency/units before implementation. The current
UI threshold is a string; persisting an ambiguous amount as executable notification
policy would be unsafe. Profile email is display metadata only: it changes neither
sign-in identity, verified destinations, directory Person data nor connector grants.

Propose authenticated `GET /v1/me/settings` and `PUT /v1/me/settings`. Code derives
owner and org from the verified Principal; no caller-supplied target uid or org is
accepted. Every signed-in user owns their settings regardless of org role. Missing
settings return explicit unsaved defaults, never a claim of successful persistence.
The write validates the complete document atomically; version checks prevent a stale
device overwriting newer preferences. Invalid or conflicting writes change nothing.

Propose a dedicated SettingsStore with in-memory fake and durable server adapter,
keyed by verified org/user. Do not place settings in a generic People record, expose
them through context/team lists, or make browser Firestore writes. Durable wiring and
any access rules remain subject to the existing review process; this ADR does not
approve access policy or infrastructure changes.

## Invariants and existing behavior

- Decisions keep at least one selected channel. The server refuses all-false decisions
  even if a caller bypasses the UI guard. Saving a selection does not verify a channel
  or prove a message was delivered.
- Quiet hours never filter gates from cards or Needs you. Preserve the channels
  filter's existing `gate`/`blocked` bypass and in-app retention. The UI's phone
  threshold must not weaken that behavior; delivery semantics need an explicit
  reconciliation before threshold wiring.
- Preferences do not authorize sends, change outbox policy, grant consent, bind an
  address or start work. No sender is invoked by a settings read/write.
- Client saves report durable success only after the server acknowledges it. Failures
  retain the editable form and show an honest error. Device-only data may be offered
  for explicit save, never silently imported under a different authenticated uid.
- No new event is proposed here. If a settings audit event becomes required, submit
  its minimal metadata-only contract separately before emitting it. Profile content,
  email addresses and notification choices never go into world events or logs.

## Acceptance tests before implementation

Tests carry FR_SET_01 or FR_SET_02 and use fake stores/providers only:

1. Two signed-in users in one org read and update only their own settings; supplied
   owner/org fields and unknown fields are refused, and neither cross-user read nor
   write succeeds. Repeat across orgs and with no verified Principal.
2. A valid save survives a new client session through the same fake durable store.
   A failed or stale save preserves the prior document; the UI never claims success.
3. All-false decisions fail atomically; other rows may be all false. Malformed times,
   unknown zones, out-of-range fields and ambiguous threshold values are refused.
4. Quiet hours preserve gates/blocked in-app and the existing server notification
   bypass. Changing display email affects neither identity nor actual recipients.
5. liveApi reads/maps the accepted contract and awaits writes. An HTTP failure remains
   visible; billing, sessions and unrecorded delivery state retain unavailable states.

## Decision needed

Accept the separate UserSettings contract and the proposed owner-only route/store
boundary; assign the contract lane to pin validation, threshold semantics and any
required audit seam. Then implement the route and liveApi in small tests-first PRs
on phase0-stack. Until acceptance, Profile remains device-only and notification
choices remain session/page state.
