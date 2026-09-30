---
name: split-pr-leftovers
description: When a PR is split out of a bigger branch, the sibling ticket's scaffolding (writers, fixtures, fields) stays behind, justified only by other code in the same diff
metadata:
  type: project
---

PR #54 (FR-HIL-09/SEC-07, split from #39 FR-HIL-07) kept EventWriter/get_event_writer, FakeEventWriter, the `writer` fixture, WorldRecord.run_id and Principal.domain even though no route in the PR used them. The docstrings said "kept because conftest wires it up", but conftest was part of the same diff, so the reason pointed back at the PR itself. The same PR also changed the mypy `exclude` to `conftest\.py$` for the whole repo, which silently dropped the existing packages/providers conftest from typecheck.

**Why:** Split branches get trimmed by deleting routes, not by tracing what they depended on.
**How to apply:** On any split PR, grep every new dataclass field, Protocol and fixture for a reader in src or a direct test use. Flag "kept because X uses it" when X is in the same diff. Check that config excludes are scoped to the new file only.
