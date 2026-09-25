# Price comparison

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to compare several supplied offers for the same item and recommend the cheapest one that actually meets every stated requirement. Use it only with offers and exchange rates that were supplied in `inputs`; never fetch a live price or rate inside this skill (fetching is a separate research step feeding `offers`).

## Steps

1. Read `inputs.item`, `inputs.requirements`, `inputs.currency`, `inputs.rates` and `inputs.offers`.
2. For every offer, convert its price into `inputs.currency` using only `inputs.rates` (multiply the offer's price by the rate for its own currency), then divide by `unit_count` to get a true unit price. Never use an outside exchange rate.
3. Record each offer's unit price in `unit_prices`, citing the offer's `source_id` so the number can be traced back.
4. Check every offer against every entry in `inputs.requirements` using the stated `op` (`eq`, `gte`, `lte`, `gt`, `lt`, `in`). An offer that fails any one requirement does not qualify, no matter how cheap it is.
5. Pick the cheapest qualifying offer by unit price. If no offer meets every requirement, `pick` is `null` — never pick a disqualified offer because it is cheap.

## Quality bar

- `unit-price-mismatch`: every unit price must exactly recompute from the offer's price, currency, rate and unit count, and cite the offer's own source id and the target currency.
- `pick-meets-requirements`: the picked offer must satisfy every stated requirement.
- `pick-is-cheapest-qualifying`: the pick must be the cheapest offer that qualifies; if none qualify, pick must be null.
- `output-malformed`: the output must be an object with a unit_prices array and a pick; malformed shapes fail closed.

## Checklist

- [ ] Every unit price recomputes exactly from the supplied price, rate and unit count.
- [ ] Every unit price cites the offer's own source id.
- [ ] The pick, if any, passes every stated requirement.
- [ ] The pick is the cheapest offer that passes, not just the cheapest offer.
- [ ] Pick is null when nothing qualifies, never a disqualified cheap offer.

## Pitfalls

- Picking the lowest raw price instead of the lowest unit price (a bigger pack can look cheaper by sticker price alone).
- Silently dropping a requirement the cheapest offer fails, instead of disqualifying it.
- Using a rate not present in `inputs.rates`, or converting in the wrong direction.
- Returning a pick with no qualifying offer instead of null.
