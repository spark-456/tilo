# Build handoff, Lovable link route, granted data — public API these tests pin (FR-CON-16, FR-CON-17, FR-CON-20)

Source: `docs/prd-supplement-2026-10-05.md` section 6 (SD-03), the E-BUILD eval line there, PRD 10.3, 10.4,
12, 13.2, 13.3, 16.1 to 16.3, HR-1 to HR-7. Builds on the outbox (`API.md`), the adapter conventions
(`API_FR_CON_04_05.md`: `execute_side_effect`, `SideEffectRefused`) and provenance (`API_FR_CON_10.md`).
Contracts used as they are (no change): `connector.schema.json`, `outbox.schema.json` + OB-01..OB-05,
`card.schema.json` + CR-09..CR-12, `artifact.schema.json` + AR-01..AR-07, `brief.schema.json`,
`plan.schema.json#/$defs/approach`, events `approval.requested`, `approval.resolved`, `data.transfer`,
`artifact.created`, `artifact.delivered`. Defaults behind every choice below: `docs/open-questions.md`
BQ-BUILD-1 to BQ-BUILD-8.

Suggested test files: `test_FR_CON_16_config.py`, `test_FR_CON_16_accepted_requirements.py`,
`test_FR_CON_16_build_handoff_flow.py`, `test_FR_CON_17_lovable_link.py`, `test_FR_CON_20_data_grants.py`;
doubles in `_handoff_lib.py`. Every test fails today with `ModuleNotFoundError: tilo_connectors.handoff` (or
`.grants`, `.adapters.lovable`), except the shipped-config tests, which pass once this design commit is in.

Nothing here makes a network call, calls a model or reads `LIVE`. The writer's framing, the secret redactor,
the safety screen, the artifact store and the link store are injected.

## Shipped config

- `config/connectors.yaml` declares `lovable` (after `gmail` and `google_drive`): `auth: none`, `scopes: {}`,
  `capabilities: [send]`, one action `{id: build_handoff, capability: send, risk_tier: T3, gate_type: approval,
  irreversible: true}`, `limits: {per_minute: null, batch_size: null}`, `data_class: {returns: [business],
  redact: []}`. It loads through `load_registry`.
- `config/autonomy.yaml` lists `build_handoff: T3` explicitly; `tilo_policy.load_risk_table().assess(
  "build_handoff", SideEffectFacts(external_share=True))` is `Assessment("T3", ("external_sharing",))`.
- `config/build_partners.yaml` (new; loader-checked shape, no contract, like `config/out_of_policy.yaml`):

```yaml
partners:
  lovable: {action: build_handoff, route: link, max_prompt_chars: 50000, max_url_length: 32000,
            max_framing_chars: 400, max_excerpt_chars: 4000, max_items: 6}
framing_words: [a, an, the, ...]   # lower-case single words, unique, at most 300
```

## Errors (`tilo_connectors.errors`, added)

```python
class BuildPartnerConfigError(ValueError): ...  # message at most 500 characters, names the key, never a value


class HandoffRefused(ValueError):
    rule: str  # "BH-01".."BH-09" or "DG-01".."DG-05" (tables below)
    # The message names the rule and ids (artifact ids, grant id) only: never requirement, framing,
    # excerpt or prompt text, a URL, or anything the redactor would remove.


@dataclass(frozen=True)
class RouteOffer:
    route: str  # "mcp"
    available: bool  # False until FR-CON-18 ships
    reason: str  # "unavailable until FR-CON-18"


class BriefTooLong(HandoffRefused):  # rule "BH-06"
    prompt_chars: int  # len(prompt), code points
    link_length: int  # link_length(prompt)
    max_prompt_chars: int
    max_url_length: int
    truncated: bool  # always False: nothing is ever cut
    alternatives: tuple[RouteOffer, ...]  # exactly (RouteOffer("mcp", False, "unavailable until FR-CON-18"),)
    message: str  # person-facing, exactly as below
```

`BriefTooLong.message` (no prompt text in it):
`"This brief is too long for a Lovable link: the prompt is {prompt_chars:,} characters (at most
{max_prompt_chars:,}) and the link would be {link_length:,} characters (at most {max_url_length:,}). Nothing
was cut and nothing was sent. Lovable's connected route can take longer briefs, but it is not available yet."`

