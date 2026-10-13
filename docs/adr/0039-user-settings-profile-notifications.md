# ADR-0039: Per-user profile and notification preferences

- Status: **Accepted by the user, 12 Oct 2026.** The contract lane's choices are the numbered decisions
  below. They are additive (a new contract, `user_settings.schema.json` 1.0.0) and the user may override any.
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
The route, store and client wiring are builder tickets after the contract PR.

## Document and boundary

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

The contract lane's choices for field lengths, email validation, IANA zone
validation, HH:MM ranges, working-hours representation and the threshold's
currency and units are decisions 2 to 6 below. The old UI threshold was a string;
persisting an ambiguous amount as executable notification policy would be unsafe, so
the string form is refused. Profile email is display metadata only: it changes neither
sign-in identity, verified destinations, directory Person data nor connector grants.

Authenticated `GET /v1/me/settings` and `PUT /v1/me/settings`. Code derives
owner and org from the verified Principal; no caller-supplied target uid or org is
accepted. Every signed-in user owns their settings regardless of org role. Missing
settings return explicit unsaved defaults, never a claim of successful persistence.
The write validates the complete document atomically; version checks prevent a stale
device overwriting newer preferences. Invalid or conflicting writes change nothing.

A dedicated SettingsStore with in-memory fake and durable server adapter,
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
- No new event is added. If a settings audit event becomes required, submit
  its minimal metadata-only contract separately before emitting it. Profile content,
  email addresses and notification choices never go into world events or logs.

## Acceptance tests for the builders

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

## Decision taken

The separate UserSettings contract and the owner-only route/store boundary are accepted. Until the
route lands, Profile stays device-only and notification choices stay page state.

## Decisions (contract lane, 12 Oct 2026)

The contract is `contracts/user_settings.schema.json` 1.0.0 (new; `$defs.update` is the `PUT` body,
generated as `UserSettingsUpdate`) with rules USET-01 to USET-08 in `contracts/user_settings.rules.md`.
No event, registry, config or other frozen schema changes.

1. **Shape as proposed, every object closed**: five fixed rows of three fixed channels; an unknown
   field is refused. `update` is the document without `owner_id`, `org_id` and `updated_at` (USET-01).
2. **Versions.** `version` is 0 to 1,000,000. 0 is the server's unsaved defaults with `updated_at` null;
   a stored document has `version` >= 1 and a time. A write is compare-and-set and a stale one is 409
   with nothing written (USET-02).
3. **Lengths and shapes.** `name` and `title` are one line of 1 to 80 characters (as
   `person.display_name`; `title` may be null). `email` is at most 254 characters, `a@b.c`, display
   only. `language` is a BCP 47 tag of at most 16 characters (`en-GB`); "English (UK)" stays the
   client's label. Zones have `person.time_zone`'s IANA shape and tilo-api also checks the zone
   database (USET-03). Clock values are `HH:MM`, 00:00 to 23:59.
4. **Working hours** are `{days, start, end}`: 1 to 7 distinct weekdays and a window in
   `profile.time_zone`, `start` before `end`, no overnight window (as `config/personal.yaml`
   `working_window`). The old one-line string is not stored.
5. **Quiet hours** are `{enabled, start, end, timezone, threshold}`, exactly what
   `tilo_channels.quiet_hours.parse_quiet_hours` reads. The window may cross midnight; `start` is never
   `end` (USET-03). No field could hide a gate (USET-05).
6. **Threshold.** `{amount_minor, currency}` or null: an integer from 1 to 1,000,000,000,000 in the
   currency's minor unit and an ISO 4217 code. The string form is refused, never parsed. No delivery code
   reads it in this release: a gate carries no structured amount and FR-HIL-13 lets only `gate` and
   `blocked` notify in quiet hours, so every gate keeps its bypass and in-app retention. Narrowing a push
   by it needs its own ADR and a typed amount on the gate.
7. **The two invariants are schema and crossref rules.** "Decisions never all off" is a `not` in the
   schema (`decision_channels`). "Quiet hours never hide a gate" is the closed `quiet_hours` shape plus a
   test that the stored block, read by the channels filter, still notifies `gate` and `blocked` with and
   without a threshold. Staleness, window order and length, and unknown zones are crossref cases.
8. **No audit event (USET-08).** A write writes no world event; profile text, addresses and choices never
   enter an event or a log. An audit trail later is a separate contract of ids and counts.

Questions logged: BQ-USET-1 to BQ-USET-3 in `docs/open-questions.md`.

## What builders do next

- Slice 1: `SettingsStore` (in-memory fake and durable adapter, keyed by org and user) and
  `GET`/`PUT /v1/me/settings` (USET-01 to USET-04), tests first from the fixtures and the reference check
  `_refusal` in `tests/contracts/test_FR_SET_01_02_user_settings_contract.py`. The unsaved defaults are
  the route's (code or config), not the contract's.
- Slice 2: `liveApi` reads, maps and awaits `PUT`; the channels `PreferenceReader` reads `quiet_hours`,
  never `threshold`. The web copy "Phone stays silent, except decisions over X" overstates it (BQ-USET-3).
