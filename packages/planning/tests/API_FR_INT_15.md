# FR-INT-15: the public interface these tests pin

Ticket FR-INT-15 "Best effort before refusal" (`docs/prd-supplement-2026-10-05.md` section 4, Must, user 5 Oct):
"A safe request outside what Tilo can fully do gets best effort first: it does what it can, says plainly what it
could not do and offers alternatives. A hard refusal is only for safety or policy (FR-INT-12)." Acceptance: "Eval:
20 partly-out-of-scope briefs each deliver the possible part and name the rest; 0 hard refusals among them."
PRD 7.1 (FR-INT-03, -06, -09, -12), 9.4, 10.4, 16.3. Builds on `API_FR_INT_11_12.md`; defaults BQ-INT15-1 to -9.

**No contract changes.** One new config file, `config/capability_gaps.yaml` (shipped with this design). The brief,
plan, card and event contracts are unchanged; the gaps reach the PlanGraph through `approach.skips` ("What this
approach leaves out"). No new event type.

## The rule

The Director's existing brief call (one call, no new one) may name the parts of an acceptable task that Tilo cannot
do, each as `{category, part}`: `category` is an id of `config/capability_gaps.yaml`, `part` a short label. Code
decides everything else, deterministically:

- A refusal id (`config/out_of_policy.yaml`) anywhere in the reply refuses the whole task with FR-INT-12's text,
  even beside a malformed gap item.
- An unknown id, a malformed item, an unusable label or more than `MAX_GAPS` gaps fails closed
  (`BriefExtractionError`): nothing is stored, nothing is truncated, no repair is asked for.
- The response schema leaves `out_of_scope` unconstrained, so the router never rejects or repairs a reply because
  of it: every `out_of_scope` outcome is decided by code on the one Director call.
- No deliverable plus at least one gap is `NothingPossible`: said plainly with alternatives, never a refusal.
- Otherwise the brief is the possible part and plans as before; the gaps go to `ExtractionResult.gaps`, the task,
  the `POST /intake` body, and the first lines of every approach's `skips`, so the PlanGraph names them too.

The person reads only configured text (`reason`, `alternative`, `nothing_possible`) beside the model's cleaned
label. A model never states what Tilo can or cannot do, and never decides a refusal away.

## `tilo_planning.gaps` (new module)

```python
DEFAULT_GAP_CONFIG = <repo>/config/capability_gaps.yaml
DEFAULT_CONNECTORS = <repo>/config/connectors.yaml
MAX_GAPS = 3                    # gaps per task, after de-duplication
MAX_PART = 60                   # characters of a part label, raw and cleaned
INVISIBLE = frozenset("ᅟᅠㅤﾠ⠀")   # blank-looking letters and symbol, removed by clean_part
MAX_REASON, MAX_ALTERNATIVE, MAX_LEAD = 120, 200, 200     # config text limits
GAP_LINE = "Not done: {part}. {reason}"   # one skips line: at most 10 + 60 + 2 + 120 = 192 <= 200 (plan.schema.json)

class GapConfigError(RefusalConfigError): ...   # subclass: tilo-api's existing 503 path covers it unchanged

@dataclass(frozen=True)
class GapCategory:
    id: str; reason: str; alternative: str

@dataclass(frozen=True)
class GapPolicy:
    categories: Sequence[GapCategory]   # file order
    nothing_possible: str               # the lead line when no part is possible
    services: Sequence[str]             # `name` of every entry of config/connectors.yaml, file order
    def get(self, category_id: str) -> GapCategory | None   # exact match only

@dataclass(frozen=True)
class Gap:
    category: str; part: str; reason: str; alternative: str   # part cleaned; reason/alternative from config
    def skip_line(self) -> str          # GAP_LINE.format(part=self.part, reason=self.reason)
    def as_dict(self) -> dict[str, str] # {"category", "part", "reason", "alternative"}, in that order

class NothingPossible(Exception):       # neither a TaskRefused nor a BriefExtractionError (no shared base but Exception)
    gaps: tuple[Gap, ...]               # 1..MAX_GAPS
    message: str                        # GapPolicy.nothing_possible
    # str(exc) == "nothing possible: " + ", ".join(category ids): no part, task or model text

def load_gap_policy(path: Path | None = None, *, connectors_path: Path | None = None) -> GapPolicy
def clean_part(value: Any) -> str | None   # the label as shown, or None when unusable
```

- **Config shape** (`load_gap_policy`, `yaml.safe_load`, fail closed with `GapConfigError` naming the key, never the
  value): a mapping with exactly `nothing_possible` and `categories`. `categories` is a non-empty list; each entry has
  exactly `id`, `reason`, `alternative`; `id` matches `[a-z][a-z0-9_]{0,63}` and is unique; each text is a non-blank
  string of at most its limit (`reason` 120, `alternative` 200, `nothing_possible` 200); `alternative` differs from
  `reason` after `strip()`. A missing or
  unreadable file, a tag, or a connectors file that is not a list of mappings each with a non-empty string `name`, is
  a `GapConfigError`. The shipped file has 7 categories.
- **`clean_part(value)`**: `None` unless `value` is a `str` of at most `MAX_PART` characters. Then remove every
  character whose `unicodedata.category` starts with `C` (controls, format characters such as bidi overrides and
  zero-width marks, surrogates, private use, unassigned) and every character in `INVISIBLE` (the Hangul fillers
  U+115F, U+1160, U+3164 and U+FFA0, which are category `Lo` but render as nothing, and the blank Braille pattern
  U+2800), join `str.split()` with single spaces, `rstrip(".")`, then `strip()`. The result must hold at least one
  character whose category starts with `L` or `N` (a letter or a digit); otherwise `None`, so a label of only
  combining marks, symbols, punctuation or blank-looking characters is never a gap. No NFKC or other normalisation
  (it can grow a string). Cleaning only shrinks, so the result is at most `MAX_PART`.

## `tilo_planning.brief.extract_brief` (changed)

```python
def extract_brief(task_text, *, router, budget=None, refusal_policy=None, gap_policy: GapPolicy | None = None)
    -> ExtractionResult                  # gap_policy None: load_gap_policy()

@dataclass(frozen=True)
class ExtractionResult:
    brief: dict; ambiguous_fields: list[str]; run: RouterResult
    gaps: tuple[Gap, ...] = ()          # new, last, so ExtractionResult(brief, ambiguous, run) still works
```

Order of decisions, pinned:

0. If the refusal policy and the gap policy share an id: `GapConfigError`, before any Director call.
1. One Director call. `brief_system.md` is rendered with `categories` (the refusal menu, unchanged), `gaps`
   (`"\n".join(f"- {c.id}: {c.reason}")` in file order) and `services` (`", ".join(policy.services)`, or
   `no other service` when empty). The system prompt holds config text only, so it is byte-identical for every task.
2. `out_of_policy` exactly as FR-INT-12 (a category raises `TaskRefused`; a malformed value is
   `BriefExtractionError`), before `out_of_scope` is read.
3. `out_of_scope` absent: no gaps (go to step 7).
4. **Refusal scan first, over whatever `out_of_scope` holds,** before any shape, length or count check, so a refusal
   id beside a malformed sibling item, or after three valid gaps, still refuses on the one call. A string matches
   when it is exactly equal to a refusal id (no case folding, trimming or Unicode normalisation). The first match in
   this order raises `TaskRefused` with that id's configured text:
   - the value itself, when it is a string;
   - when it is a list, each element in list order: a string element itself; for a mapping element, its `category`
     value when that is a string, then its other values that are strings, in the reply's key order. This holds for
     an element that is otherwise invalid (an extra or missing key, a bad `part`, a non-string `category`);
   - when it is a mapping, its values as for a mapping element.

   Nothing else is searched: numbers, booleans, null and nested lists or mappings are not scanned (they fail step 5).
   A non-string `category` is simply invalid: never a refusal, never a gap.
5. **Shape, in code only** (one call, no repair): `out_of_scope` is a list; each element a mapping with exactly the
   keys `category` and `part`; `category` a `str` that is exactly a gap id (a near-miss is unknown);
   `clean_part(part)` not `None` (this covers a non-string, empty, blank-looking or over-60-character part).
   Anything else is `BriefExtractionError` whose message names the rule, never the value.
6. Identical `(category, cleaned part)` pairs collapse to the first. More than `MAX_GAPS` left:
   `BriefExtractionError`. A list is never truncated.
7. `deliverables == []` with at least one gap: `NothingPossible(gaps, nothing_possible)`. With no gap it stays a
   `BriefExtractionError` (the brief contract's `minItems: 1`).
8. `complete_brief` drops `out_of_scope` as well as `ambiguous_fields` and `out_of_policy`; the brief is
   `brief.schema.json`-valid and holds only the possible part. The result carries `gaps` in list order.

`output_schema()` gains an optional (not required) property, and relaxes one bound of this output schema only
(`brief.schema.json` is unchanged):

```json
"out_of_scope": {}
```

The property is listed (the output schema keeps the generated `Brief`'s `additionalProperties: false`, so an
unlisted key would be rejected) and unconstrained: any JSON value passes the router. Every check of it (list-ness,
element mapping-ness, keys, `category` type, `part` type, emptiness, blank-looking text and the 60-character cap,
the 3-gap cap, duplicates) is code in steps 4 to 6 (`_gaps`, `clean_part`). Why: the router rejects a schema
violation before code sees the reply, repairs once per candidate and escalates (the director role has a primary
and a fallback, so up to 4 calls), and a repair is a fresh generation that can drop a refusal id. So no constraint
on `out_of_scope`, not even a type or a label length. `deliverables.minItems` is 0 here; an empty-deliverables
reply with no gap is not repaired by the router and fails closed in step 7.

## `tilo_planning.approaches.propose_approaches` (changed)

```python
MAX_SKIPS = 5   # plan.schema.json approach.skips maxItems
def propose_approaches(brief, *, router, base, seq, budget=None, gaps: Sequence[Gap] = ()) -> ApproachesResult
def problems(approaches, *, skip_room: int = MAX_SKIPS) -> list[str]
```

- `skip_room = MAX_SKIPS - len(gaps)` (at least 2). `approaches_task.md` gains one sentence, rendered for every
  request: `Each approach lists at most $skip_room skips.`
- `problems()` adds one check: an approach with more than `skip_room` skips gives
  `f"skips: {_label(id)} lists {n} skips; list at most {skip_room}"`. It goes through the existing single repair,
  then `ApproachProposalError`. With no gaps the room is the schema's own 5, so nothing changes.
- On a usable set, code sets every approach's `skips` to `[g.skip_line() for g in gaps] + model_skips`, gap lines
  first in `gaps` order, and re-validates each approach with the generated `PlanApproach`. The event is unchanged.
- `compile_plan` is unchanged: it takes `inputs.approaches` (the merged ones), so the PlanGraph's `approaches[].skips`
  name every gap, and the gap lines reach the plan prompt only inside the APPROACH data block (`_data`).

## Prompts (the builder writes them; substance pinned)

- `prompts/director/brief_system.md`: the deliverables line becomes "up to ten objects (at least one, unless Tilo can
  do none of the task)". After the refusal paragraph and `$categories`, add: "Besides web search, public web pages
  and the files the person uploads, Tilo is connected only to: $services." and "An acceptable task can still have
  parts Tilo cannot do. Do not refuse them and do not drop them silently: keep them out of goal and deliverables
  and add the key out_of_scope, a list with one object per such part: category, one id below, and part, a plain
  label of at most 60 characters naming that part of the task. Use an empty list when Tilo can do all of it. When
  Tilo can do none of it, give an empty deliverables list. Never use out_of_scope for anything an out_of_policy
  category rules out." followed by `$gaps`.
- `prompts/director/approaches_task.md`: the `$skip_room` sentence above. No other prompt changes.

## HTTP (`services/api`)

- `POST /intake` 201 body gains `"gaps": [Gap.as_dict(), ...]` (always present, `[]` when none). `TaskRecord` gains
  `gaps: tuple[Gap, ...] = ()`, set once from the extraction; answers and chip edits never change it.
- `NothingPossible`: 422 with exactly `{"error": <nothing_possible>, "gaps": [...]}`. No `category` and no
  `alternative` key (it is not a refusal); nothing stored (no artifact, task, world or event); no further model call.
- `GapConfigError`: 503 through the existing `RefusalConfigError` handler; nothing stored, no Director call.
- `TaskRefused`: unchanged 422 `{error, alternative, category}`.
- `GET /tasks/{id}/approaches` passes `gaps=task.gaps`: every approach's `skips` starts with the gap lines in the
  intake body's order; a re-proposal after a chip edit adds the same lines.

## The eval set (the acceptance)

Fixture `packages/planning/tests/fixtures/best_effort_set.yaml` (test-writer; fictional names, `example.com` /
`example.org` only, no text copied from `evals/bank/`, GEN-06 shingles):

```yaml
partly_out_of_scope:            # exactly 20, ids BE-01..BE-20
  - {id: BE-01, task: "...", deliverables: [{title: "...", format: pdf}], gaps: [{category: money_movement, part: "..."}]}
must_refuse:                    # at least 6, ids BR-..
  - {id: BR-01, task: "...", out_of_policy: credential_handling, gaps: [...], expect: credential_handling}
nothing_possible:               # at least 2, ids BN-..; the scripted reply has deliverables []
  - {id: BN-01, task: "...", gaps: [...]}
```

Spread of the 20: 1 to 3 deliverables and 1 to 3 gaps each; every shipped gap id in at least 2 cases; at least 5
cases with 2 or 3 gaps, at least 2 with exactly 3; one case repeats a category with two different parts; one part
is exactly 60 characters; at least 4 deliverable formats. `must_refuse` covers: `out_of_policy` set with valid gaps
(2+), `out_of_policy` null with a refusal id in `gaps` at index 0 and after three valid gaps (2+), and
`out_of_policy` set with a different refusal id in `gaps` (`expect` is the `out_of_policy` one).

The check, `packages/planning/tests/test_FR_INT_15_best_effort_eval_set.py`, with a scripted Director behind a real
`Router` (`_fr_int_12_lib` pattern; EFF-01, no paid call), the shipped configs, a fixed approaches reply within the
room and a one-unit plan reply (writer, no skills, connectors or actions). For each of the 20:

1. `extract_brief` returns (no `TaskRefused`, `NothingPossible` or `BriefExtractionError`);
   `[(g.category, g.part) for g in result.gaps]` equals the case's gaps; each `reason` and `alternative` equals
   the shipped config text; `result.brief` validates against `brief.schema.json` and has no `out_of_scope` key.
2. `propose_approaches(..., gaps=result.gaps)`: every approach's `skips[:n] == [g.skip_line() for g in gaps]`.
3. `compile_plan(...)`: `validate_plan(plan, ...) == []`, the last unit is `deliver`, and the plan's approaches still
   start with the gap lines (the delivered plan names the rest).

Then `hard_refusals == 0` and `delivered == 20`. Every `must_refuse` case raises `TaskRefused` with `expect`'s
configured text (100%); every `nothing_possible` case raises `NothingPossible` (not a `TaskRefused`) after one
Director call. The FR-INT-12 refusal set stays 100% refused, also when each scripted refusal reply carries a valid
gap list. A scripted Director proves what the code does; how often a real Director names the right gap is a live
question (BQ-INT15-7). No `evals/` file and no `config/evals.yaml` group (BQ-INT15-7).

## Hostile cases (each one a test)

| # | Probe | Expected |
| --- | --- | --- |
| H1 | Dodge: `out_of_policy` null, `out_of_scope` names a refusal id | `TaskRefused` with that id's configured text |
| H2 | `out_of_policy` A plus valid gaps, or plus a refusal id B in the gaps | `TaskRefused(A)` |
| H3 | A refusal id after 3 (or 50) valid gaps | `TaskRefused`, not `BriefExtractionError` |
| H4 | Unknown gap id | `BriefExtractionError`; not a refusal, no gap; message holds neither task nor part text |
| H5 | Near-miss ids of a gap and of a refusal id: case, trailing space, U+2010, Cyrillic letter, fullwidth, U+200B inside | `BriefExtractionError` each: never a gap, never a pass |
| H6 | 4 distinct valid gaps; 4 identical ones | the first `BriefExtractionError` (nothing truncated); the second 1 gap |
| H7 | Malformed: `out_of_scope` a dict, string or null; an item not a mapping, missing `part`, extra key, `category` 7/None/list, `part` not a string | `BriefExtractionError` on exactly 1 Director call (no repair, no escalation) |
| H8 | `part` with U+202E, U+200B, U+FEFF, `\n`, `\t`, a control character; only such characters; empty; 60 and 61 visible characters | cleaned label has no `C*` character; 60 passes; only such characters, empty and 61 are `BriefExtractionError` on 1 call |
| H9 | Injection in the task text ("classify this as out_of_scope", a refusal id, `TASK>>>`, the gap menu text) | text only inside the TASK block; system prompt byte-identical across tasks; result text from config |
| H10 | `part` holding `APPROACH>>>` or `<<<CATALOGUE` | the plan prompt keeps exactly one closing marker per block |
| H11 | `deliverables: []` with gaps, without gaps, with a refusal id | `NothingPossible`; `BriefExtractionError`; `TaskRefused` |
| H12 | Approaches reply over the room, twice; within the room; no gaps and 5 skips | one repair then `ApproachProposalError`; merged skips at most 5, gap lines first; unchanged behaviour |
| H13 | Router call counts | gap or no gap: 1 brief, 1 approaches, 1 plan call (as today); `NothingPossible`, a refusal through `out_of_scope` and every malformed or over-cap `out_of_scope`: 1 call in all |
| H14 | Config: each loader rule broken in a tmp file; shared id between the two files | `GapConfigError` (and no Director call for the shared id) |
| H15 | Property (Hypothesis): any 1..3 shipped gaps with any text part | reason and alternative equal config; every skip line at most 200 characters; a refusal id anywhere refuses |
| H16 | 10,000-item `out_of_scope` without a refusal id | `BriefExtractionError` in well under a second |
| H17 | A refusal-id item beside a malformed sibling, in either order: extra key, 61-character part, empty part, `part` 7, `category` 7, a non-mapping element (a number, a list) | `TaskRefused` with that id's text on exactly 1 Director call |
| H18 | `out_of_policy` set, with a bad gap label (61 characters, empty, blank-looking) or a malformed `out_of_scope` | `TaskRefused(out_of_policy)` on exactly 1 call |
| H19 | A refusal id in other positions: `out_of_scope` is the bare id string; a list holding the bare id; a mapping whose `part`, or the value of an unexpected key, is the id; `{"category": 7, "part": <id>}`; the same with a near-miss of the id | the exact id: `TaskRefused`, 1 call; a near-miss: `BriefExtractionError`, 1 call |
| H20 | Blank-looking labels: U+3164, U+FFA0, U+115F, U+1160, U+2800, only combining marks (U+0301 repeated), only punctuation, each alone or between spaces | `BriefExtractionError`, 1 call, never a gap; `clean_part` returns `None` |
| H21 | Schema pin | `output_schema()["properties"]["out_of_scope"] == {}` and `"out_of_scope"` is not in `required` |

HTTP: 201 `gaps` equal config text with cleaned parts; `NothingPossible` 422 has exactly `error` and `gaps`, stores
nothing and holds no task text; refusal 422 unchanged; approaches carry the gap lines.

## Cost (EFF)

No new model call: gaps ride on the existing brief call, as `out_of_policy` does. Texts, lines, room and
de-duplication are code and config. The room is told up front, so a well-behaved model needs no repair on a gap
task. `NothingPossible` ends after the brief call (no approaches or plan call). Because `out_of_scope` is
unconstrained in the response schema, every `out_of_scope` outcome (gaps, a refusal in it, a malformed or over-cap
list, an unusable label) takes exactly the one brief call: no router repair, no escalation to the fallback profile.
The system prompt grows by about 9 static lines (cache-friendly, the same for every task).

## Builder must know

- Prompt and output-schema changes alter the replay keys: `evals/tests/test_PL_LIVE_E2E_*` fail until
  `uv run python evals/tests/regen_live_e2e_fixture.py` regenerates `evals/bank/live/B-007`. It sets `LIVE=1` in its
  own process (fake provider, no paid call) and the guard hook blocks that: leave it to the orchestrator or the user
  and say so in the hand-off. The schema amendment (`out_of_scope: {}`) changes the brief-stage key again, so B-007
  needs one more re-record after it lands.
- An untyped property (`{}`) goes to the providers as part of `response_schema`. Before a live run, check that the
  Google and OpenAI-compatible adapters accept it. If one refuses, change that adapter, not this schema: any
  constraint here brings back the router repair.
- `packages/planning/CLAUDE.md` and `services/api/CLAUDE.md` are at the 40-line cap: extend lines (FR-INT-15 module
  line; `capability_gaps.yaml` in the API's config list), never add. Also update `services/api/tests/API_CL_INT_1.md`
  (the intake body gains `gaps`).
- GEN-06 (`tests/repo`): no regex or string test on content-named values; call the label `part`.
- `extract_brief` has one production caller (`services/api/src/tilo_api/intake.py`); any new caller (FR-INT-13 panel)
  must handle `NothingPossible`.
- `problems()`'s keyword default keeps the FR-INT-06 tests as they are.

## Not in this ticket

- The S-02 "Not done" list in `apps/web` (reads the intake body's `gaps`) and a reminder on the delivery screen
  (reads the chosen approach's `skips` from the plan): UI follow-ups. S-03 already shows "Skips: ...".
- A live-model eval of gap naming (needs the user's `LIVE=1`).
- The same router-before-code order still applies to FR-INT-12's `out_of_policy` (typed `string | null`) and to the
  brief's own fields: a refusal id beside, say, an over-long `goal` is rejected and repaired before code reads the
  refusal. Existing FR-INT-12 behaviour, logged in BQ-INT15-5 as a follow-up.
