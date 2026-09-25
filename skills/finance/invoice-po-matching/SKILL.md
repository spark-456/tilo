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

- `mismatch-missing-reason`: every match that is not "matched" must carry a reason_code.
- `item-mismatch-not-flagged`: a pair marked matched must actually have the same item on both sides.
- `quantity-outside-tolerance-not-flagged`: a pair marked matched must be within the stated quantity tolerance.
- `total-not-recomputed`: invoice_total and po_total must equal the exact recomputed sum of quantity times unit price.
- `unexpected-approval-field`: the output must never carry an approval, payment or authorisation field.
- `output-malformed`: the output must be an object with matches, invoice_total and po_total; malformed shapes fail closed.

## Checklist

- [ ] Every non-matched line has a reason code.
- [ ] Every matched pair has the same item on both sides.
- [ ] Every matched pair's quantities are within the stated tolerance.
- [ ] Both totals are recomputed exactly, not copied from either document.
- [ ] The output contains no approval or payment field.

## Pitfalls

- Trusting a total printed on the invoice or PO instead of recomputing it from the lines.
- Marking two lines matched because the amounts look close, without actually comparing items or checking the tolerance.
- Rounding the recomputed total for a "cleaner" number, which breaks exact-match totals.
- Adding a convenience "approved" or "ready_to_pay" flag — this skill only matches; it never authorises payment.
