---
name: router-real-factory-path-probe
description: Router tests inject scripted providers only; probe Router(config, fixtures_dir=...) on real config to hit RecordReplayProvider stubs
metadata:
  type: feedback
---

Router tests (packages/providers/tests/conftest.py) inject ScriptedModelProvider via provider_for_profile, so the real
factory path (build_provider -> RecordReplayProvider) is never exercised. In P0-06 review, Router.embed on the real
config raised a raw NotImplementedError from RecordReplayProvider.embed ("lands with the router ticket P0-06"), with the
attempt left recorded as "ok".

**Why:** stubs deferred to "the router ticket" by earlier tickets are easy to leave behind when every test mocks the provider.
**How to apply:** for provider-layer tickets, grep for NotImplementedError / "lands with" mentioning the ticket, and run a
scratchpad probe with the worktree venv against config/models.yaml in replay mode. Related: [[provider-error-base-class]].
