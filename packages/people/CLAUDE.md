# packages/people — `tilo_people`

## Purpose
People core for meetings, plates, pinboards and calendars (addendum PPL-10): the visibility oracle
(`decide`, `read`, `project`), write checks (`check_write`), deterministic name matching and due-date
resolution, and in-memory record stores whose interface `tilo-api` implements on Firestore (the person store also holds the founder marker and one address reservation per person; `erase_person` refuses an unfounded org's last person, PPL-11c-FS).

## Commands
- `uv run pytest packages/people/tests -q` (public API pinned in `tests/API.md`); `just check`

## Contracts
- Reads `contracts/{person,meeting,work_item,pinboard_item,mention,calendar_entry}.schema.json`
  and `contracts/people.rules.md` (PE-01 to PE-08, PE-11, PE-13, PE-15 to PE-20, PE-24).
- Acceptance suite: `contracts/fixtures/person/crossref/` (same verdicts as
  `tests/contracts/_people_lib.permits`, plus the stricter S1 to S5 and grants G1, G2 in API.md).
- Emits no event and writes no outbox entry; callers do.

## Config
- None. Time zones come from person records (`tzdata` package, so Windows and slim images agree).

## Requirement IDs
FR-MTG-05, FR-PA-01, FR-PA-11, FR-PA-17, FR-PB-01, FR-PB-02, FR-PB-04 to FR-PB-07,
FR-CAL-03, FR-CAL-06 (oracle half); PPL-10a to PPL-10d.

## Local rules
- Pure: no model, provider, network, randomness, logging, print or clock read under `src/`.
  `now` and `meeting_at` are the only time sources.
- Validate with `tilo_policy.schemas.conforms`, never the generated pydantic models.
- Fail closed: `decide` and `check_write` never raise; unknown or malformed input refuses.
- Never put record text (titles, names, aliases, emails, due phrases) in an error or a repr.
- A model never resolves identity, dates or access: code only (PE-15, PE-11).
- `check_write` lets a meeting's `world_id` go from absent to a world id as an owner `edit`, alone and once (PPL-11c S6, BQ-273); any other `world_id` change is `immutable`.
- Change `decide` only together with the reference oracle and the crossref fixtures (architect).
