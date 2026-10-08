# `tilo_people` — public API these tests pin

Ticket PPL-10 "People core" (`docs/prd-addendum-people-agents.md` section 8). Package
`packages/people`, import name `tilo_people`, dist name `tilo-people`. Privacy path: PPL-11a
(meetings, work items, plate) and PPL-11b (pinboards, calendar, assistant) import it; PPL-20
(minutes) and PPL-31 (calendar sync) use the name, date and store parts. This file is the contract
the builders implement exactly; tests in this directory import only what is listed here.

Order of truth: `contracts/` (schemas, `contracts/people.rules.md` PE-01 to PE-30, the crossref
fixtures), then the addendum and the 2026-10-05 supplement section 3, then ADR-0015/0016, then this
file. Where this file picks a default the rules leave open, the BQ id is given (`docs/open-questions.md`).

## Slices (one builder ticket each, about 400 hand-written lines with tests)

| Slice | Modules | Depends on | Unblocks |
| --- | --- | --- | --- |
| PPL-10a | `errors`, `text`, `directory`, `access` (`decide`, `project`, `read`), `crossref` | contracts only | PPL-11a/b reads, the plate and quote oracles |
| PPL-10b | `names` (`normalize_name`, `match_name`, `name_candidates`), `dates` (`resolve_due`) | 10a | PPL-20 (FR-MTG-05) |
| PPL-10c | `writes` (`check_write`) | 10a | PPL-11a/b writes |
| PPL-10d | `stores` (`MemoryStore`, `PeopleStores`, tombstone, disconnect, erasure) | 10a (`errors`) | PPL-11a/b, PPL-31 |

