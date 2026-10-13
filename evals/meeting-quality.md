# E-MEET offline quality rubric (FR-MTG-03/04)

Source: `docs/prd-addendum-people-agents.md`, FR-MTG-03/04 and section 5. This evaluator grades saved outputs and independent annotations. It never generates minutes, calls a provider, sends a message, or enables a meeting route/job.

The existing 12 scripted API acceptance cases prove plumbing. The recorded Meet HTML fixtures prove DOM handling, not minutes quality. No provider-output corpus was found in the lane checkout; provider quality remains **pending**.

## Frozen thresholds

Use 12 distinct transcripts. Minutes/transcripts must validate against the existing contracts; meeting IDs must agree; verified items must cite existing utterances. Action recall >= 85%, precision >= 90%, agenda coverage 100%, zero invented commitments, dates correct, ambiguous names never auto-assigned. Planted false items must be caught/marked >= 90% (FR-MTG-04). Summary scores must each be >= 4/5. Duplicate action matches consume prediction slots, never increase recall.

## Independent annotation

Before inspecting the output, label gold action IDs and expected agenda rows from the transcript. Afterward map each predicted action ID to one gold ID or null. Evaluate semantic paraphrases manually; do not require identical wording. Mark invented commitments (including decisions), incorrect dates and unsafe ambiguous name assignments. List planted-false action IDs, including missing items: silently dropped items do not count as caught. Review all factual summary claims and citations.

Summary rubric: 1 = unusable/invented; 2 = major omissions or unsupported claims; 3 = mostly accurate but material omission/unclear phrasing; 4 = grounded, concise, captures every important decision and next step; 5 = all of 4 with excellent clarity and prioritisation. A missing independent score is pending, never a zero or a pass. The producer cannot review its own output. No autorater executes in this evaluator.

## Offline bundle

JSON is an array of cases with `id`, `basis` (`scripted_fakes` or `recorded_provider`), contract-shaped `transcript` and `minutes`, `gold` (`action_ids`, `agenda`, `summary_score`, `planted_false_ids`), and `annotation` (`action_matches`, `invented_commitment_ids`, `dates_correct`, `ambiguous_names_safe`). IDs/annotations are local evaluator data, not new contracts. All verified action IDs need a mapping. Gold IDs are unique; empty gold corpora have unavailable action metrics and cannot pass.

Recorded cases additionally carry `provenance`: `producer`, independent `reviewer`, and `recording_sha256`: SHA-256 of UTF-8 canonical JSON with keys `transcript` and `minutes` (`sort_keys=True`, `separators=(',', ':')`). This binds reviewed content; the hash does not prove a provider was called. The reviewer must inspect original provider-layer recording/capture metadata before asserting `recorded_provider`. Keep real transcripts and capture files in approved private storage; never commit meeting content, credentials or tokens. Existing consent/retention/privacy gates apply.

Run `uv run python -m tilo_evals.meeting_quality <private-bundle.json>`. The report contains aggregate counts/metrics only, never meeting text or identifiers. Exit 0 = supplied recorded evidence meets the rubric, 1 = failed rubric, 2 = pending/malformed. Scripted and recorded metrics are never pooled. Synthetic reports always keep provider quality pending, even when mechanics pass. This is offline rubric evidence, not supervisor readiness/security approval, live voice acceptance, actual spend measurement, or permission to activate providers.
