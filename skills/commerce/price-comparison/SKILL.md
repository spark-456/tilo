# Price comparison

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to compare offers for one item, normalise each to a common unit price, and pick the cheapest offer that actually meets every stated requirement.

## Steps

1. Read `inputs.item`, `inputs.requirements` (field/op/value), `inputs.currency`, `inputs.rates` and `inputs.offers`.
2. For every offer, compute its unit price in the target currency from `price`, the offer's own `rates` entry, and `unit_count` — never from a number typed by hand. Give every supplied offer its own row in `output.unit_prices`.
3. An offer "meets" the requirements only when every one of `inputs.requirements` is satisfied against that offer's own fields, using the stated `op` exactly (eq/gte/lte/gt/lt/in).
4. Pick the cheapest offer, by its recomputed unit price, among the offers that meet every requirement. If none meet every requirement, `pick` is null — never pick the cheapest overall offer as a fallback.
5. `pick.source_id` must be that same offer's own `source_id`, never a different offer's.

## Quality bar

- `ids-missing`: every supplied offer must have exactly one row in `output.unit_prices`.
- `unit-price-mismatch`: a unit_prices row must recompute exactly from that offer's price, currency rate and unit count, to 4 decimal places, and carry that offer's own source_id.
- `pick-requirement-fail`: the pick must be an offer that meets every stated requirement, and its source_id must match that offer's own.
- `pick-not-cheapest`: the pick must be the cheapest offer among those that meet every requirement (or null when none do).

## Checklist

- [ ] Every offer has a unit_prices row, recomputed from the offer and rates, never invented.
- [ ] The pick meets every stated requirement, or is null if none do.
- [ ] The pick is the cheapest offer among the ones that qualify, not merely cheap.
- [ ] pick.source_id matches the picked offer's own source_id.

## Pitfalls

- Picking the cheapest offer overall without checking it against every stated requirement.
- Reporting a unit price that "looks about right" instead of recomputing it from price, rate and unit count.
- Leaving out an offer's unit_prices row because it was clearly not going to be picked.
- Copying the wrong offer's source_id onto the pick.
