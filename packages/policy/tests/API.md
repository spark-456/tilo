# `tilo_policy` — public API these tests pin

Ticket P4-01. Package `packages/policy`, import name `tilo_policy`, dist name `tilo-policy`.
Deterministic policy engine (PRD 10.4, `docs/security/p4-policy-invariants.md` PI-01..PI-17).
This file is the contract the builder implements exactly; the tests in this directory import
only what is listed here. Nothing here is business logic — it is the shape tests hold the
builder to.

## Errors

```python
class PolicyConfigError(Exception):
    """Raised by load_risk_table on a missing or schema-invalid risk table file (fail closed)."""
```

## Risk tiers

```python
def load_risk_table(path: str | os.PathLike | None = None) -> RiskTable:
    """Reads YAML (JSON is valid YAML) at `path`, default `config/autonomy.yaml` (not in the
    repo yet, spark-456/tilo#1 — tests always pass an explicit fixture path), validates it
    against contracts/policy.schema.json#/$defs/risk_tier_table, and raises
    PolicyConfigError if the file is missing or fails that schema. Never returns a partial
    table."""


@dataclass(frozen=True)
class RiskTable:
    actions: dict[str, str]  # action_type -> "T1" | "T2" | "T3", from $defs.actions
    modifiers: tuple[str, ...]  # the six tier_condition names, from $defs.modifiers
    max_level: dict[str, str]  # {"T1": ..., "T2": ..., "T3": "L1"}, from $defs.max_level

    def assess(self, action_type: str, facts: "SideEffectFacts") -> "Assessment":
        """Deterministic. modifiers = the subset of the six SideEffectFacts flags below that are
        true for this call, in table order. tier = "T3" if modifiers is non-empty, else the
        table's base tier for action_type. An action_type absent from `actions` is fail-closed
        T3 with modifiers=() (unknown action type, PI-07's "fail closed" reading extended to
        assess() itself, not just decide())."""


@dataclass(frozen=True)
class Assessment:
    tier: str  # "T1" | "T2" | "T3"
    modifiers: tuple[str, ...]  # e.g. ("new_recipients", "attachments"); () when none apply
```

## Side effect facts

```python
@dataclass(frozen=True)
class SideEffectFacts:
    recipients: tuple[str, ...] = ()  # every recipient address of the proposed action
    known_recipients: tuple[str, ...] = ()  # addresses the thread/contact list already has
    attachments: tuple[Any, ...] = ()  # non-empty => "attachments" modifier
    external_share: bool = False  # => "external_sharing" modifier
    deletion: bool = False  # => "deletion" modifier
    money_or_legal: bool = False  # => "money_or_legal" modifier
    safety_flags: bool = False  # => "safety_flag" modifier

    @property
    def new_recipients(self) -> tuple[str, ...]:
        """recipients not in known_recipients (order preserved, PRD 10.4 T3 "new recipients").
        Non-empty => "new_recipients" modifier."""
```

Ambiguity resolved (PRD 10.4 table; ticket text lists "recipients/facts" together): `Proposal`
carries no separate `recipients` field — recipients live only in `proposal.facts.recipients`,
and policy scope (`scope.recipients` / `scope.domains`) is checked against those. Noted for the
builder; not a new requirement.

## Proposal / Decision

