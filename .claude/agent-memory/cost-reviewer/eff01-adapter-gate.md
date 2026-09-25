---
name: eff01-adapter-gate
description: EFF-01 gate must live in the adapters, not only the factory/replay wrapper; P0-05 adapters built real clients with LIVE unset until d838fe6
metadata:
  type: project
---

P0-05 review (2026-09-25): at first, LIVE=1 was checked only in `RecordReplayProvider`. `GoogleModelProvider(client=None)` and `OpenAICompatModelProvider(transport=None)` built real network clients with LIVE unset. A probe reached integrate.api.nvidia.com.

The fix took four reviews: builders fixed the other findings (secret scrubbing, https-only) and left the gate. Name the gate fix explicitly in any verdict. It was fixed at d838fe6, where both constructors raise ProviderError before building a client, and that review passed.

**Why:** a gate only in the wrapper is bypassed by any direct adapter construction. EFF-01 says no code path, so this counts.

**How to apply:** in any provider, search, safety or speech adapter review:
- Run a scratchpad probe that constructs the adapter directly with LIVE unset and no injected transport. Expect a refusal before a client exists.
- Check that TILO_RECORD=1 without LIVE still hits ReplayMissError and builds no live provider.
- Check that the CI hosts-file block covers every endpoint host.
- If the HEAD sha is unchanged since the last review, re-verify quickly instead of doing a full review.
