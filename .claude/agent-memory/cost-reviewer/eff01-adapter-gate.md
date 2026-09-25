---
name: eff01-adapter-gate
description: EFF-01 gate must live in the adapters, not only the factory/replay wrapper; P0-05 adapters built real clients with LIVE unset
metadata:
  type: project
---

P0-05 review (2026-09-25): LIVE=1 was checked only in `RecordReplayProvider`. `GoogleModelProvider(client=None)` and `OpenAICompatModelProvider(transport=None)` built real network clients with LIVE unset. The factory even told callers to construct openai_compat directly. A probe reached integrate.api.nvidia.com and got HTTP 404.

Re-review at ca3157b: three fix commits later the gap was still there. The fixes addressed secret scrubbing and https only, not the LIVE gate. Name the gate fix explicitly in the verdict, because builders fix the other findings and leave this one.

**Why:** a gate only in the wrapper is bypassed by any direct adapter construction. EFF-01 says no code path, so this counts.

**How to apply:** in any provider, search, safety or speech adapter review, run a probe that constructs the adapter directly with LIVE unset and no injected transport. Expect a refusal before a client exists. Also check that a CI hosts-file block covers every endpoint host.

Third review at ca3157b (same head, 2026-09-25): gate still missing in both adapters; also `test_PL_02_nim_profiles_load_through_the_same_loader_and_denylist` fails (base_url/api_key_env rejected as extra fields by ProvidersModels), so the NIM profile shape likely needs a contract change.

Fourth review (still ca3157b, 2026-09-25): no new commits; same two defects. If the head is unchanged, check the HEAD sha first and re-verify quickly instead of a full re-review.
