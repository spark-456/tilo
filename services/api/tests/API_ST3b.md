# `tilo_api.cards` — public API these tests pin

Ticket ST-3b (session ST). Module `tilo_api.cards`, package `tilo-api` (`services/api`).
API side of cards and batching (FR-HIL-01, FR-HIL-02; PRD 10.2, 10.3, 10.6, 9.5, FR-INT-09).
This file is the contract the builder implements exactly; the tests in this directory import
only what is listed here. No business logic lives in the tests — this is the shape the builder
is held to. Rendering a card in world/HUD/Story is SW's job, out of scope here.

Kept in a new module family so this ticket never touches `services/api/tests/_api_lib.py`,
`test_FR_HIL_07_*`, `test_FR_HIL_09_*` or `API_ST3a.md` (owned by a parallel ticket).

## Round 2 (issue #32 review findings): this section supersedes the shapes and ambiguities below

- **Identity.** `answer(world_id, card_id, *, option, channel, principal, pin_verified=False)` and
  `list_for_world(world_id, *, principal)` take the verified `deps.Principal`; `actor` and `as_user`
  are gone and the HTTP body forbids extra fields (a body naming an actor is a 422). Roles follow
  PRD 10.1: the owner answers everything; a Viewer gets 403 (also on GET); a Team Lead sees and
  answers needs_you and meeting cards of their `districts` only (a gate needs `open_gate`'s lead
  record and policy, so it is 403 here); an Approver sees and answers assigned cards, not consent.
  A card outside the principal's scope is 404 (no existence oracle); a refusal writes nothing and
  leaves the card open.
- **Companion data.** `submit(card, *, outbox_id=None, district=None, assignee=None)`: `district`
  (card.schema.json has none; none means owner-only) and `assignee` (the Approver the owner assigned,
  `approval.requested` approver.user) are data the harness holds. District and assignee are part of
  the merge key, so a merge never crosses a visibility scope.
- **Channel and PIN.** The route accepts `channel` other than web/mobile_web and `pin_verified` only
  when `cards.get_channels_caller()` is true (an authenticated tilo-channels call; false until
  service auth lands), else 403 `channel_not_permitted`.
- **submit** is idempotent: identical content returns the first result and changes nothing; a
  different card under a used id is rejected; a resolved record is never reopened. CR-01 (safe
  default names an option), CR-02 (unique option ids), a real calendar `created_at` and a
  representable deadline are validator rules.
- **Merging** keeps every card as its own record (own question and options); a group lists as its
  first open member and one answer or one timeout closes the whole group with one part (BQ-72).
- **Part scope (SEC-07):** every part carries `world_id`, `card_id`, `district`, `vis` ([district], or
  None with `owner_only` True when the card has no district; never "all", BQ-73). A Team Lead's
  question answer is `answered_by` "team_lead"; an unknown role is refused like a Viewer.
- **One resolution per card:** answer and timeout claim the group under a lock before `writer.write`
  and release the claim if the write raises, so racing answers or an answer racing tick write one part.
- **Gate answers (CR-07, PI-02):** only `approve` writes `approval.resolved` and resolves; `edit` and
  `hold` write nothing and leave the gate open. **Consent (CR-13):** `connect` writes
  `connection.consented` (authz by the person); `hold` writes nothing.
- **Timeouts (supersedes ambiguity 5):** each open card times out at its own `created_at + timeout`.
  A needs_you or meeting card writes `question.answered` (default, nudge) and resolves. A gate or
  consent card stays open and writes one `alert.raised` (severity nudge, its own derived `alert_id`,
  `card_id` = the card's id), because `question.answered` would close the card on every channel.

## Ambiguities resolved (root CLAUDE.md: PRD default, logged here, keep going)

1. **District.** `card.schema.json` carries no `district` field (only `header.building`), and
   resolving a building to its district needs the world's `layout.schema.json` record, which is
   out of scope for a card store. FR-HIL-02's "one district" is approximated at this layer by
   `header.building`: two cards from the same building are certainly from the same district, and
   every merge/no-merge fixture pair used below shares (or differs on) `header.building`
   accordingly. A later ticket that resolves buildings to districts through the layout may widen
   this; it only makes merging more permissive, never less, so no test here breaks.
2. **"Same-type" (10.3).** Taken as `card["kind"]` (`needs_you` | `gate` | `consent` | `meeting`),
   since that is card.schema.json's own discriminator and the one PRD 10.2's table itself keys
   the escalation ladder on.
3. **Merge window anchor.** "Three cards ... in 60 s" and "61 s apart" are read as measured from
   the *first* card's `created_at` in a merge group (not from each new submission, which would
   let a slow trickle merge forever, and not from the clock, which would make `submit` depend on
   wall-clock timing tests cannot control). `submit` is otherwise clock-free; only `tick` reads
   the injected `Clock`.