10b, 10c and 10d run in parallel once 10a is merged. Tests import each name from its module
(`tilo_people.errors`, `.text`, `.directory`, `.access`, `.crossref`, `.names`, `.dates`, `.writes`,
`.stores`); `tilo_people/__init__.py` stays a docstring, so parallel slices never conflict there.
Test files are named
`test_PPL_10<slice>_<req ids>_<topic>.py` (e.g. `test_PPL_10a_FR_PA_11_crossref_verdicts.py`); the shared
helper module is `_ppl10_testlib.py` (a unique name: `tests/contracts/_people_lib.py` and every
`_lib.py` share one `sys.path` under pytest's prepend mode).

## Rules for every module

- Pure and deterministic. No model, provider, network, randomness, logging, `print`, file write or
  wall-clock read under `src/` (an `ast` scan like `packages/policy/tests/test_no_model_in_decision.py`
  forbids importing `tilo_providers`, `random`, `secrets`, `logging`, `socket`, `requests`, `httpx`,
  `urllib`, and calling `print`, `datetime.now`, `datetime.utcnow`, `date.today`, `time.time`,
  `time.time_ns`, `time.monotonic`). Time comes only from `now` / `meeting_at` arguments.
- Every record is checked against its JSON Schema with `tilo_policy.schemas.conforms`
  (`"person.schema.json"`, `"meeting.schema.json"`, ...; its `pattern` fix makes `$` end the string),
  never against the generated pydantic models (they drop `if`/`then`, ADR-0002).
- Timestamps are `common.schema.json#/$defs/timestamp` (fixed width, UTC, ASCII digits), so a
  validated timestamp compares correctly as a string. Every digit test uses `[0-9]`, never `\d`
  (Python's `\d` matches Devanagari and other digits).
- Fail closed: `decide` and `check_write` never raise; anything malformed, unknown or missing is a
  refusal. Nothing here emits an event (callers do) or authorises a side effect (the policy engine
  and the outbox do).
- Nothing here puts record text (titles, bodies, names, aliases, emails, due phrases) into an
  exception message or a `repr`; only kinds, ids, versions and codes.

## Errors (`tilo_people.errors`)

```python
class PeopleError(Exception): ...


class PeopleInputError(PeopleError, ValueError): ...  # malformed argument to a store or to resolve_due


class AlreadyExists(PeopleError): ...  # create: (org_id, id) is taken


class NotFound(PeopleError): ...  # replace/delete: no such (org_id, id)


class VersionConflict(PeopleError): ...  # replace/delete: expected_version is not current
```
`str(e)` names the kind, the record id and the versions, nothing else.

## Text hygiene (`tilo_people.text`) — PE-24

```python
def clean_line(text: str) -> str:
    """Removes every character whose unicodedata.category is Cc, Cf, Zl or Zp (control, format
    incl. bidi overrides, zero-width and astral tag characters U+E0000..U+E007F, line and
    paragraph separators). Nothing else changes."""
```

## 1. Visibility oracle (PPL-10a) — PE-01 to PE-08, PE-11, PE-17 to PE-20

### Directory: the membership facts

```python
@dataclass(frozen=True)
class Directory:
    persons: Mapping[str, Mapping[str, Any]]  # user id -> person record, only valid, unambiguous ones

    @classmethod
    def of(cls, persons: Iterable[Mapping[str, Any]]) -> "Directory":
        """Keeps each record that conforms to person.schema.json, keyed by its `id`. A record that
        fails its schema is dropped; an id held by two records (two orgs, or a duplicate) drops
        both. Never raises."""

    def get(self, user: str) -> Mapping[str, Any] | None: ...
    def is_member(self, user: str, team: str, now: str) -> bool:
        """people.rules.md "Terms": `user` is in the directory and has a membership for `team`
        whose `assigned_by.by` is in the directory, of the user's own org, with org_role "owner",
        and `assigned_by.at <= now`."""

    def teammates(self, a: str, b: str, now: str) -> bool:
        """Both in the directory and members of at least one common team at `now`."""
```
The caller passes every person of the actor's org (team scale, ADR-0015). A person missing from
the directory has no rights and no membership. Membership is evaluated at `now`, so a person who
left (entry removed) or whose entry is dated later counts as no member.

### The request

```python
ACTIONS = (
    "read_full",
    "read_status",
    "read_busy",
    "read_directory",
    "read_membership",
    "create",
    "edit",
    "confirm",
    "mention",
    "untag",
    "mark_done",
    "assign_membership",
    "set_org_role",
    "start_capture",
)  # people.rules.md "Terms", in this order
RECORD_KINDS = ("pinboard_item", "work_item", "calendar_entry", "meeting", "mention", "person")


@dataclass(frozen=True)
class AccessRequest:
    actor: str  # "u_..." the signed-in person (from the session), or "A_..." Tilo
    action: str  # one of ACTIONS
    record_kind: str  # one of RECORD_KINDS
    record: Mapping[str, Any]  # the stored record (a create: the record to be stored)
    now: str  # the server clock, read once per API request by the caller
    meeting: Mapping[str, Any] | None = None  # source meeting (or its tombstone) of a Tilo-made record or pin
    work_item: Mapping[str, Any] | None = None  # the released item a Tilo calendar proposal cites (PE-08)
    source_owner: str | None = None  # owner of a mail, request, call or Google source (PE-08)
    pin: Mapping[str, Any] | None = None  # record_kind "mention": the pin it tags
    mentions: tuple[Mapping[str, Any], ...] = ()  # action "mention": the pin's existing mentions


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    view: str | None  # reads: "full" | "status" | "busy" | "directory" | "membership"; else None


def decide(request: AccessRequest, directory: Directory) -> Verdict: ...
```
`decide` never raises and never reads a store or a clock. A refusal is `Verdict(False, None)`;
callers answer 404 for a refused read (no 403, no existence oracle). For an allowed read, `view`
is the action's suffix (`read_busy` -> `"busy"`); for an allowed write it is `None`.

### `decide`: semantics

`decide` is a port of `permits()` in `tests/contracts/_people_lib.py` (the reference oracle of the
crossref suite) with exactly the additions S1 to S5 (stricter) and G1, G2 (grants the reference
lacks). Nothing else may differ. In order:

0. **Input gate** (any failure: refuse). `actor` matches `common#/$defs/user_id` or `agent_id`;
   `action` in ACTIONS; `record_kind` in RECORD_KINDS; `now` is a timestamp; `record` conforms to
   `contracts/<record_kind>.schema.json`; `meeting`, `work_item`, `pin` conform to their schemas when
   given; every entry of `mentions` conforms to `mention.schema.json`; `source_owner` is None or a
   user id. Tilo = an `agent_id` actor; Tilo never appears in the directory.
1. **Stricter clauses (PE-19, checked on every request; any failure: refuse).**
   - S1: when `meeting` is given and its `minutes_confirmed_by` is not None, that stamp's `by` is
     the meeting `owner` and its `at <= now`.
   - S2: a person-made work item (`record`, `created_by.by == "person"`) has `assigned_by` None or
     `assigned_by.by == created_by.ref`.
   - S3: in `record`, `pin` and `work_item`, every history entry whose `change` is `confirmed` or
     `accepted` has `by == confirmed_by.by` (a `confirmed_by` of None fails it).
   - S4: in `record` and `pin` when they are pinboard items, `kind == "link"` exactly when `url` is
     not None.
   - S5: a calendar entry `record` has `end` None or `end >= start`.
2. **Mentions** (`record_kind == "mention"`, before the Tilo gate, because Tilo may tag): refuse
   unless `pin` is given, `pin.scope.kind == "team"`, `record.pin_id == pin.id`,
   `record.team == pin.scope.team`, `record.org_id == pin.org_id`, and, for a Tilo-made pin,
   `tilo_made_ok(pin)`.
   - `mention`: refuse unless `pin.status == "active"`, `record.removed` is None, the tagged person
     is in the directory, of the pin's org and a member of `record.team` at `now`, and no entry of
     `mentions` has `user == record.user` with `removed.by == record.user`. Then a person actor is
     allowed when it is `pin.set_up_by`, of the pin's org and a member of the team; Tilo is
     allowed when `confirmed(pin, pin.set_up_by)`.
   - `untag`: refuse when `record.removed` is not None; allowed for a person of the pin's org who
     is `record.user` or `pin.set_up_by`.
   - anything else (every read of a mention record included): refuse (BQ-PPL10-12).
3. **Actor gate.** Tilo continues only for `create`. A person must be in the directory with
   `org_id == record.org_id`.
4. **Per kind** (helpers below; "reads" means `read_full` and `read_status`; an action a kind
   does not name is refused):
   - `pinboard_item`: Tilo-made and not `tilo_made_ok`: refuse. Person-made with
     `set_up_by != created_by.ref`: refuse. Personal scope: `create` is allowed for Tilo (Tilo-made)
     or for `scope.user` (person-made); otherwise only `scope.user` may `read_full`, `read_status`,
     `edit`. Team scope T: `create` (Tilo-made) needs Tilo, `status == "proposed"` and owner_ok;
     `create` (person-made) needs `actor == set_up_by`, actor a member of T, owner_ok (owner None or
     a member of T). Tilo otherwise: refuse. `active`: reads for members of T (a Tilo-made pin only
     when `confirmed(pin, set_up_by)`), `edit` for `set_up_by` while a member. `proposed`/`removed`:
     reads and `edit` for `set_up_by` while a member; `confirm` for `set_up_by` while a member and
     only on `proposed`.
   - `work_item`: Tilo-made and not `tilo_made_ok`: refuse. `create`: person-made needs
     `actor == owner == created_by.ref`, `status == "open"`, `assigned_by` None or by the creator;
     Tilo-made needs Tilo, `status == "proposed"`, `assigned_by` not None. Tilo otherwise: refuse.
     `proposed`: only `confirm`, by `assigned_by.by`. A Tilo-made item not `confirmed(item,
     assigned_by.by)`: refuse. `read_full`, `edit`: the owner. `mark_done`: the owner, on `open`.
     `read_status`: the owner or `assigned_by.by`.
   - `calendar_entry`: Tilo-made and not `tilo_made_ok`: refuse. `create`: person-made needs
     `actor == owner`; Tilo-made needs Tilo, `confirmed_by` None and `share` None. Tilo otherwise:
     refuse. An `accepted` entry whose source is `tilo`, or Tilo-made with source `manual`, that is
     not `confirmed(entry, owner)`: refuse. `confirm`: the owner, on `proposed`. `edit`: the owner,
     and when `share` is set the owner is a member of `share.team`. Reads: the owner, or a member of
     `share.team` when `share` is set, the entry is `accepted` and the owner is still a member.
     `read_busy`: the owner, or a teammate of the owner when the entry is `accepted`.
   - `meeting`: `start_capture`: `actor == owner`, `attestation.by == owner`, attester in the
     directory (PE-18). Reads, `edit`, `confirm` (the minutes card): the owner. **G2** `create`:
     `actor == owner` and `attestation.by == actor` (FR-MTG-01, PE-18; BQ-PPL10-3).
   - `person`: org_owner = actor's record has `org_role == "owner"` and the record's org.
     `assign_membership`, `set_org_role`: org_owner. `read_full`: `actor == record.id`.
     `read_membership`: self or org_owner. `read_directory`: self, org_owner, or a teammate.
     **G1** `create`: org_owner (PE-17; the first person of an org is minted by tilo-api outside
     `decide`; BQ-PPL10-3).
   - anything else: refuse.

Helpers (as in the reference): `confirmed(r, who)` = `r.confirmed_by` not None, `who` not None,
`confirmed_by.by == who`, `created_by.at <= confirmed_by.at <= now`.
`meeting_matches(ref, org)` = `meeting` given, `ref` not None, `ref.split("#")[0] == meeting.id`,
`meeting.org_id == org`. `minutes_confirmed` = `meeting.status == "minuted"`,
`minutes_confirmed_by.by == meeting.owner`, its `at <= now`. `released_item(entry)` = the source
`ref` holds `#`, `work_item` given, its `owner == entry.owner`, its `source.ref == ref`, status
`open` or `done`, Tilo-made, `assigned_by.by == meeting.owner`, `confirmed(work_item,
meeting.owner)` and `minutes_confirmed`. `tilo_made_ok(r)` (only for Tilo-made `r`):
- pin: source not None and not `manual`; a personal pin's `set_up_by == scope.user`; source
  `meeting`: `meeting_matches(source.ref, r.org_id)` and `set_up_by == meeting.owner`; other
  sources: `source_owner == set_up_by`.
- work item: source `meeting`, `meeting_matches`, `assigned_by.by == meeting.owner`.
- calendar entry: source `manual`: no; `google`: `source_owner == owner`; `tilo` from `meeting` or
  `transcript`: `meeting_matches`, then allowed when `meeting.owner == owner`, else only from
  `meeting` with `released_item`; `tilo` from `request` or `mail`: `source_owner == owner`.

### Views and fields

```python
VIEW_FIELDS = {
    "status": ("id", "title", "status", "due"),
    "busy": ("start", "end"),
    "directory": ("id", "display_name"),
    "membership": ("id", "display_name", "org_role", "memberships"),
}


def project(record_kind: str, view: str, record: Mapping[str, Any]) -> dict[str, Any] | None:
    """View "full": a deep copy of the record. "status": the VIEW_FIELDS keys the record has (a
    calendar entry gives id and title). "busy" (calendar entries only): {"start", "end"}, or None
    when `end` is None (BQ-PPL10-9). "directory", "membership" (persons only): those keys. Values
    are deep copies; no other key is ever copied. Unknown kind or view: None."""


def read(request: AccessRequest, directory: Directory) -> dict[str, Any] | None:
    """`project(...)` of `request.record` when `decide` allows a read_* action, else None."""
```
Email, aliases, time zone and preferred channel leave only in the person's own `full` view (PE-20).
The assistant reads as the signed-in person (`u_`), never as an agent id (PE-11): an agent id
reads nothing.

### Crossref adapter (`tilo_people.crossref`) and how the fixtures are driven

```python
def case_request(case: Mapping[str, Any]) -> tuple[AccessRequest, Directory]:
    """One contracts/fixtures/person/crossref/{valid,invalid}/*.json case:
    actor = case.request.actor; action = "read_" + view when case.request.action == "read", else
    case.request.action; record_kind = case.record.kind; record = case.record.data; now = case.now;
    meeting, work_item, source_owner, pin from case.record (None when absent); mentions =
    tuple(case.record.get("mentions", ())); directory = Directory.of(p for k, p in
    case.persons.items() if p.get("id") == k). Raises PeopleInputError on a case missing a key."""


def verdict_for_case(case: Mapping[str, Any]) -> Verdict:
    """decide(*case_request(case)); a malformed case is Verdict(False, None), never an exception."""
```
Acceptance (PPL-10a):
- Every file in `person/crossref/valid/` (29 today): `case["rule"] is None`,
  `verdict_for_case(case).allowed is True`, and for a read action `verdict.view` is its suffix.
- Every file in `person/crossref/invalid/` (75 today): `verdict_for_case(case).allowed is False`.
- For every valid read case, `read(...)` returns exactly the `project(...)` keys and values.
- **Parity property.** Load the reference with `tests/contracts` on `sys.path`
  (`import _people_lib`). For every crossref case (valid and invalid), every actor among the case's
  persons plus `"A_analyst"`, and every action in ACTIONS, at the case's `now`:
  `decide(...).allowed` implies `_people_lib.permits(...)`, except for `(person, create)` and
  `(meeting, create)` (G1, G2). Must run in under 30 s.
- One test per S1 to S5 where the reference permits and `decide` refuses, and one per G1, G2.
- The plate and transcript crossref suites (PE-22 to PE-28) are PPL-11a's acceptance; their
  oracles call `decide(..., action "read_full")` exactly as `_read` in
  `tests/contracts/test_CC_PEOPLE_3_quotes_and_plate.py` calls `permits` (BQ-PPL10-10).

## 2. Names (PPL-10b) — FR-MTG-05, PE-15, PE-20

```python
NAME_MAX = 80


def normalize_name(text: object) -> str:
    """Exactly, in order: not a str or len > NAME_MAX -> "". NFKC. clean_line. NFD, then drop
    U+0300..U+036F (Latin/Greek/Cyrillic diacritics only; Devanagari signs stay). casefold().
    NFKC. Collapse whitespace (str.split, join with one space). Strip leading and trailing
    characters whose category starts with "P", collapse whitespace again. len > NAME_MAX -> ""."""


@dataclass(frozen=True)
class NameMatch:
    status: str  # "resolved" | "ambiguous" | "unknown"
    user: str | None  # set only when resolved
    candidates: tuple[str, ...]  # ambiguous only: matching ids, sorted, at most 10; else ()


def name_candidates(viewer: str, directory: Directory, now: str) -> tuple[Mapping[str, Any], ...]:
    """Persons p of the directory, sorted by id, for which decide(viewer, "read_directory",
    "person", p, now) is allowed: the viewer, their teammates, and everyone in the org when the
    viewer is an org owner (PE-20). No one else can be named in minutes."""


def match_name(spoken: object, directory: Directory, *, viewer: str, now: str) -> NameMatch:
    """key = normalize_name(spoken); "" -> unknown. A candidate matches when key equals
    normalize_name of its display_name or of any alias (empty results ignored). 0 matches ->
    unknown, 1 -> resolved, 2 or more -> ambiguous. No prefix, first-name, token, fuzzy or
    phonetic matching; attendance never breaks a tie (BQ-PPL10-4). The model never resolves."""
```
The minutes `viewer` is the meeting owner. `owner_text` is kept as said; `owner` is set only for
`resolved` (PE-15); ambiguous and unknown raise the "Who is Priya?" card (FR-MTG-05).

## 3. Due dates (PPL-10b) — FR-MTG-05, PE-15

```python
DUE_REASONS = (
    "resolved",
    "no_phrase",
    "too_long",
    "not_understood",
    "ambiguous",
    "before_meeting",
    "out_of_range",
    "bad_time_zone",
)


@dataclass(frozen=True)
class DueResolution:
    due: str | None  # YYYY-MM-DD, set only when reason == "resolved"
    due_text: str | None  # the phrase as said, cleaned; None for no_phrase and too_long
    reason: str  # one of DUE_REASONS


def resolve_due(due_text: object, *, meeting_at: str, time_zone: str) -> DueResolution:
    """Raises PeopleInputError only when meeting_at is not a common timestamp."""
```
- `meeting_at` is `meeting.scheduled.start`, else `meeting.created_at`; `time_zone` is the
  assignee's, or the meeting owner's while the owner is unresolved (BQ-PPL10-5). D0 = the date of
  `meeting_at` in `time_zone` (zoneinfo with the `tzdata` package). `time_zone` that does not
  fullmatch the person schema pattern or that zoneinfo cannot load: `bad_time_zone`, `due` None.
- `due_text`: None or not a str -> `no_phrase`; `len > 60` -> `too_long`; else `clean_line`, collapse
  whitespace; empty -> `no_phrase`. The key is that text, NFKC, casefold, trailing `.` and `!`
  removed, commas replaced by spaces, whitespace collapsed.
- Grammar (the whole key must match; optional prefix `by` | `on` | `due` | `due by` | `due on`,
  then optional `the`):

| Phrase | due |
| --- | --- |
| `today`, `tonight`, `eod`, `cob`, `end of day`, `end of the day`, `end of today`, `close of business` | D0 |
| `tomorrow` | D0 + 1 |
| `day after tomorrow` | D0 + 2 |
| WD (`monday`..`sunday`, `mon` `tue` `tues` `wed` `thu` `thur` `thurs` `fri` `sat` `sun`) | next WD strictly after D0; WD equal to D0's weekday: `ambiguous` |
| `this` WD | WD of D0's Monday-to-Sunday week if `>= D0`, else `ambiguous` |
| `end of week`, `end of the week`, `end of this week`, `eow` | Friday of D0's week if `>= D0`, else `ambiguous` |
| `end of next week` | Friday of the following week |
| `end of month`, `end of the month`, `end of this month`, `eom` | last day of D0's month |
| `end of next month` | last day of the next month |
| `in` N (`day`, `days`) / (`week`, `weeks`); N = `[0-9]{1,3}`, `a`, `an`, `one`..`ten` | D0 + N (1..365) / D0 + 7N (1..52); 0: `not_understood`; above: `out_of_range` |
| ORD alone (`1st`, `2nd`, `3rd`, `4th`..`31st`, the English suffix required: `11th`, `12th`, `13th`, `21st`) | day `>= D0.day`: this month if the day exists, else `ambiguous`; day `< D0.day`: next month if the day exists, else `ambiguous`; `0th` or above 31 `not_understood` |
| ORD [`of`] MONTH, DAYNUM MONTH, MONTH ORD, MONTH DAYNUM (MONTH `january`..`december`, `jan`..`dec`, `sept`; DAYNUM `[0-9]{1,2}`), optional `[0-9]{4}` year last | no year: this year's date if valid and `>= D0`, else next year's if valid, else `not_understood`; with year: invalid `not_understood`, `< D0` `before_meeting`, year `> D0.year + 1` `out_of_range` |
| `YYYY-MM-DD` | that date; `< D0` `before_meeting`; invalid `not_understood` |
| `next` WD, `next week`, `this week`, `[0-9]{1,2}/[0-9]{1,2}(/[0-9]{2,4})?` | `ambiguous` (never guessed: locale and "next" are ambiguous) |
| anything else (times of day, "before Friday", other languages, non-ASCII digits) | `not_understood` |

- Any result more than 366 days after D0: `out_of_range`. Nothing resolves before D0. A date
  before the request day but on or after D0 stays (the plate shows it overdue, PE-28); there is no
  `now` argument. Dates are computed on `date` values, so DST never shifts a day once D0 is known.

## 3b. Free slots (FR-CAL-07b-1) — `tilo_people.free_slots`

```python
def find_free_slots(entries, *, owner, now, tz, duration_min, working_window=("09:00", "18:00"),
                    working_days=(0, 1, 2, 3, 4), not_before=None, not_after=None, count=3, step_min=15,
                    buffer_min=0, default_entry_min=60, horizon_days=14) -> tuple[str, ...]
def parse_working_window(raw) -> tuple[str, str]   # {start, end} of config/personal.yaml; raises FreeSlotError
class FreeSlotError(PeopleInputError): reason: str  # a code, never record text
```

Returns up to `count` UTC start timestamps, earliest first, strictly increasing, each fitting `duration_min`
plus `buffer_min` either side free inside `working_window` (local to `tz`) on `working_days` (Monday 0), on the
local `step_min` grid, no later than `now` + 14 days and ending by `not_after`. Busy: the owner's `accepted`
entries and the owner's `free_busy` intervals; all-day blocks its local day; no end blocks `default_entry_min`.
Refused with a reason: `bad_owner`, `bad_time_zone`, `bad_window`, `bad_duration` (not an int >= 1),
`duration_too_long` (longer than the window), `bad_working_days`, `bad_count`, `bad_step`, `bad_buffer`,
`bad_default`, `bad_horizon`, `bad_time`, `bad_entry`, `too_many_entries` (over 2000).

## 4. Write checks (PPL-10c) — PE-02, PE-04, PE-07, PE-17, PE-19

```python
WRITE_PROBLEMS = (
    "not_allowed",
    "unsupported",
    "schema",
    "identity",
    "immutable",
    "stamp",
    "transition",
    "history",
    "owner_not_member",
    "after_not_allowed",
    "snooze_range",
)


def check_write(request: AccessRequest, after: Mapping[str, Any], directory: Directory) -> tuple[str, ...]:
    """The problems with storing `after` for this request; () means store it. Sorted, unique,
    never raises. Callers run decide, build `after` with stamps {by: actor, at: now} from the
    session and the server clock (PE-19), run check_write, then store with compare-and-set."""
```
1. `decide(request)` refuses: `("not_allowed",)`. A read action or `start_capture`:
   `("unsupported",)`. `after` fails its kind's schema: `("schema",)`.
2. `create` and `mention` (a tag creates a mention): `after` must equal `request.record` (else
   `identity`), and its stamps are the actor's at `now` (else `stamp`): `created_by` /
   `added_by` = `{by: "person" for u_ or "tilo" for A_, ref: actor, at: now}` (person records:
   `{by: actor, at: now}`, and every membership's `assigned_by` the same); `created_at`,
   `updated_at` = now where the kind has them; `confirmed_by` (and a meeting's
   `minutes_confirmed_by`) None; a mention's `removed` None; a Tilo-made work item's
   `assigned_by.at` = now; a person-made one's `assigned_by` None or `{actor, now}`; a meeting's
   `attestation.by` = actor with `at <= now`. Work items and pins: `history` is exactly
   `[{at: now, by: actor, change: "created", status: after.status}]` (else `history`).
3. Every other write: `after.id` and `after.org_id` equal the record's (else `identity`); every
   top-level field outside the row's MAY set is deep-equal to before (else `immutable`); history,
   where the row names one, keeps the old entries as a prefix and gains exactly one entry
   `{at: now, by: actor, change: <listed>, status: after.status}` (else `history`); `updated_at`,
   where the kind has it, is now (else `stamp`).

| Kind, action | MAY change | Must hold |
| --- | --- | --- |
| work_item, `edit` | title, due, due_text, snoozed_until, status, history, updated_at | status unchanged, or `done` -> `open` with change `reopened` (PE-30); other changes `edited`, `snoozed`, `reassign_requested`; a changed `snoozed_until` is None or `now < it <= now + 30 days` (`snooze_range`) |
| work_item, `confirm` | status, confirmed_by, history, updated_at | `proposed` -> `open`; `confirmed_by == {actor, now}`; change `confirmed` |
| work_item, `mark_done` | status, history, updated_at | `open` -> `done`; change `done` |
| pinboard_item, `edit` | title, body, kind, url, owner, due, status, history, updated_at | status unchanged (change `edited`, or `owner_changed` when owner changed), or `active`/`proposed` -> `removed` (change `removed`, or `undone` for a Tilo-made personal pin); team scope: `owner` None or a member of the team at now (`owner_not_member`) |
| pinboard_item, `confirm` | status, confirmed_by, history, updated_at | `proposed` -> `active`; `confirmed_by == {actor, now}`; change `accepted` |
| calendar_entry, `edit` | title, start, end, all_day, share, state, updated_at (Google source: share, updated_at) | state unchanged, `proposed` -> `declined` or `accepted` -> `cancelled` |
| calendar_entry, `confirm` | state, confirmed_by, updated_at | `proposed` -> `accepted`; `confirmed_by == {actor, now}` |
| meeting, `edit` | title, series, scheduled, agenda, attendees | |
| meeting, `confirm` | minutes_confirmed_by | None -> `{actor, now}`; status `minuted` |
| mention, `untag` | removed | None -> `{by: actor, at: now}` |
| person, `assign_membership` | memberships | every entry not in before has `assigned_by == {actor, now}` (`stamp`); entries may be removed |
| person, `set_org_role` | org_role | `member` -> `owner` only (PE-17: roles are only promoted) |

A broken MAY row's state/status/role move is `transition`; a wrong `confirmed_by`/`removed` stamp
is `stamp`. For `edit`, `decide` must also allow the same request with `record=after`
(`after_not_allowed`): this catches a share with a team the owner is not in, a share on an entry
that is not accepted, and S1 to S5 on the new record. No other edit exists: persons have no
`edit` (BQ-PPL10-7), mentions none.

## 5. Stores (PPL-10d) — PE-13, PE-16, PE-19

```python
@dataclass(frozen=True)
class Stored:
    kind: str
    record: Mapping[str, Any] = field(repr=False)  # a deep copy
    version: int  # 1 on create, +1 per replace


INDEXES = {
    "person": (),
    "meeting": ("owner",),
    "work_item": ("owner",),
    "pinboard_item": ("scope.user", "scope.team", "set_up_by"),
    "mention": ("pin_id", "user"),
    "calendar_entry": ("owner",),
}


class RecordStore(Protocol):  # what PPL-11a/b implement on Firestore later
    kind: str

    def get(self, org_id: str, record_id: str) -> Stored | None: ...
    def create(self, record: Mapping[str, Any]) -> Stored: ...
    def replace(self, record: Mapping[str, Any], *, expected_version: int) -> Stored: ...
    def delete(self, org_id: str, record_id: str, *, expected_version: int) -> None: ...
    def list(self, org_id: str, field: str | None = None, value: str | None = None) -> tuple[Stored, ...]: ...


class MemoryStore:  # implements RecordStore for one kind of INDEXES
    def __init__(self, kind: str) -> None: ...  # unknown kind: PeopleInputError


@dataclass(frozen=True)
class PeopleStores:
    persons: RecordStore
    meetings: RecordStore
    work_items: RecordStore
    pins: RecordStore
    mentions: RecordStore
    calendar: RecordStore

    @classmethod
    def in_memory(cls) -> "PeopleStores": ...
```
- Keyed by `(org_id, id)`. `get` with a malformed org or id, or another org's id, is None.
- `create`: the record conforms to its kind's schema (else `PeopleInputError`) and the key is free
  (else `AlreadyExists`). `replace`: schema, key exists (`NotFound`), `expected_version` is current
  (`VersionConflict`), version + 1. `delete`: `NotFound` / `VersionConflict`. Compare-and-set is
  the only update; confirm, mark_done, edit and untag all go through `replace`.
- `list`: `field` is None (every record of the org) or one of the kind's INDEXES (dotted path),
  else `PeopleInputError`; equality on that field; sorted by id; never another org's records.
- Atomic per call (one lock per store); inputs and outputs are deep copies. Stores authorise
  nothing: callers run `decide` and `check_write` first.

```python
def meeting_tombstone(meeting: Mapping[str, Any]) -> dict[str, Any]:
    """PE-19 tombstone, a schema-valid meeting: keeps id, org_id, owner, world_id (when present),
    attestation, source, ended_reason, created_at; sets status "deleted", title "Deleted meeting",
    series None, scheduled None, agenda [], attendees [], transcript None, minutes None,
    minutes_confirmed_by None, delete_transcript_after None, delete_minutes_after None
    (BQ-PPL10-2)."""


def delete_meeting(stores: PeopleStores, org_id: str, meeting_id: str, *, expected_version: int) -> Stored:
    """Replaces the meeting with its tombstone (compare-and-set). Work items, pins and calendar
    entries made from it are not touched; they stay readable through the tombstone (owner kept)."""


def disconnect_calendar(stores: PeopleStores, org_id: str, owner: str) -> int:
    """PE-13: deletes the owner's entries whose source.kind is "google"; returns the count."""


def erase_person(stores: PeopleStores, org_id: str, user: str) -> dict[str, int]:
    """PE-16 (BQ-PPL10-8): tombstones meetings the user owns, then deletes their work items,
    personal pins (scope.user), mentions naming them, calendar entries and finally their person
    record. Team pins they set up stay. Returns counts keyed "meeting", "work_item",
    "pinboard_item", "mention", "calendar_entry", "person". A second run returns all zeros.
    Written against RecordStore only, so a Firestore store gets it unchanged."""
```

## Hostile cases the reviewers will probe (each has a test)

| Case | Expected |
| --- | --- |
| Actor of another org reads, edits or tags (ids that look valid) | refused; a membership assigned by another org's owner never counts |
| Same user id in two orgs' person records | `Directory.of` drops both: that id acts on nothing and is a member of no team |
| A viewer who left the team (membership removed, or dated after `now`) | no read of active team pins, shared entries or busy; no edit of pins they set up |
| Owner withdraws a share (`share` -> None) or leaves the shared team | teammates' `read_full` refused at once; `read_busy` only while still teammates |
| Unknown `record_kind`, `action`, actor shape, malformed timestamp, extra field in a record | refused (input gate, schema `additionalProperties: false`) |
| A field outside the view's allowlist | never in `project`/`read` output (email, aliases, time zone to anyone but self) |
| Tilo (`A_`) reads anything, confirms its own record, tags without the setter's confirmation | refused |
| Meeting-sourced Tilo record without its meeting, or meeting of another org or id | refused (fail closed) |
| Minutes stamp by a non-owner or in the future (S1), stamped history by someone else (S3) | refused even where the reference permits |
| Alias collision: two persons share an alias or display name ("Sam Iyer" twice) | `ambiguous`, never resolved; identity is the id, never the name |
| Spoken name with zero-width, bidi override, tag characters, NFKC-expanding characters, Cyrillic look-alikes, 81+ characters | cleaned and matched on visible text; look-alikes and oversize are `unknown` |
| A person outside the owner's teams with the spoken name | not a candidate, `unknown` (PE-20) |
| `by 2026-01-05` for a meeting in October, `by Friday` on a Friday, `next Friday`, `12/10` | `before_meeting`, `ambiguous`, `ambiguous`, `ambiguous`; `due` None, `due_text` kept |
| Meeting near midnight UTC, assignee in Asia/Kolkata vs America/Los_Angeles; DST-change days | D0 is the assignee's local date; weekday arithmetic on dates |
| `in 999 days`, `in 9999 days`, `in 0 days`, Devanagari digits, fullwidth digits | `out_of_range`, `not_understood` (N is 1 to 3 digits), `not_understood`, `not_understood`, resolved like ASCII (NFKC folds them) |
| Write with stamps from the body (another `by`, an old `at`), changing `owner`/`source`/`created_by`, setting `confirmed_by` by `edit`, rewriting history, demoting an owner | `stamp`, `immutable`, `immutable`, `history`, `transition` |
| Two confirms racing on one version | one `replace` wins, the other gets `VersionConflict` |
| A record whose title is a sentinel string | the sentinel appears in no `repr`, `str(error)` or log (there is no logging) |

## What callers must know (PPL-11a/b, PPL-20, PPL-31)

- `actor` comes from the session (`u_`) or the internal writer's agent id (`A_`), never from a
  body; `now` is read once per API request and used for `decide`, the stamps and `check_write`.
- Load the directory as every person of the actor's org. For a Tilo-made record pass `meeting`
  (the stored meeting or its tombstone) when the source is a meeting or a Tilo source `from`
  meeting or transcript, `source_owner` looked up from the mail, request, call or Google source
  store (never from the record), and `work_item` for a calendar proposal citing `mt_x#aiN`.
- Lists filter with `read()` per record; a refused single read is a 404.
- Writes: `decide`, build `after`, `check_write`, `replace(expected_version)`, then emit the event
  in the world PE-12 names. Log ids and problem codes only, never record text.
- Every Tilo writer that goes through `decide` acts and stamps as an agent id (`A_calendar_sync`,
  not `system`; BQ-PPL10-11).
- Free/busy documents (at most 31 days, PE-19) are assembled by PPL-11b from per-entry
  `read_busy` verdicts (BQ-PPL10-9). Reading a pin's mentions goes through the pin (BQ-PPL10-12).

Open questions: BQ-PPL10-1 to BQ-PPL10-12 in `docs/open-questions.md`.