## `tilo_connectors.handoff`

```python
DEFAULT_BUILD_PARTNERS: Path  # <repo>/config/build_partners.yaml


@dataclass(frozen=True)
class BuildPartnerConfig:
    connector: str  # "lovable"
    action: str  # "build_handoff"
    route: str  # "link"
    max_prompt_chars: int  # 1..50000
    max_url_length: int  # 100..2_000_000
    max_framing_chars: int  # 1..1000
    max_excerpt_chars: int  # 1..max_prompt_chars
    max_items: int  # 1..6
    framing_words: frozenset[str]


def load_build_partners(
    path: str | os.PathLike[str] = DEFAULT_BUILD_PARTNERS, *, registry: ConnectorRegistry
) -> dict[str, BuildPartnerConfig]: ...
```

The loader refuses the whole file (`BuildPartnerConfigError`) on: unreadable YAML or aliases (as
`registry._read_entries`), a key other than `partners`/`framing_words` or a partner key other than the seven
above, a bool or non-int limit or one out of range, `route` other than `link`, a partner id not declared in
`registry`, or whose declared action `action` is not `risk_tier: T3`, `gate_type: approval`, `irreversible: true`;
a `framing_words` entry that is not one NFKC-casefolded word matching `[^\W_]+`, a duplicate, or more than 300.

```python
@dataclass(frozen=True)
class AcceptedRequirements:  # every text is whitespace-collapsed: " ".join(value.split())
    world_id: str
    run_id: str
    accepted_by: str  # the world's owner
    accepted_at: str  # RFC 3339 time of the owner's approval
    goal: str
    deliverable_index: int
    deliverable_title: str
    audience: str
    approach_id: str
    approach_label: str
    approach_summary: str
    constraints: tuple[str, ...]  # brief.constraints, in order
    assumptions: tuple[str, ...]  # brief.assumptions[].assumed, in order
    skips: tuple[str, ...]  # the chosen approach's skips, in order

    def fields(self) -> tuple[str, ...]: ...  # every text above in render order


def accepted_requirements(
    *,
    world_id: str,
    run_id: str,
    world_owner: str,
    brief: Mapping[str, Any],  # the brief as the owner approved it (POST /tasks/{id}/approve)
    approach: Mapping[str, Any],  # plan.schema.json approach the owner picked
    chosen_approach_id: str,  # the approach_id of that approval
    deliverable_index: int,  # 0-based index into brief["deliverables"]: ONE deliverable
    approval: Mapping[str, Any],  # {"by": "person", "ref": <user id>, "at": <timestamp>}, exactly these keys
) -> AcceptedRequirements: ...
```

BH-01 refuses: `brief` fails `brief.schema.json`; `approach` fails `plan.schema.json#/$defs/approach`;
`approach["id"] != chosen_approach_id`; `deliverable_index` not an int (bool refused) in range;
`approval["by"] != "person"`, `approval["ref"] != world_owner`, or another key. Nothing else of the brief is
read: `sources`, `deadline`, `sensitivity` and `applied_preferences`, and the approach's `risks`, `dimensions`,
`time` and `credits`, never reach the prompt (BQ-BUILD-1). There is no thread, message or event parameter
anywhere in this module.

```python
def declined_texts(
    *, draft_brief: Mapping, approved_brief: Mapping, approaches: Sequence[Mapping], chosen_approach_id: str
) -> tuple[str, ...]: ...
```

The texts the person did not accept, whitespace-collapsed, unique, sorted: the draft's `goal` and `audience`
when they differ from the approved ones; each draft `constraints` item, `assumptions[].assumed` and
`deliverables[].title` that is not in the approved brief's list; the `label` and `summary` of every approach
whose id is not `chosen_approach_id`.

```python
def writer_brief(accepted: AcceptedRequirements) -> str: ...  # the requirements block below; all the writer sees
def find_leaks(text: str, planted: Sequence[str]) -> tuple[str, ...]: ...
```

**Words.** `words(s)` = `re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", s).casefold())`. A text
*occurs* in another when its words, in order, are a contiguous run of the other's words (a text with no words
never occurs). `find_leaks` returns the `planted` strings that occur in `text`, in `planted` order, each once.