4. **`outbox_id` on gate cards.** `card.schema.json#/$defs/gate` has no `outbox_id`, but
   `approval.resolved.schema.json` requires one, and PRD 8.5/`card.rules.md` CR-12 say it is the
   id `approval.requested` reserved when the gate was raised. `CardStore.submit` therefore takes
   `outbox_id` as a companion argument, required (and ulid-shaped) exactly when `kind == "gate"`,
   never supplied otherwise. This is data the harness already has (it wrote `approval.requested`)
   and is not invented here.
5. **PI-03's Nudge for gates/consent.** `docs/security/p4-policy-invariants.md` PI-03 says a
   gate's timeout "emits no `approval.resolved`, and a default answer is posted as a Nudge" —
   naming a Nudge in the same breath it forbids `approval.resolved`. Read together with BQ-04
   (`question.answered`, `answered_by: "default"`, severity `nudge`) and the registry's own
   `question.answered` HUD effect ("The question card closes on every channel" — no kind
   restriction), a timeout emits `question.answered`/`default`/`nudge` for **every** card kind,
   including gate and consent; only the kind-specific side-effect event (`approval.resolved` /
   `connection.consented`) is withheld for gate/consent, and their record stays `open` ("held"),
   never `resolved`, so a person can still answer it later. `tick` nudges a still-open gate or
   consent card at most once (an internal `nudged` flag), so repeated `tick` calls do not spam
   Nudges while it waits.
6. **HTTP surface.** The ticket names `cards.submit(card)` as a plain call and lists only
   `GET /worlds/{id}/cards` and `POST /worlds/{id}/cards/{card_id}/answer` as routes. `submit`
   and `tick` are therefore plain `CardStore` methods (the harness/scheduler calls them
   in-process); they are not exposed over HTTP by this ticket.