```python
@dataclass(frozen=True)
class Proposal:
    world_id: str
    action_type: str
    connector: str
    district: str
    destination: str | None
    facts: SideEffectFacts
    item: dict | None  # artifact_ref shape ({"artifact_id": ..., "version": ...}) or None
    credits: float
    instruction: dict | None  # the whole event dict (type/authz/data) the proposal cites, or None


@dataclass(frozen=True)
class Decision:
    outcome: str  # "gate" | "run_after_undo" | "run" | "draft_only"
    tier: str  # "T1" | "T2" | "T3", from RiskTable.assess
    modifiers: tuple[str, ...]
    level: str  # the autonomy level in force for this decision: "L0".."L3"
    # (T3 and "no covering policy" both report "L1", since that is the
    # level whose rule — "ask each time" — governs them)
    policy_id: str | None  # the covering policy's id on the policy path, else None
    authz: dict | None  # {"by": "policy", "ref": policy_id, "at": now} on a policy run path,
    # None on "gate" and "draft_only" (a gate authorises nothing, PI-01)
    undo_window_s: int | None  # set (>=1) only for "run_after_undo"; else None
    scheduled_at: str | None  # set only for "run_after_undo": now + undo_window_s; else None
    reason: str  # a stable short code, see "Reason codes" below


def decide(
    proposal: Proposal,
    *,
    table: RiskTable,
    policies: list[dict],  # policy.schema.json records (plain dicts)
    world_owner: str,
    applied: list[dict],  # earlier policy.applied parts under the owner's policies, every world; see "applied shape"
    now: str,  # RFC 3339 timestamp, common.schema.json#/$defs/timestamp
) -> Decision:
    """Deterministic; same arguments always give an equal Decision (dataclass equality).
    A model is never consulted and the clock is never read internally — `now` is the only
    source of time.

    1. tier, modifiers = table.assess(proposal.action_type, proposal.facts).
    2. tier == "T3" => outcome "gate", level "L1", policy_id None, authz None,
       reason "t3_always_gates" (PI-07). This is unconditional: no policy, however permissive,
       changes it.
    3. Otherwise, find every policy in `policies` that "covers" the proposal (below). If none
       covers it, or the covering one's level in force at `now` is "L0" or "L1": outcome
       "gate", level = that level ("L1" when no covering policy exists at all), policy_id =
       the covering policy's id if there is one at L0/L1 else None, authz None, reason
       "no_covering_policy" (level None/L1) or "l0_draft_only_is_not_a_gate" is NOT used here —
       L0 is handled in the next step, this step only covers "no covering policy" and "L1".
    4. Several covering policies: the LOWEST level in force wins (fail safe) before step 3/5/6
       are applied — i.e. covers/level-selection first picks the policy (if any) whose level in
       force at `now` is lowest; ties broken by `policy_id` ascending (deterministic).
    5. Covering policy at L0: outcome "draft_only", policy_id set, authz None, reason
       "l0_draft_only" (nothing leaves Tilo).
    6. Covering policy at L2: needs the owner's own, unused, earlier instruction for this exact
       destination (PI-08/09/10 below). Missing/invalid/reused instruction => outcome "gate",
       reason "l2_instruction_required" (same policy_id, since it "covers" the type/scope but
       not this particular send). Otherwise outcome "run_after_undo", undo_window_s =
       policy["undo_window_s"] (>= 1; the policy schema's default is 60), scheduled_at = now +
       undo_window_s seconds, authz {"by": "policy", "ref": policy_id, "at": now}, reason
       "l2_run_after_undo".
    7. Covering policy at L3: within `limits.per_day` and `limits.credits` (PI-11, "applied
       shape" below) => outcome "run", authz {"by": "policy", "ref": policy_id, "at": now},
       undo_window_s None, scheduled_at None, reason "l3_run". Over either limit => outcome
       "gate", reason "l3_daily_cap_reached" or "l3_credits_cap_reached" (credits checked only
       when per_day is not itself already exceeded).

    "Covers" (PI-06, mirrors tests/contracts/test_FR_WLD_03_outbox_crossref.py's
    `_policy_covers`): policy["action_type"] == proposal.action_type; policy["owner"] ==
    world_owner; every stamp (created_by, changed_by, each history entry) has "by" ==
    policy["owner"] (PI-13, "made by owner"); policy["created_by"]["at"] <= now; expiry is
    None or now < expiry; proposal.connector in scope["connectors"]; district in
    scope["districts"] (empty = unrestricted); every proposal.facts.recipients entry in
    scope["recipients"] AND its domain (text after "@", lower-cased) in scope["domains"]
    (both empty-list-is-unrestricted, same rule applied per PI-06); the level in force at
    `now` (PI-13: the last history entry at or before `now`; a record whose history is out of
    order, empty, or whose current `level` disagrees with its last entry, covers nothing —
    same as `_level_at` in the reference check) is not None.

    "applied shape" (PI-10, PI-11): each item of `applied` is a policy.applied part
    `{"type": "policy.applied", "authz": {"by": "policy", "ref": <policy_id>, "at": <ts>},
      "data": <policy.applied data, includes policy_id, instruction_id and credits>}`.
    Daily cap counts entries whose `data["policy_id"]` equals the covering policy's id and whose
    `authz["at"]` falls on the same UTC calendar date (the `YYYY-MM-DD` prefix) as `now`,
    the proposal's own pending send included (so `len(matching) + 1 <= limits["per_day"]` when
    per_day is not null); credits cap sums `data["credits"]` over the same matching entries plus
    `proposal.credits`, checked against `limits["credits"]` the same way. Instruction reuse
    (PI-10) checks the *whole* `applied` list of the world (not filtered to this policy_id):
    no entry's `data["instruction_id"]` may equal the instruction being used.
    """
```