### The prompt (BH-02): rendered by code, nothing else

```python
def render_prompt(accepted: AcceptedRequirements, framing: str, excerpts: Sequence[Excerpt]) -> str: ...
```

`prompt = framing + "\n\n" + requirements_block + reference_block`, LF only, ending in one `"\n"`:

```text
requirements_block = "\n".join([
    "## Goal", goal, "",
    "## Deliverable", deliverable_title, "",
    "## Audience", audience, "",
    "## Approach", f"{approach_label}: {approach_summary}",
    *(["", "## Requirements", *(f"- {c}" for c in constraints)] if constraints else []),
    *(["", "## Assumptions", *(f"- {a}" for a in assumptions)] if assumptions else []),
    *(["", "## Leave out", *(f"- {s}" for s in skips)] if skips else []),
]) + "\n"
reference_block = "" if not excerpts else "\n" + "\n".join([
    "## Reference material",
    "The client shared these excerpts as reference material.",
    *(line for e in excerpts for line in ["", f"### {collapse(e.item.label)}", fence(e.text), e.text, fence(e.text)]),
]) + "\n"
fence(t) = "`" * max(3, longest run of "`" in t + 1)
```

`writer_brief(accepted)` is exactly `requirements_block`. `framing` is the writer's framing when it passes BH-03,
otherwise `DEFAULT_FRAMING.format(title=deliverable_title)`, with
`DEFAULT_FRAMING = "Build the {title} described below. Follow the requirements exactly and add nothing that is not listed."`

### Preparing a handoff

```python
class Screen(Protocol):  # a tilo_providers SafetyProvider fits: check(text) -> {"flagged": bool, "reason": ...}
    def check(self, text: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class PreparedHandoff:
    world_id: str
    run_id: str
    connector: str  # "lovable"
    action_type: str  # "build_handoff"
    deliverable_index: int
    prompt: str  # the exact prompt (render_prompt output)
    prompt_sha256: str  # sha256(prompt.encode("utf-8")), lower-case hex
    framing_source: str  # "writer" | "default"
    framing_rule: str | None  # None when the writer's framing was used, else one of
    # "absent", "too_long", "secret", "flagged", "unknown_word", "declined"
    grant_id: str | None
    items: tuple[tuple[str, int], ...]  # (artifact_id, version) of the excerpts' items, first-use order, distinct
    redacted_items: tuple[tuple[str, int], ...]  # those whose excerpt the redactor changed
    exact: str  # gate.action.exact for the card (BH-08)
    link_length: int  # adapters.lovable.link_length(prompt)


def prepare_handoff(
    *,
    accepted: AcceptedRequirements,
    framing: str | None,  # the writer role's reply to writer_brief(accepted); None when there is none
    excerpts: Sequence[Excerpt],  # from grants.granted_excerpts(); () when nothing is granted
    grant_id: str | None,  # the grant the excerpts came from; required when excerpts is not empty
    grants: GrantStore,
    declined: Sequence[str],  # declined_texts(...)
    partner: BuildPartnerConfig,
    declaration: Mapping[str, Any],  # the connector entry of partner.connector (its name goes on the card)
    redact: Callable[[str], str],  # the shared SEC-01 redactor (FR-MEM-05; BQ-109: never identity in production)
    safety: Screen,
) -> PreparedHandoff: ...  # or raises HandoffRefused / BriefTooLong
```

Checks, in this order; the first failure raises and nothing is returned:

