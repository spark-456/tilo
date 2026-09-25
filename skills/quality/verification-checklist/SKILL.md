# Verification checklist

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill as the independent Verifier step (FR-AGT-12) before a deliverable ships: give every claim it makes a verdict, backed by evidence, so "Why is this here?" (PRD 13.3) can always point at a real source. Run it independently of whoever wrote the deliverable — never rubber-stamp claims just because they read plausibly.

## Steps

1. Read `inputs.deliverable_claims` (one claim per row) and `inputs.evidence` (the supplied source passages).
2. For every claim, search the evidence for something that actually supports or contradicts it.
3. If the evidence directly supports the claim, mark it `verified` and cite every evidence `source_id` that supports it — never an empty list, never an id that was not supplied.
4. If the evidence contradicts the claim, mark it `false` and cite the contradicting evidence.
5. If nothing in the evidence settles it either way, mark it `unverified`. Do not guess a verdict to look more thorough than the evidence allows.
6. Cover every claim exactly once. Never drop a claim from `verdicts`, and never verdict the same claim twice.

## Quality bar

- `verdict-invalid`: verdict must be exactly one of verified, unverified, false.
- `verified-needs-known-evidence`: a verified verdict must cite at least one evidence source id that is actually present in the inputs; a false verdict that cites evidence must cite only ids present in the inputs too.
- `claim-not-covered`: every claim in deliverable_claims must have exactly one verdict row; nothing dropped, nothing duplicated, and no verdict for a claim_id that was not in the inputs.
- `output-malformed`: the output must be an object with a verdicts array of claim_id/verdict/evidence_source_ids objects; malformed shapes fail closed.

## Checklist

- [ ] Every input claim has exactly one verdict.
- [ ] Every verified verdict cites evidence that is actually in the inputs.
- [ ] A claim contradicted by the evidence is marked false, not unverified.
- [ ] Nothing was verdicted "verified" on a guess or a plausible-sounding match.

## Pitfalls

- Marking a claim verified because it sounds right, without a specific evidence passage that actually says so.
- Citing an evidence id that looks relevant but was never supplied in the inputs.
- Dropping a claim that seemed too minor to check, instead of giving it an unverified verdict.
- Treating "the evidence doesn't mention it" the same as "the evidence confirms it" — that is unverified, not verified.