### L2 instruction check (PI-08, PI-09, PI-10, PI-12)

While `coverage.L2_ACTION_RECORDED` is False (until ADR-0013 lands; BQ-57, PI-21), `decide` counts no
instruction at all: every L2-covered send gates with reason `l2_instruction_required`. The OB-01
validator keeps `instruction_counts`. Once the flag is True, `proposal.instruction` counts only when all of:
- it is not None and its `type` is `"world.requested"` with `data["channel"]` in
  `("web", "mobile_web")`, or `"channel.message_in"` with `data["channel"] == "whatsapp"`
  (never `"email"`, whoever `actor` is — PI-09);
- `instruction["world_id"] == proposal.world_id` (or `instruction["data"]["world_id"]` — tests
  set both the same, see conftest factories) and `instruction["actor"] == policy["owner"]`;
- `instruction["ts"] < now` (strictly earlier);
- `instruction["data"]["destination"] == proposal.destination` and `proposal.destination` is
  not None;
- no entry in `applied` (every world the caller passes) has `data["instruction_id"] == instruction["id"]`
  already (PI-10: an instruction opens at most one entry, cancelled sends included).

`undo_window_s` at L2 is always `policy["undo_window_s"]`, which the policy schema requires
`>= 1` when `level` is L2 (the FR-HIL-05 default is 60). `scheduled_at` is `now` plus that many
seconds, formatted the same way as `now` (RFC 3339, `...Z`, millisecond precision).

## Gate opening

```python
def open_gate(
    reserved: dict,  # the approval.requested event ({"type", "authz": None, "data"})
    resolved: dict | None,  # the approval.resolved event, or None (never answered)
    *,
    world_owner: str,
    team_lead: dict | None = None,  # team_lead.schema.json record, when resolved's authz.by
    # is "team_lead"
    policy: dict | None = None,  # the policy.schema.json record reserved["data"]["team_lead"]
    # names, when a Team Lead answered
) -> Decision:
    """PI-02, PI-03: only `resolved["data"]["option"] == "approve"` from someone allowed to open
    THIS gate (same gate_id/card_id/outbox_id as `reserved`) yields outcome "run"; `edit`,
    `hold`, `resolved is None`, or an answer from anyone else yields "gate". Never delegated to
    the Director: an authz `by` outside {"person", "team_lead"} is never accepted (PI-03) — this
    is structural, since approval.resolved's registry entry only allows authz_by
    ["person", "team_lead"] (a caller passing anything else gets "gate", reason
    "gate_not_opened").

    Allowed answerers (PRD 10.1, mirrors `_may_answer` in
    tests/contracts/test_FR_WLD_03_outbox_crossref.py):
    - authz["by"] == "person": authz["ref"] is world_owner, or reserved["data"]["approver"]["user"]
      when that assignment's `assigned_by` is the world_owner at or before authz["at"] (ADR-0006).
    - authz["by"] == "team_lead": reserved["data"]["team_lead"] is not None, and `team_lead` and
      `policy` are given and consistent — team_lead["id"] == authz["ref"], team_lead["domain"]
      == reserved["data"]["team_lead"]["domain"], team_lead["assigned_by"]["by"] == world_owner,
      team_lead["assigned_by"]["at"] <= authz["at"]; policy["id"] ==
      reserved["data"]["team_lead"]["policy_id"], policy["owner"] == world_owner, every policy
      stamp is the owner's (as in `decide`'s "covers"), policy["action_type"] ==
      reserved["data"]["action_type"], reserved["data"]["team_lead"]["domain"] in
      policy["team_lead_domains"], policy["created_by"]["at"] <= authz["at"], and
      policy["expiry"] is None or authz["at"] < policy["expiry"].
    - SEC-06: when reserved["data"]["risk_tier"] == "T3" and resolved["data"]["channel"] ==
      "whatsapp", resolved["data"]["pin_verified"] must be true, whoever answered.

    On "run": tier = reserved["data"]["risk_tier"]; modifiers = () (approval.requested carries
    no modifier list — only the outbox entry does, out of scope for this event pair);
    level = "L1"; policy_id = None (a gate's authz is a person or Team Lead, never a policy —
    PI-16 forbids stamping it as one even when a policy named the Team Lead allowance);
    authz = resolved["authz"] unchanged (PI-02: "the entry's authz is that event's"); undo_window_s
    = 0; scheduled_at = None; reason = "gate_approved".
    On "gate": tier/modifiers as above, level "L1", policy_id None, authz None, undo_window_s
    None, scheduled_at None, reason "gate_not_opened".
    """
```