| Rule | Check |
| --- | --- |
| BH-09 | `partner.route == "link"`, `declaration["id"] == partner.connector`, its action `partner.action` is T3, `approval`, irreversible |
| DG-03 | `excerpts` not empty: `grants.require_active(grant_id, world_id=..., run_id=..., connector=...)` passes |
| DG-02 | every `excerpt.item` is one of that grant's `items` |
| DG-04 | at most `partner.max_items` distinct items |
| BH-04 | no declined text occurs in any `excerpt.text`, except a declined text that occurs in one of `accepted.fields()` (it was accepted in that form). The message names the item id |
| BH-03 | the framing (whitespace-collapsed) is used only if: not None or empty (`absent`); at most `max_framing_chars` (`too_long`); `redact(f) == f`, and a redactor error counts as a change (`secret`); `safety.check(f)` not flagged, and an error counts as flagged (`flagged`); every word is in `words` of `accepted.fields()` or in `framing_words` (`unknown_word`); no declined text occurs in it except as BH-04 allows (`declined`). Otherwise `DEFAULT_FRAMING` is used and `framing_rule` says why. Never a refusal |
| BH-05 | `redact(prompt) == prompt` and `safety.check(prompt)` is not flagged (an error refuses) |
| BH-06 | `len(prompt) <= max_prompt_chars` and `link_length(prompt) <= max_url_length`, else `BriefTooLong` |
| BH-08 | `exact` is at most 500 characters (card schema), else refused; never cut |

`exact` = `f"Makes a {name} build link from the prompt shown ({len(prompt):,} characters). {carries} Nothing
leaves Tilo until you open the link; {name} starts building only when you press send there."` with
`name = declaration["name"]` and `carries` = `"It carries no granted data."`, or `f"It carries excerpts of {k}
granted item{'s' if k != 1 else ''}: {', '.join(f'{a}@{v}' for a, v in items)}."`.

### After the prompt is stored

The caller (the handoff unit in the harness, a later wiring ticket) stores `prepared.prompt.encode("utf-8")` in
the artifact store as `text/markdown`, origin `unit` (the handoff unit and its writer agent), idempotency key
`f"{run_id}:{unit_id}:{attempt}:0"` (AR-05), then:

```python
@dataclass(frozen=True)
class HandoffRecord:
    world_id: str
    run_id: str
    unit_id: str
    agent_id: str
    attempt: int
    connector: str
    action_type: str
    prompt: dict  # {"artifact_id", "version"} of the stored prompt
    prompt_sha256: str
    grant_id: str | None
    items: tuple[tuple[str, int], ...]
    exact: str
    link_idempotency_key: str  # f"{run_id}:{unit_id}:{attempt}:1" (the link is the unit's output 1)


class HandoffStore:  # in memory, lock-guarded; a Firestore one later
    def record(
        self, prepared: PreparedHandoff, stored: Mapping[str, Any], *, unit_id: str, agent_id: str, attempt: int
    ) -> HandoffRecord: ...
    def get(self, world_id: str, ref: Mapping[str, Any]) -> HandoffRecord | None: ...


def handoff_gate(record: HandoffRecord, declaration: Mapping[str, Any]) -> dict: ...
```

