# Canva decks and documents — public API these tests pin (FR-CON-19)

PRD supplement 2026-10-05 s6, SD-03. Tests: `test_FR_CON_19_canva.py`; doubles in `_canva_lib.py` (a fake Canva
API, a token seam; no network, no real Canva). Canva is declared in `config/canva.yaml` (one
`connector.schema.json` entry) and is NOT yet in `config/connectors.yaml`: moving the entry there is the activation
step once the workspace owner registers a Canva app (BQ-CON19-2).

## `tilo_connectors.canva` (pure, no network, no model)

- `canva_status(environ=None) -> {"connector", "state", "message"}`: `needs_setup` with the message
  `Needs the workspace owner's Canva app` unless `CANVA_OAUTH_CLIENT_ID` and `CANVA_OAUTH_CLIENT_SECRET` are both set
  (then `ready_to_connect`); no value is ever echoed.
- `prepare_design(...) -> PreparedDesign` (`document`, `document_bytes`, `assets`, `exact`): the request document.
  Refusals are `HandoffRefused` with a rule id: `CV-01` content not approved by the world's owner, `CV-02` content
  is not clean, intact text (or an asset not a clean png/jpeg), `CV-03` the redactor changed it or the safety screen
  flagged it, `CV-04` bad shape (kind, format, template id, counts), `DG-03` grant not active, `DG-02` asset not an
  item of the grant (checked before the asset is read).
- `design_gate(prepared, item, table=)` and `share_gate(export_ref, recipients, table=)`: the fields the card and the
  outbox entry copy. The tier is `table.tier_of(action, modifiers)`: granted assets are `attachments` (T3), a share
  is `external_sharing` + `new_recipients` (T3).
- `CanvaApi` protocol: `capabilities`, `upload_asset`, `create_design`, `autofill`, `export`, `share`.
  `CanvaApiError(status)` carries the HTTP status only.

## `tilo_connectors.adapters.canva`

- `CanvaAdapter(declaration, api, tokens, artifacts, exports, grants, owner_of, risk_table=None, enabled=False)`.
  `execute_side_effect(entry, grant)` runs only with the outbox's grant (`MissingGrant` first), is off unless
  `enabled`, recomputes the tier from the risk table, and re-checks every approved text and granted asset against the
  sha256 recorded at approval and the grant before each upload (a revoke mid-task stops later uploads).
- `create_design`: autofill when `brand_template_id` is set and Canva's `capabilities` include `autofill`; plain
  creation when not, or when Canva answers 402/403/404 to the plan check or the autofill (no error). The export is
  checked (magic bytes, size) and stored through `ExportStore.put` with `provenance` (partner, route, design id,
  outbox id, authz, parents = approved content + granted assets, origin unit and agent). A design is made at most
  once per entry; a retry after a failed export only repeats the export.
- `share_design`: only a design Tilo exported (`ExportStore.get`), recipients required, `external_sharing` and
  `new_recipients` required, T3; at most once.
- The token is `tokens.access_token_for_adapter(user, "canva", required_scopes=..., not_before=authz.at)`; a
  `NotConnected` waits for the person (no API call). Tilo never takes, types or stores a password.
