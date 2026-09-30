# Quote comparison

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to compare supplier quotes against a fixed set of requirements, with a coverage row for every (quote, requirement) pair and a recomputed total per quote.

## Steps

1. Read `inputs.requirements` (requirement_id, must_have) and `inputs.quotes` (quote_id, source_id, line_items).
2. Give every (quote, requirement) pair exactly one coverage row, with `status` one of met/partial/missing; never invent a row for a quote or requirement id that was not supplied.
3. Recompute every quote's total from its line items (quantity times unit price, summed) — or from an already-known `total` when the quote supplies one — never from a number typed by hand.
4. Recommend a quote only when it covers every must-have requirement (status `met` on each). If no quote does, `recommendation` is null.

## Quality bar

- `ids-unknown`: every coverage row's quote_id and requirement_id must be among the supplied quotes and requirements; a coverage row for an unknown quote or requirement fails, as does a missing pair.
- `ids-missing`: a required (quote, requirement) coverage pair, or a quote's row in the totals list, that the output leaves out fails the same way -- a quote whose total cannot be recomputed still needs a totals row, so the checker can flag it, not be silently excused from the requirement.
- `status-invalid`: coverage status must be exactly one of met, partial, missing.
- `totals-mismatch`: each quote's total must recompute exactly from its line items (or its own supplied total).
- `recommendation-invalid`: the recommendation must be a quote that meets every must-have requirement, or null when none does.

## Checklist

- [ ] Every (quote, requirement) pair has exactly one coverage row.
- [ ] No coverage row names a quote or requirement id that was not supplied.
- [ ] Every total recomputes exactly from the quote's own line items.
- [ ] The recommendation, if any, meets every must-have requirement.

## Pitfalls

- Leaving a (quote, requirement) pair uncovered because it seemed obviously "missing".
- Recommending the cheapest quote without checking it actually meets every must-have.
- Reporting a total that "looks right" instead of summing the line items exactly.
- Inventing a coverage row for a quote or requirement that was never in the input.
