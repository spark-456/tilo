# Quote comparison

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to compare several supplier quotes against a stated set of requirements, and recommend one only if it actually covers every must-have requirement. Use it with quotes that already carry a ground-truth `meets` mapping (from research or the supplier's own quote); this skill compares and totals, it does not judge coverage from free text.

## Steps

1. Read `inputs.requirements` (each with a `requirement_id` and whether it is `must_have`) and `inputs.quotes` (each with `line_items` and a `meets` map from requirement id to met/partial/missing).
2. Build the `coverage_matrix`: one row per quote per requirement, with the status copied faithfully from that quote's `meets` map (missing if the quote did not address it). Never invent or soften a status.
3. Recompute each quote's `total_cost` yourself as the exact sum of quantity times unit price across its line items, citing the quote's own `source_id`.
4. A quote qualifies for recommendation only if it is `met` on every must-have requirement. Partial does not count as met, even if it is close.
5. Recommend the qualifying quote (any one, or the cheapest if several qualify); if none qualifies, `recommendation` is `null` and says so — never recommend a quote that misses a must-have.

## Quality bar

- `coverage-matrix-incomplete`: the coverage matrix must have exactly one row per quote x requirement pair, matching the quote's own meets data.
- `total-not-recomputed`: every total_cost must equal the exact recomputed sum of quantity times unit price, citing the quote's own source id; totals must have exactly one row per input quote — a missing or duplicated row fails too.
- `recommendation-fails-must-have`: a recommendation must meet every must-have requirement.
- `recommendation-should-be-null`: recommendation must be null when no quote meets every must-have requirement.
- `output-malformed`: the output must be an object with coverage_matrix, totals and recommendation; malformed shapes fail closed.

## Checklist

- [ ] Every quote x requirement pair appears in the coverage matrix with its true status.
- [ ] Every total is recomputed exactly from the quote's own line items.
- [ ] The recommendation, if any, meets every must-have requirement.
- [ ] Recommendation is null, and says so, when nothing qualifies.

## Pitfalls

- Rounding "partial" up to "met" because a quote is close on a must-have requirement.
- Recommending the cheapest quote overall instead of the cheapest quote that actually qualifies.
- Leaving a requirement out of the coverage matrix because a quote did not mention it — silence means missing, not omitted.
- Trusting a quote's own stated total instead of recomputing it from line items.
