---
name: api-route-attack-patterns
description: services/api (tilo_api) attack patterns that found real bugs - mutate-before-lookup in bulk loops, vis lists leaking hidden district ids, O(n) next_seq
metadata:
  type: project
---

Found on ST-3a (FR-HIL-07/09, SEC-07), 2026-09-25:
- Bulk kill-switch loops mutated policy (history/level) BEFORE looking up `store.policy_worlds[pid]`; an org-level policy with no world mapping -> KeyError 500 mid-loop, later policies stay L2, orphan changed with no event. Always seed one unmapped / malformed record among good ones and check partial state.
- Events visible via one district still carry the full `vis` list, exposing hidden district ids to viewers.
- `next_seq` scans the whole stream per event: 2000 policies x 10k events ~5 s.

**Why:** these routes are side-effect paths with honesty rules; partial commits without events are the worst class.
**How to apply:** for any bulk mutation route, drive it with TestClient + raise_server_exceptions=False and diff store state after a 500. Scratch scripts need PYTHONIOENCODING=utf-8 on Windows. See [[policy-engine-attack-patterns]].
