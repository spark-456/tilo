---
name: import-keeps-old-created-at
description: Imported artifact records keep the source created_at, so ArtifactStore GRACE/_settle logic treats a mid-write import as interrupted and purges it
metadata:
  type: project
---

FR-MEM-10 `ArtifactStore.import_version` keeps the bundle's `created_at` (EV-15). `_settle` decides "still being written"
by `clock - created_at <= GRACE`, so an imported record whose blob is not yet written looks long-interrupted and is purged
by a concurrent import of the same version.

**Why:** any store logic keyed on `created_at` freshness assumes the store minted the time; imports break that.
**How to apply:** when reviewing code that writes records with caller-supplied times (imports, restores, migrations),
probe every freshness/grace check that reads those times. See [[timeout-then-late-commit-probe]].
