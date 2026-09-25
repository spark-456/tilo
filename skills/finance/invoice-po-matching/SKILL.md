# Invoice-to-PO matching

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to match an invoice's lines against a purchase order's lines by item and quantity, and recompute both totals exactly. This is matching only — it never approves anything for payment; approval is a separate, gated step outside this skill.

## Steps

1. Read `inputs.invoice.lines`, `inputs.purchase_order.lines` and `inputs.quantity_tolerance_pct`.
2. For each invoice line, find the purchase-order line with the same item. Compare quantities: if they are within `quantity_tolerance_pct` of each other, the pair is `matched`; otherwise it is `mismatched`.
3. An invoice line with no corresponding PO line (by item) is `unmatched`.
4. Every line that is not `matched` needs a `reason_code` explaining why (for example `item_not_on_po`, `quantity_over_tolerance`, `price_differs`).
5. Recompute `invoice_total` and `po_total` yourself as the exact sum of quantity times unit price across all lines, using decimal arithmetic — never trust a total printed on the document, and never round during the sum.
6. Never add an approval, payment or authorisation field to the output. This skill reports matches; a person or a separate policy-gated step decides whether to pay.

## Quality bar

- `line-not-covered`: every invoice line and every PO line must appear in exactly one match row; a dropped or duplicated line fails this, even if the totals are otherwise correct.
- `mismatch-missing-reason`: every match that is not "matched" must carry a reason_code that is a real, non-empty string — not merely a truthy value (a list, an object or a NaN number is truthy but is not a usable reason and fails this too).
- `item-mismatch-not-flagged`: a pair marked matched must actually have the same item on both sides.
- `quantity-outside-tolerance-not-flagged`: a pair marked matched must be within the stated quantity tolerance.
- `total-not-recomputed`: invoice_total and po_total must equal the exact recomputed sum of quantity times unit price.
- `unexpected-approval-field`: the output must never carry an approval, payment or authorisation field.
- `input-malformed`: a line's quantity or unit_price that cannot be used as a bounded, finite number (the input schema allows any JSON number, including an absurd one such as a 400-digit quantity) fails closed instead of being computed with.
- `output-malformed`: the output must be an object with matches, invoice_total and po_total; malformed shapes fail closed.

## Checklist

- [ ] Every invoice line and every PO line appears in exactly one match row (nothing dropped, nothing duplicated).
- [ ] Every non-matched line has a reason code.
- [ ] Every matched pair has the same item on both sides.
- [ ] Every matched pair's quantities are within the stated tolerance.
- [ ] Both totals are recomputed exactly, not copied from either document.
- [ ] The output contains no approval or payment field.

## Pitfalls

- Returning `"matches": []` (or otherwise omitting a line) while still reporting correct-looking totals — every input line must show up in a match row, or a billed line that is not on the PO can be dropped silently.
- Trusting a total printed on the invoice or PO instead of recomputing it from the lines.
- Marking two lines matched because the amounts look close, without actually comparing items or checking the tolerance.
- Rounding the recomputed total for a "cleaner" number, which breaks exact-match totals.
- Adding a convenience "approved" or "ready_to_pay" flag — this skill only matches; it never authorises payment.
- Passing through a wildly out-of-range quantity or price unquestioned — a schema-valid number can still be absurd (for example a 400-digit quantity); treat it as unusable input, not as a real value to compute with.
