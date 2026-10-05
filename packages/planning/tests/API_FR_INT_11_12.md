# FR-INT-11 and FR-INT-12: the public interface these tests pin

Tickets FR-INT-11 (scenario configs) and FR-INT-12 (refusal of out-of-policy tasks), PRD 7.1, 4.3, 16.
The tests import only what is listed here; the builder implements it exactly. `needs contract change:`
`contracts/scenario.schema.json` (the shape of `config/scenarios/<id>.yaml`) belongs to the architect; the tests
below pin behaviour through the loader, so they hold for whatever schema is written.

## FR-INT-11: `tilo_planning.scenarios`

```python
class ScenarioError(Exception): ...        # any bad file, id or reference; the message names the offender

def load_scenario(scenario_id: str, *, repo_root: Path = <repo root>, skill_ids: Collection[str] | None = None) -> Scenario
def smoke_test(scenario: Scenario, *, repo_root: Path = <repo root>) -> list[str]   # problems; [] means it passes

class Scenario:   # frozen
    id: str; title: str
    skills: Sequence[str]            # skill ids (common.schema.json skill_id), non-empty
    connectors: Sequence[str]        # ids in <repo_root>/config/connectors.yaml
    seed_data: Sequence[Path]        # absolute paths of existing files inside repo_root
    theme: str                       # slug; no config/themes/ exists yet, so only the shape is checked
    autonomy: Sequence[dict]         # the file's policy entries, as written
    def policies(self, *, owner: str, at: str) -> list[dict]   # policy.schema.json records
```

- **File:** `<repo_root>/config/scenarios/<id>.yaml`. The id matches `[A-Za-z][A-Za-z0-9_-]{0,31}` (anything else, a
  path included, is a `ScenarioError` before any file is read); the file's `id` equals its name. YAML is
  `safe_load`ed; an empty file, a non-mapping, a tag, an unknown key or a missing key is a `ScenarioError`.
- **Keys:** `id`, `title`, `skills` (list of skill ids), `connectors` (list), `seed_data` (list of repo-relative
  paths), `theme`, `autonomy` (list, may be empty or absent), each entry `{action_type, level, connectors,
  per_day?, undo_window_s?}`.
- **Checks:** every connector is in the registry; every seed path stays inside `repo_root` (no `..`, no absolute
  path) and exists; `skill_ids`, when given, contains every skill; every autonomy entry has a level within
  `max_level[tier(action_type)]` of `<repo_root>/config/autonomy.yaml` (an unlisted action is T3, BQ-44), a
  `per_day` for L2 and L3 (`policy.schema.json`), and `connectors` drawn from the scenario's own list (or
  `internal`).
- **`policies(owner, at)`:** one record per entry: `owner`, `created_by = {by: owner, at}`, one history entry,
  `notify_channel` `web`, `expiry` null, empty `team_lead_domains` and scope lists except `connectors`, all
  three conditions true, a unique `pol_` id. Only the owner creates a policy (PRD 10.1), so the caller passes the
  signed-in owner, never the file.
- **`smoke_test`:** re-resolves every reference against `repo_root` as it is now and parses every seed file
  (`.yaml`/`.yml`, `.json`, `.csv`); each problem is one string naming the offender.
- **No scenario code:** no `packages/*/src` or `services/*/src` file names a scenario id.
- **Not pinned:** skill resolution against the real `skills/` catalog for SC-01 (FR-AGT-04 is not merged; BQ-202).

### API (`services/api`)

`POST /intake` takes an optional form field `scenario`. An unknown or malformed id is 422 with nothing stored. The
201 body gains `scenario` (the id, or null). Nothing is created at intake. `POST /tasks/{id}/approve` then creates
each `Scenario.policies(owner=<principal>, at=<now>)` record in `Store.policies`, maps it in `Store.policy_worlds`,
and writes one `policy.changed` (`change: created`, authz person = the owner) per policy; a second approve adds
none. The API calls `tilo_planning.scenarios.load_scenario` and nothing scenario-specific.

## FR-INT-12: `tilo_planning.refusal`, `extract_brief`, `POST /intake`

```python
class RefusalConfigError(Exception): ...

DEFAULT_REFUSAL_CONFIG = <repo>/config/out_of_policy.yaml
def load_refusal_policy(path: Path | None = None) -> RefusalPolicy   # None: the default file
class RefusalPolicy:  categories: Sequence[RefusalCategory]          # file order
class RefusalCategory: id: str; reason: str; alternative: str
class TaskRefused(Exception): category: str; reason: str; alternative: str   # str(exc) holds no task text

tilo_planning.brief.extract_brief(task_text, *, router, budget=None, refusal_policy: RefusalPolicy | None = None)
```

- **Config:** `config/out_of_policy.yaml`: `categories: [{id (slug), reason, alternative}]`; at least one
  category; ids unique; reason and alternative non-empty, different from each other and at most 400 characters; no
  other keys. The shipped file has at least five (credentials, a send without approval, bypassing the approval
  gate or the safety screen, deception, bulk or unsolicited sending, and so on, from PRD 10.4, 16.1, 16.3).
- **Director reply:** the brief JSON gains an optional key `out_of_policy`: `null`, or a category id. A reply
  without the key means in policy, so every existing scripted reply and the dev Director keep working. A non-null
  id that is not a category, or any non-string, is a `BriefExtractionError` (fail closed; never a brief).
- **Refusal:** a category id raises `TaskRefused` with the category's configured reason and alternative: the text a
  person reads comes only from config, never from the model or the task. It wins over any brief in the same reply.
  One Director call; no questions or approaches follow. `refusal_policy=None` loads the default file.
- **HTTP:** `POST /intake` answers a refusal 422 `{"error": <reason>, "alternative": <alternative>, "category":
  <id>}` and stores nothing (no artifact, task, world or event). An unknown category is 502, like any unusable
  Director reply. Limits and the safety screen still run first (an empty task is the old 422, no model call).
- **Eval refusal set:** `packages/planning/tests/fixtures/refusal_set.yaml` (24 out-of-policy and 12 ordinary
  tasks). The Director is scripted; the set proves the code refuses and states the alternative every time. How
  often a real model picks the right category is a live-eval question (EFF-06, a refusal group added to PRD 19.2
  by the owner), not a unit test.
