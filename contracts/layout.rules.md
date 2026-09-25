# WorldLayout rules beyond the schema (layout.schema.json v1)

PRD 9.2 says validation rules WE-01 to WE-16 "carry over from v1 unchanged in intent", but the
v1 list is not in the repo (**BQ-02**, `docs/open-questions.md`). Until the user supplies it,
the rules below are derived from the one-sentence summary in PRD 9.2 plus the limits in 9.1.
The numbering is ours, not v1's: when the v1 list arrives, map it here and record any change in
an ADR. Rules marked "schema" are already enforced by `layout.schema.json`; the rest belong to
the deterministic layout validator. A layout that fails goes back to the model for up to two
repairs, then to the deterministic fallback layout.

| Rule | Rule | Checked by |
| --- | --- | --- |
| WE-01 | Tier matches the agent count in `semantic.agents`: outpost 1-2, village 3-6, town 7-15, city 16+. | validator |
| WE-02 | Every plan unit maps to exactly one building: the `plan_units` lists together hold each unit id of the plan once. | validator |
| WE-03 | No decorative buildings: a kit building has at least one plan unit (schema); a common building without plan units stands for a platform function the run uses (for example Town Hall for the Director, Treasury for the budget). Gap: v1's list of which functions imply which common buildings. | schema + validator |
| WE-04 | Every external system has an island: each connector or channel the plan uses has exactly one island, and every island is used by the plan. | validator |
| WE-05 | Every side effect has a gate: each plan gate has a layout gate with the same id, `guards` equal to its action type and `between` = [the building of a guarded unit, the island of the connector that performs the action]. | validator |
| WE-06 | Roads equal plan dependencies: `geometry.roads` holds one edge per `depends_on` edge between units in different buildings, from the dependency's building to the dependant's building, and no other edges. | validator |
| WE-07 | Names are 2-24 plain characters (`common.schema.json#/$defs/plain_name`). | schema |
| WE-08 | Kit parts and icons come from the published lists for the theme (`config/themes/<theme>`). Gap: the lists are not published yet. | validator |
| WE-09 | Tints come from the solver: the semantic part carries no colours, and `geometry` tints are district role ids `district.1` to `district.6`. | schema |
| WE-10 | Unknown event types render in the Trace only (HR-5); the world never animates them. | renderer |
| WE-11 | Replay determinism: the solver is a pure function of `semantic` and `solver_version`, and replaying the same layout and events always yields the same frame. | solver tests |
| WE-12 | Structure follows 9.1 and 8.1: at most 6 districts per level and 5 buildings per district (schema); exactly one director; each district's `lead` is an agent of rank lead. | schema + validator |
| WE-13 | Ids are unique per kind (levels, districts, buildings, islands, gates, agents), every reference resolves (`lead`, `between`, `team_lead`), and every geometry entry matches a semantic entry one to one. | validator |
| WE-14 | The connection fixes the bridge: api road, mcp rail, browser footpath, channel pier. | schema |

WE-15 and WE-16 are left unassigned until the v1 list is available (BQ-02).
