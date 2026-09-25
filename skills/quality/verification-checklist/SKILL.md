# Verification checklist

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to give every claim in a deliverable a verdict against supplied evidence, before the deliverable goes out (PRD 13.3: "Why is this here?" depends on this).

## Steps

1. Read `inputs.deliverable_claims` (claim_id, text) and `inputs.evidence` (source_id, text).
2. Give every claim exactly one verdict: `verified` (evidence supports it), `unverified` (no evidence either way), or `false` (evidence contradicts it). Never drop a claim.
3. Cite evidence only by ids that were actually supplied in `inputs.evidence`; never invent one.
4. A `verified` verdict must cite at least one evidence id — a bare assertion is not enough.

## Quality bar

- `ids-missing`: every claim must have exactly one verdict; a duplicate or an unrecognised claim id fails the same underlying check.
- `verdict-invalid`: verdict must be exactly one of verified, unverified, false.
- `evidence-unknown`: every cited evidence id must be one of the supplied evidence entries.
- `verified-needs-evidence`: a verified verdict must cite at least one evidence id.

## Checklist

- [ ] Every claim has exactly one verdict.
- [ ] Verdict is exactly one of the three allowed values.
- [ ] Every cited evidence id was actually supplied.
- [ ] Every verified claim cites at least one evidence id.

## Pitfalls

- Dropping a claim that was hard to verify instead of marking it unverified.
- Marking a claim verified on the strength of the claim's own wording rather than the evidence.
- Citing an evidence id that sounds plausible but was never in `inputs.evidence`.
- Treating "no evidence found yet" as false rather than unverified.