## Crossref check (reference-equivalent verdict)

```python
def check_entry(case: dict, table: RiskTable | None = None) -> str | None:
    """`case` is one contracts/fixtures/outbox/crossref/{valid,invalid}/*.json file, already
    loaded (keys: rule, note, entry, reserved_by, authorised_by, policy, team_lead, world_owner,
    instruction, earlier_applied, transfer — see contracts/outbox.rules.md). Returns None when
    the case is valid, else the OB-01 or OB-05 rule the entry breaks — built from the same
    `decide`/`open_gate` coverage and stamping logic above (not a second implementation), so it
    reaches the same verdict as the file's own `rule` field and as
    tests/contracts/test_FR_WLD_03_outbox_crossref.py's `broken()` reference check. Never raises
    on a well-formed case."""
```

## Reason codes

`Decision.reason` is one of exactly:
`t3_always_gates`, `no_covering_policy`, `l0_draft_only`, `l2_instruction_required`,
`l2_run_after_undo`, `l3_run`, `l3_daily_cap_reached`, `l3_credits_cap_reached`,
`gate_approved`, `gate_not_opened`.

## Determinism / no model in the decision (FR-HIL-04, FR-HIL-08)

Nothing under `packages/policy/src` imports `tilo_providers`, `random`, `secrets`, any network
library (`requests`, `httpx`, `urllib`, `socket`), or reads the wall clock (`datetime.now`,
`datetime.utcnow`, `time.time`, `time.time_ns`) — `decide` and `open_gate` take every time value
(`now`, event `at`/`ts` fields) as arguments. `packages/policy/tests/test_no_model_in_decision.py`
enforces this with an `ast` scan over every `.py` file under `packages/policy/src`.

## Inputs are checked against the contracts (review round 1)

`decide`, `open_gate` and `check_entry` validate what they read against `contracts/*.schema.json`
before using it: each policy (`policy.schema.json`), Team Lead record, event part's `data`
(`approval.requested`, `approval.resolved`, `policy.applied`, instruction events) and outbox entry.
A policy that fails covers nothing; an event part or entry that fails opens nothing ("gate") or is
rejected (`check_entry` returns "OB-01"). Timestamps accept ASCII digits only. On the policy path
`check_entry` also rejects a T3 entry, any modifier, `authz.by` other than "policy", `authz.ref`
other than the `policy_id`, and a send over `limits.per_day` / `limits.credits` (PI-07, PI-11, PI-16).
`applied` must hold the earlier `policy.applied` parts under the owner's policies in every world,
not just this one, or a policy's daily cap multiplies by the number of worlds; the caller (harness)
supplies them.

## Live decisions read the record as it is (review round 3)

`decide` is a live decision: if any of the owner's policies for the action type has a
`created_by`, `changed_by` or history stamp dated after `now` (or one that cannot be read), the
whole decision gates (the clock is behind the record: a retry, a replay or skew), so a Stop all or
revocation already in the record always gates, whatever other policy covers the send. Reading a policy back to an earlier
level is `check_entry`'s job alone (a send made before a revocation stays covered, PI-13). Two
records sharing an id gate, whether or not both cover the send. At L2 the instruction must be
dated no earlier than the history entry that put the policy at the L2 level in force. With
`table` given, `check_entry` also rejects an entry whose `risk_tier` is not the tier the table
assigns to its `action_type` and `modifiers` (PI-07, PI-14).