7. **Gate/consent answerer authorisation.** Deciding *who* may open a gate (owner / assigned
   Approver / Team Lead, `docs/security/p4-policy-invariants.md` PI-02) is `packages/policy`'s
   `open_gate` (ticket P4-01), not this card layer. This ticket's `answer` only checks the option
   is one the card offers and the channel is one `answer_channels` allows (which structurally
   enforces PI-04, since a gate's `answer_channels` never include `email` and a consent card's
   never include `whatsapp`/`email` — see card.schema.json's `if`/`then` branches), then records
   the answering person's own `authz` on the emitted event part. Whether that `authz` actually
   satisfies PI-02 is decided downstream, out of scope here.
8. **"For the owner" (GET).** `CardStore` is constructed with a `world_owners: dict[world_id,
   user_id]` map (a stand-in for the world record). `GET /worlds/{id}/cards` takes `as_user` and
   the store raises `PermissionError` — the router turns that into `403` — when `as_user` is not
   that world's owner. Full role/redaction scoping (Team Lead districts, Viewer scope) is
   FR-HIL-09, a separate ticket already excluded from this one.

## Shapes

```python
from typing import Protocol


class Clock(Protocol):
    def now(self) -> str: ...  # RFC 3339, common.schema.json#/$defs/timestamp


class EventWriter(Protocol):
    def write(self, part: dict) -> None: ...

    """Same idea as ST-3a's EventWriter: the API never stamps id/seq/ts/run_id (PI-18) — it
    hands the harness-owned writer an unstamped part, a plain dict with keys "type" (str),
    "data" (dict, matching contracts/events/data/<type>.schema.json), "authz" (dict | None) and
    optionally "severity" (str, overriding the registry's default_severity — needed for BQ-04's
    question.answered/default which is "nudge" where the type's own default is "info")."""


@dataclass(frozen=True)
class SubmitResult:
    outcome: str  # "accepted" | "merged" | "rejected"
    card_id: str | None  # the stored (or merged-into) card's id; None when rejected
    errors: tuple[str, ...]  # jsonschema messages; empty unless outcome == "rejected"


@dataclass(frozen=True)
class AnswerResult:
    outcome: str  # "answered" | "rejected"
    reason: str | None
    # None on success, else one of: "card_not_found", "already_resolved",
    # "invalid_option", "invalid_channel", "pin_required"
    emitted: tuple[dict, ...]  # unstamped parts written (via EventWriter); empty on rejection


@dataclass(frozen=True)
class TimeoutResult:
    card_id: str
    kind: str
    held: bool  # True for a gate/consent card that stayed open; False once resolved to default


class CardStore:
    def __init__(
        self,
        *,
        clock: Clock,
        writer: EventWriter,
        world_owners: dict[str, str] | None = None,
        merge_window_s: int = 60,
    ) -> None: ...

    def submit(self, card: dict, *, outbox_id: str | None = None) -> SubmitResult:
        """Validates `card` against contracts/card.schema.json (2020-12, with
        contracts/common.schema.json resolved). Invalid -> SubmitResult("rejected", None, errors).
        Valid, kind == "gate": outbox_id required (ulid); else rejected. Valid, kind != "gate":
        outbox_id must be None; else rejected.
        Valid, kind in {"gate", "consent"}: always stored as its own new record — never merged
        (each is its own authorisation) -> SubmitResult("accepted", card["id"], ()).
        Valid, kind in {"needs_you", "meeting"}: if an *open* record of the same world, same
        kind and same header.building exists whose group anchor created_at is within
        merge_window_s (default 60) seconds of this card's created_at, this card merges into it
        (its id is recorded, nothing new is stored) -> SubmitResult("merged", <existing card
        id>, ()). Otherwise stored as a new record -> SubmitResult("accepted", card["id"], ())."""

    def get(self, world_id: str, card_id: str) -> dict | None:
        """The stored card.schema.json dict (the group's original card, for a merged group), or
        None. Looks up by the *submitted* card_id too, so a merged card's own id still resolves
        to the record it merged into."""

    def list_for_world(self, world_id: str, *, as_user: str) -> list[dict]:
        """Every open or held card.schema.json dict for world_id, oldest first. Raises
        PermissionError when as_user != world_owners[world_id] (or the world is unknown)."""

    def answer(
        self,
        world_id: str,
        card_id: str,
        *,
        option: str,
        channel: str,
        actor: str,
        pin_verified: bool = False,
    ) -> AnswerResult:
        """`option` must be one of the stored card's options[].id, else "invalid_option".
        `channel` must be in the stored card's answer_channels, else "invalid_channel" — this is
        the whole of PI-04 (structural: a gate card's answer_channels schema-excludes email, a
        consent card's excludes whatsapp and email). When the card's kind is "gate" and its
        gate.risk_tier == "T3" and channel == "whatsapp", pin_verified must be true (SEC-06),
        else "pin_required". A card that is not open (already answered, or a non-gate/consent
        card already resolved by timeout) -> "already_resolved". Unknown card -> "card_not_found".
        On success: writes {"type": "question.answered", "data": {"answered_by": "person"},
        "authz": None} for a needs_you/meeting card (closing it, chosen option = `option`);
        writes {"type": "approval.resolved", "data": {"gate_id": ..., "card_id": ...,
        "outbox_id": ..., "option": option, "channel": channel, "pin_verified": pin_verified},
        "authz": {"by": "person", "ref": actor, "at": clock.now()}} for a gate card (only
        `option == "approve"` closes/resolves the record; "edit"/"hold" still emit the part but
        leave the record open, so it can be answered again); a consent card behaves like a gate
        card but this ticket does not exercise its own side-effect event (`connection.consented`
        is FR-HIL-08/token-broker territory, out of scope). Returns AnswerResult("answered",
        None, (<parts written>,))."""

    def tick(self) -> list[TimeoutResult]:
        """Reads clock.now(). For every open record whose group anchor created_at + card.timeout
        seconds <= now and that has not already been nudged: writes {"type": "question.answered",
        "data": {"answered_by": "default"}, "authz": None, "severity": "nudge"} (BQ-04). A
        needs_you/meeting record then resolves to its safe_default option (TimeoutResult.held =
        False). A gate/consent record stays open — marked nudged so it is not nudged again —
        never resolved and never emits approval.resolved/connection.consented (PI-03;
        TimeoutResult.held = True)."""


def build_router(store: CardStore) -> "fastapi.APIRouter":
    """GET /worlds/{world_id}/cards?as_user=<user_id> -> 200 [card, ...] | 403 (PermissionError).
    POST /worlds/{world_id}/cards/{card_id}/answer, body {"option", "channel", "actor",
    "pin_verified"?} -> 200 {"outcome": "answered"} | 404 (card_not_found) | 400
    {"outcome": "rejected", "reason": ...} for every other AnswerResult rejection reason."""
```

## Fixtures used

`contracts/fixtures/card/valid/*.json` and `contracts/fixtures/card/invalid/*.json` (every file,
by name, so a new fixture is picked up automatically). `card.schema.json`'s own `$ref`s to
`common.schema.json` are resolved with a `referencing.Registry` built the same way
`tests/contracts/_lib.py` does (kept as an independent copy in `_cards_lib.py` per this
ticket's "never import from conftest / other test dirs" instruction — not a second source of
truth, just the same small loader duplicated so this ticket's tests do not reach across worktree
boundaries into files owned by a parallel ticket).