`record` (BH-07) takes `stored`, the `artifact.schema.json` record the store returned, and refuses unless its
`world_id`, `run_id` equal the prepared ones, `media_type == "text/markdown"`, `content_sha256 ==
prepared.prompt_sha256` (so the store's own redactor changed nothing), `screening == "clean"`, `origin ==
{"kind": "unit", "unit": unit_id, "agent": agent_id}` and `idempotency_key == f"{run_id}:{unit_id}:{attempt}:0"`.
The same `(world_id, artifact_id, version)` recorded again with the same content returns the first record;
anything else under it refuses. `get` keys on `world_id` plus the ref's `artifact_id` and `version`
(type-strict: `True` or `1.0` is not `1`), so another world's record reads as None.

`handoff_gate` returns what the deterministic card builder, `approval.requested` and the outbox entry copy
(CR-10 to CR-12, OB-05), refusing (BH-09) a declaration whose action is not T3, approval, irreversible:

```python
{
    "action_type": "build_handoff",
    "connector": "lovable",
    "risk_tier": "T3",
    "irreversible": True,
    "modifiers": ["external_sharing"],
    "recipients": [],
    "attachments": [],
    "item": record.prompt,
    "destination": None,
    "exact": record.exact,
    "undo_window_s": 0,
}
```

## `tilo_connectors.grants` (FR-CON-20)

```python
@dataclass(frozen=True)
class GrantItem:
    kind: str  # "artifact" | "folder" | "record"
    ref: str  # artifact: an artifact_id; folder: a destination-shaped id; record: "<record_ref kind>:<opaque_ref>"
    version: int | None  # artifact: the pinned version (>= 1, never bool); folder and record: None
    label: str  # 1..80 characters after whitespace collapse, no control characters; the excerpt heading


@dataclass(frozen=True)
class DataGrant:
    id: str  # "dg_" + 26 Crockford base32 characters, minted by the store
    world_id: str
    run_id: str  # the task: a grant lives and dies with this run
    connector: str  # the one build partner it is for
    items: tuple[GrantItem, ...]
    granted_by: str  # the world's owner
    granted_at: str
    state: str  # "active" | "revoked" | "expired"
    ended_at: str | None  # set exactly when not active
    ended_by: str | None  # the owner for revoked, None for expired


class GrantStore:  # in memory, lock-guarded, copies out
    def __init__(self, partners: Mapping[str, BuildPartnerConfig]) -> None: ...
    def create(
        self,
        *,
        world_id: str,
        run_id: str,
        connector: str,
        items: Sequence[GrantItem],
        by: str,
        world_owner: str,
        at: str,
    ) -> DataGrant: ...
    def revoke(self, grant_id: str, *, by: str, world_owner: str, at: str) -> DataGrant: ...
    def end_run(self, world_id: str, run_id: str, *, at: str) -> tuple[DataGrant, ...]: ...
    def get(self, grant_id: str) -> DataGrant | None: ...
    def require_active(self, grant_id: str, *, world_id: str, run_id: str, connector: str) -> DataGrant: ...


class TextArtifacts(
    Protocol
):  # P7's ArtifactStore read side, scoped by world (tests: a dict-backed double that logs reads)
    def head(
        self, world_id: str, ref: Mapping[str, Any]
    ) -> Mapping[str, Any] | None: ...  # artifact.schema.json record
    def read(self, world_id: str, ref: Mapping[str, Any]) -> bytes: ...  # hash-checked bytes (AR-01)


@dataclass(frozen=True)
class ExcerptRequest:
    ref: str  # artifact id
    version: int
    text: str | None  # a contiguous part of that version's text; None = the whole text


@dataclass(frozen=True)
class Excerpt:
    item: GrantItem
    text: str  # line endings normalised to LF, then the redactor's output
    redacted: bool  # the redactor changed it


def granted_excerpts(
    *,
    grants: GrantStore,
    artifacts: TextArtifacts,
    grant_id: str,
    world_id: str,
    run_id: str,
    connector: str,
    requests: Sequence[ExcerptRequest],
    partner: BuildPartnerConfig,
    redact: Callable[[str], str],
    safety: Screen,
) -> tuple[Excerpt, ...]: ...
```

| Rule | Rule (refusals raise `HandoffRefused`; nothing is returned) |
| --- | --- |
| DG-01 | Only the world's owner creates or revokes a grant (`by == world_owner`). `create` refuses: a connector not in `partners`; no items or more than its `max_items`; an item of another kind, a ref not matching its kind's shape (anchored, no newline), an artifact without an int version, a folder or record with one, a bad label; the same `(kind, ref, version)` twice. A refused call changes nothing. `revoke` of a revoked or expired grant returns it unchanged |
| DG-02 | An item outside the grant is never read or included: each request's `(ref, version)` must equal an `artifact` item of the grant (type-strict), checked before `artifacts.head` or `artifacts.read` is called for that ref. Folder and record items are not readable on the link route |
| DG-03 | A grant gives data only while `active`, for its own `world_id`, `run_id` and `connector`, checked first, before any read. `revoke` and `end_run` (the task ended: the harness calls it on `world.completed` or `world.failed`) make it inactive for good. Revoking mid-task stops further use: later `granted_excerpts` and `prepare_handoff` calls refuse, and a prepared handoff that used the grant is never released (adapter, below) |
| DG-04 | Only a text version (`text/markdown`, `text/csv`, `application/json`) of this world, screened `clean`, is read (`head` None or anything else refuses). Its bytes decode as strict UTF-8; with line endings normalised, the request text (or the whole text) is a non-empty substring of it, at most `max_excerpt_chars`. At most `max_items` distinct items per call |
| DG-05 | Each excerpt passes `redact`, then `safety.check` on the redacted text. A redactor error, an empty result, a flagged verdict or a screen error refuses |

## `tilo_connectors.adapters.lovable` (FR-CON-17)

```python
LOVABLE_LINK_PREFIX = "https://lovable.dev/#prompt="


def link_length(prompt: str) -> int: ...  # len(LOVABLE_LINK_PREFIX) + len(quote(prompt, safe=""))
def decode_link(url: str) -> str:
    ...  # ValueError unless url == PREFIX + one percent-encoded value with no
    # "&", "#" or "?", and it decodes as strict UTF-8 (unquote, errors="strict")


@dataclass(frozen=True)
class LinkArtifact:
    world_id: str
    run_id: str
    unit_id: str
    agent_id: str
    idempotency_key: str  # the record's link_idempotency_key (AR-05)
    media_type: str  # "application/json"
    content: bytes  # the link record, canonical JSON (below)


class LinkStore(Protocol):  # production: the artifact store bound to world_id's Scope, origin unit
    def put(self, link: LinkArtifact) -> dict: ...  # artifact_ref; the same idempotency_key returns the same ref


class InMemoryLinkStore:  # dev and tests; `.links` lists the LinkArtifacts it stored, one per key
    def put(self, link: LinkArtifact) -> dict: ...


class LovableLinkAdapter:
    def __init__(
        self,
        *,
        declaration: Mapping[str, Any],
        partner: BuildPartnerConfig,
        handoffs: HandoffStore,
        grants: GrantStore,
        artifacts: TextArtifacts,
        links: LinkStore,
    ) -> None: ...

    id: str  # property: declaration["id"]

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict: ...
```

The link is `LOVABLE_LINK_PREFIX + quote(prompt, safe="")` (`urllib.parse.quote`, UTF-8): the prompt rides in
the fragment, never a query (PRD 16.2), with no `autosubmit` and no `images`/`html` parameters. Only the
adapter builds a link (a private helper); nothing else in `tilo_connectors` does.

`execute_side_effect` (called only by `Outbox.dispatch_due`, SEC-03) does, in order; any failure but the first
raises `SideEffectRefused` (the entry ends `failed`, no `data.transfer`, no link stored):

1. `grant.verify(entry["idempotency_key"])`: no valid Grant raises `MissingGrant` before anything is read.
2. BH-09: `action_type == partner.action`, `connector == self.id`, `recipients == []`, `attachments == []`,
   `destination is None`, `item` not None, `risk_tier == "T3"`, `"external_sharing" in modifiers`.
3. BH-09: `handoffs.get(entry["world_id"], entry["item"])` is a record of this connector (None refuses: a prompt
   that did not go through `prepare_handoff` and `record` never leaves).
4. DG-03: when the record has a `grant_id`, `grants.require_active(...)` for the entry's world, run and connector.
5. BH-07: `artifacts.read(world_id, item)`; its SHA-256 equals the record's `prompt_sha256`; strict UTF-8.
6. BH-06 with the config in force now: `len(prompt) <= max_prompt_chars` and `link_length(prompt) <=
   max_url_length`; never truncated.
7. `links.put(LinkArtifact(...))` with `content = json.dumps({"v": "1.0", "partner": self.id, "route": "link",
   "url": url, "prompt": {"artifact_id": ..., "version": ...} (the item's two keys, no label),
   "outbox_id": entry["id"], "project_id": None, "status": "link_ready"},
   sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")`. An exception from `put` other
   than `SideEffectRefused` propagates (the outbox retries; the same key returns the same version, AR-05).
8. Returns `{"link": <artifact_ref>, "status": "link_ready"}`.

It emits nothing itself: the outbox emits the one `data.transfer` out (`artifact` = the prompt `item`, `authz`
= the entry's). The URL never appears in an event, an exception message or a log line.

**No call to Lovable.** `adapters/lovable.py`, `handoff.py` and `grants.py` import nothing from `socket`,
`ssl`, `http`, `urllib.request`, `httpx`, `requests`, `aiohttp`, `urllib3`, `websockets`, `grpc`, `google`,
`tilo_connectors.live`, `tilo_connectors.tokens`, `tilo_connectors.adapters._transport` or `._google`, and no
model provider. `LovableLinkAdapter` takes no transport, broker or token. `adapters/lovable.py` imports
`handoff` and `grants` only under `TYPE_CHECKING` (`handoff` imports `link_length` from it).

## Ordered flow (who calls what)

1. The owner approves the brief and an approach (`POST /tasks/{id}/approve`) -> `accepted_requirements(...)`;
   `declined_texts(...)` from the draft and the other approaches.
2. Optional: the owner grants items for this task and partner -> `GrantStore.create(...)` (web action, later ticket).
3. The handoff unit asks the `writer` role (through `packages/providers`, never in `tilo_connectors`) with
   `writer_brief(accepted)` as the only data -> `framing`.
4. `granted_excerpts(...)` -> excerpts (only granted, clean, redacted, screened text).
5. `prepare_handoff(...)` -> `PreparedHandoff`, or `BriefTooLong` (the caller shows `message`; nothing is gated)
   or `HandoffRefused`.
6. The caller stores the prompt (text/markdown, AR-05 index 0) -> `HandoffStore.record(...)` -> `HandoffRecord`.
7. Policy: `assess("build_handoff", SideEffectFacts(external_share=True))` is T3 -> a gate. `approval.requested`
   (`item` = the prompt ref, `irreversible: true`, `risk_tier: T3`, reserved `outbox_id`) and the gate card
   from `handoff_gate(...)`: `gate.action = {type, connector, exact, item, destination: null}`,
   `gate.recipients = []`. The web shows `item` as plain text (its exact bytes), not rendered Markdown.
8. The owner (or the assigned Approver) answers on `web` or `mobile_web`: `approval.resolved`.
9. Only on `approve`: the outbox entry from `handoff_gate(...)` with the approval's `authz`, `undo_window_s: 0`,
   `state: queued` -> `Outbox.enqueue(entry, evidence)` (`tilo_policy.check_entry`, OB-01/OB-05).
10. `Outbox.dispatch_due()` -> `LovableLinkAdapter.execute_side_effect` -> link stored -> `data.transfer` out.
11. The harness (later wiring ticket), on that `data.transfer`: `artifact.created` for the link version and
    `artifact.delivered` (`format: in_app`, `outbox_id: null`, cause the `data.transfer`); the link's manifest has
    `inputs: [prompt ref]` and the prompt gets its `sent` revision with cause the `data.transfer` (AR-06, MF-04),
    so the link traces back to the approval (FR-CON-10, FR-MEM-12).

## Acceptance tests: the exact assertions

**FR-CON-16 (a) no outbox entry before an approving `approval.resolved`.** With `Outbox(store, {"lovable":
adapter}, emit, clock)` and `gate_case(connector="lovable", action_type="build_handoff", recipients=(),
destination=None, item=record.prompt, risk_tier="T3")` (entry `modifiers` set to `["external_sharing"]`,
`authorised_by.data.channel` `"web"`): after steps 1 to 7, `outbox.get(outbox_id) is None`, `links.links == []`
and no part was emitted; `enqueue` with `authorised_by.data.option` `"hold"` or `"edit"`, or `authorised_by`
None, raises `OutboxRefused` and the three facts still hold; with `"approve"` it stores the entry, and one
`dispatch_due()` stores exactly one link and emits exactly one `data.transfer` whose `authz` equals the
approval's and whose `data.artifact` equals the card's `gate.action.item`. `adapter.execute_side_effect(entry,
None)` raises `MissingGrant` and stores nothing.

**FR-CON-16 (b) the prompt sent equals the prompt shown, byte for byte.** `decode_link(url).encode("utf-8") ==
artifacts.read(world_id, card["gate"]["action"]["item"]) == prepared.prompt.encode("utf-8")`, where `url` is
read back from the stored link record; `entry["item"] == card["gate"]["action"]["item"] ==
reserved_by["data"]["item"] == transfer["data"]["artifact"] == link_record["prompt"]`. A prompt version replaced
in the double after `record` (different bytes under the same ref) makes dispatch fail the entry with no link.

**FR-CON-16 (c) a requirement the person did not accept never appears.** Plant, as unaccepted: a draft
constraint the owner removed, a draft goal the owner changed, the other approach's summary, a sentence of the
request thread (never passed to any function), and an `applied_preferences` entry. Then
`find_leaks(prepared.prompt, planted) == ()` and `find_leaks(decode_link(url), planted) == ()`. A writer framing
that contains a declined text, or a word outside the accepted words and `framing_words` (for example a planted
"crypto"), gives `framing_source == "default"` with `framing_rule` `"declined"` / `"unknown_word"` and the prompt
starts with `DEFAULT_FRAMING`; a framing made only of accepted and listed words is used verbatim (whitespace
collapsed). An excerpt containing a declined text raises `HandoffRefused` with rule `BH-04`. Every
`accepted.fields()` item occurs in the prompt, and `prepared.prompt == render_prompt(accepted, used_framing,
excerpts)`.

**FR-CON-17 (a) the link decodes to the approved prompt.** `url.startswith(LOVABLE_LINK_PREFIX)`, `"?" not in
url`, `"autosubmit" not in url`, and `decode_link(url) == prepared.prompt`, also for a prompt holding `&`, `#`,
`%`, `+`, spaces, newlines and non-ASCII text.

**FR-CON-17 (b) under the limit, or "too long" with the MCP offer.** With a partner whose `max_url_length` is
`n`: a prompt whose `link_length` is `n` prepares; one whose `link_length` is `n + 1` raises `BriefTooLong`
with `truncated is False`, `alternatives == (RouteOffer("mcp", False, "unavailable until FR-CON-18"),)`, the
exact `message`, and nothing recorded, gated, enqueued or stored; the same for `max_prompt_chars`. A record
prepared under a larger limit and dispatched after the limit was lowered ends `failed`, with no link and no
`data.transfer`. Both limits come from the loaded config (a test config file changes them; no code constant).

**FR-CON-17 (c) no call to Lovable from Tilo.** The import rule above holds by AST over the three modules; the
adapter's constructor has no transport-like parameter; with `socket.socket`, `socket.create_connection` and
`socket.getaddrinfo` patched to raise, steps 1 to 10 complete and store the link.

**FR-CON-20 (a) a file outside the grant is never uploaded (link route: never read, never included).** A
request for an ungranted artifact, or a granted artifact at another version, raises `HandoffRefused` `DG-02`;
the `TextArtifacts` double logged no `head` or `read` of that ref; the ungranted file's planted canary is in
no prompt, link or emitted part. `prepared.items` and the ids in `prepared.exact` are exactly the excerpts' items.

**FR-CON-20 (b) a secret in a granted file is redacted.** A granted text file holding a fake secret (assembled
at runtime) and a test redactor that replaces it: the secret is in no excerpt, prompt, link, stored link record
or emitted part; the excerpt's `redacted` is True and its item is in `prepared.redacted_items`.

**FR-CON-20 (c) revoking mid-task stops further uploads.** Revoke after `record` and approval, before dispatch:
the entry ends `failed`, no link, no `data.transfer`. Revoke before preparing: `granted_excerpts` and
`prepare_handoff` raise `DG-03` before any read. `end_run` expires the run's grants with the same effect. A
revoke by someone other than the owner raises `DG-01` and the grant stays active.

**E-BUILD (8 cases; evals ticket).** 4 handoffs: `prepare_handoff` succeeds, `prompt == render_prompt(...)` and
`find_leaks(prompt, declined) == ()` (100%). 2 planted cases (unaccepted text, ungranted file):
`find_leaks(prompt + decode_link(url), planted) == ()` and no read of the ungranted ref (0 leaks). 2 over-long
briefs: `BriefTooLong` with the MCP offer and `truncated is False`.

## Builder notes

- `SIDE_EFFECT_METHOD_NAMES` is unchanged (`execute_side_effect` is already in it).
- `tests/repo/test_GEN_06_*` flags regex calls on content-named values (`text`, `prompt`, `goal`...) in
  `services/*/src`: the word matcher compares task text with accepted and declined task text, never with a
  literal; add each flagged function to `tests/repo/generality_allowlist.txt` with this reason (or the lint
  fails `just check`).
- `services/api/src/tilo_api/runs.py` `gate()` refuses a send with no recipients or destination: wiring a
  build handoff into a run needs its own branch there (later ticket, with step 11).
- The writer's instructions belong in `prompts/writer/build_handoff.md` (intelligence-builder): one paragraph,
  at most `max_framing_chars`, only words of the requirements or `framing_words`.
