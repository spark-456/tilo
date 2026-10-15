# CX-STUDIO-COPY

Checked the user-facing “not available yet” / “not available here yet” copy in Connectors, Agenda, Team and ContextPanel at base `03e254047548d8b1641a1c1de51d4aeceb86cd30`. Paths and fields below are from the current API handlers and schemas; “none found” means the relevant handlers/schema expose no matching field.

## Connectors

- [LiveConnectors.tsx:34](../../apps/web/src/park/pages/Connectors/LiveConnectors.tsx#L34), connect/reconnect: the API actions already exist: `POST /v1/connectors/connect` → `authorize_url`; `POST /v1/connectors/callback` → `connector`, `scope_lines`; `POST /v1/connectors/disconnect`. See `services/api/src/tilo_api/connect_routes.py:122-159`. The page has no corresponding controls yet.
- [LiveConnectors.tsx:56](../../apps/web/src/park/pages/Connectors/LiveConnectors.tsx#L56), connection state: `GET /v1/connectors` → `connectors[].state`, `connectors[].state_known` (`connectors_list.py:53-64,100-125`).
- [LiveConnectors.tsx:64](../../apps/web/src/park/pages/Connectors/LiveConnectors.tsx#L64), access level: `GET /v1/team` → `tools[].level` (`team_routes.py:143-156,265`). This is the workspace tool level; `/v1/connectors` itself has no access-level field.
- [LiveConnectors.tsx:65-66](../../apps/web/src/park/pages/Connectors/LiveConnectors.tsx#L65), usage and sync history: no per-connector usage or sync-history route/field found. `GET /costs` is an owner-level cost report, not a connector usage/history response (`costs.py:125+`).
- [LiveConnectors.tsx:68-74](../../apps/web/src/park/pages/Connectors/LiveConnectors.tsx#L68), granted scopes and grant expiry: `GET /v1/connectors` → `connectors[].scopes`, `connectors[].expires_at` (`connectors_list.py:53-64`). `expires_at` is derived grant expiry, and may be null.

## Agenda

- [AgendaPage.tsx:195-197](../../apps/web/src/park/pages/Agenda/AgendaPage.tsx#L195), week view: `GET /v1/plate` supplies `today`, `rows`, and `parked` only (`people.py:164-177`; `contracts/plate.schema.json:9-24`). No week-range/grid response found. `GET /v1/meetings` is a meeting list, not a week view.
- [AgendaPage.tsx:222-235](../../apps/web/src/park/pages/Agenda/AgendaPage.tsx#L222), Tilo’s brief: `GET /v1/meetings/{meeting_id}` → meeting `scheduled`, `agenda`, and `minutes` fields (`people.py:213-224`; `contracts/meeting.schema.json:70-80,139`). `GET /v1/meetings/{meeting_id}/minutes` also serves minutes. No prepared Tilo brief field found.
- Same line, Tilo-suggested times/focus blocks: no suggestion/availability-slot route or response field found. `GET /schedules` → `schedules[].next_due` serves routine due times only (`schedules.py:359-367,441-444`), not proposed meeting times or focus blocks.
- Same line, boards: `GET /v1/pinboards` → `items[]`, `truncated` (`people.py:512-520`; `people_pins.py:111-137`). The copy says pinboard items appear under Pinboards; the underlying data route exists.

## Team

- [LiveMembers.tsx:63-64](../../apps/web/src/park/pages/Team/LiveMembers.tsx#L63), backups and activity: no backup or last-activity field/route found. `GET /v1/people` serves directory fields only (`people_list.py:47-64`; `contracts/person.schema.json:21-89`); the Team mapper sets `dept` and `active` to null (`apps/web/src/park/api/live/teamFromPeople.ts:28-33`). `GET /v1/team` has `members`, `switches`, `tools`, `capabilities`, and `invites`, with no backup/activity field (`team_routes.py:143-156`).
- [Studio.tsx:63](../../apps/web/src/park/pages/Team/Studio.tsx#L63), backup coverage: no backup route/field found in `/v1/team` or `/v1/people` handlers/schema.
- [Studio.tsx:67](../../apps/web/src/park/pages/Team/Studio.tsx#L67), “Who helped Tilo learn”: `GET /v1/skills` serves `skills[]` (and optional `builtins[]`), but no learner/contributor attribution field or route was found (`skills_routes.py:309-329`).

## ContextPanel

- [ContextPanel.tsx:187](../../apps/web/src/park/shell/ContextPanel.tsx#L187), agent details and sources: no structured agent-detail/source-summary route found. `GET /worlds/{world_id}/events` returns `events[]` with event `actor`, `data`, and `trace` for recorded per-world evidence (`redaction.py:188-215`), but not an agent profile or source-summary field. `GET /v1/context` returns summarized worlds/work/meetings/pins/workspace, not agent details (`context_panel.py:37-44,190`).
- [ContextPanel.tsx:221](../../apps/web/src/park/shell/ContextPanel.tsx#L221), memory explanations: no memory explanation route/field found in the context handler; it returns no memory collection (`context_panel.py:37-44,190-192`).
- [ContextPanel.tsx:230](../../apps/web/src/park/shell/ContextPanel.tsx#L230), routine next-run times and forecasts: `GET /schedules` → `schedules[].next_due` can supply next routine due times (`schedules.py:359-367,441-444`). No forecast route/field found; `/v1/context.unavailable` explicitly lists both `routines` and `forecasts` (`context_panel.py:37-44,190`).
- [ContextPanel.tsx:233](../../apps/web/src/park/shell/ContextPanel.tsx#L233), knowledge items: no knowledge-item route/field found. `/v1/context.unavailable` includes `knowledge`; `GET /v1/skills` serves skills, not knowledge items (`context_panel.py:37-44,190`; `skills_routes.py:309-329`).
