# Invoice / PO matching

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to match invoice lines to purchase-order lines and recompute both totals; it only matches and reports — it never approves or pays anything.

## Steps

1. Read `inputs.invoice_lines` and `inputs.po_lines` (each line_id, amount, description).
2. Give every invoice line and every PO line exactly one row in `output.matches`; a line with no counterpart still gets a row (`unmatched`, with the other side's id null).
3. Mark a pair `matched` when the amounts agree, `mismatched` when they do not, giving a `reason_code` (amount_mismatch or description_mismatch) for every mismatch.
4. Recompute `invoice_total` and `po_total` by summing the respective lines' amounts — never from a number typed by hand.

## Quality bar

- `ids-missing`: every invoice line and every PO line must appear in exactly one match row; a duplicate or an unrecognised id fails the same underlying check.
- `status-invalid`: status must be exactly one of matched, mismatched, unmatched.
- `reason-code-invalid`: a mismatched row must give a reason_code of amount_mismatch or description_mismatch.
- `totals-mismatch`: invoice_total and po_total must recompute exactly from the supplied lines.

## Checklist

- [ ] Every invoice line and PO line appears in exactly one match row.
- [ ] Status is exactly one of the three allowed values.
- [ ] Every mismatched row gives a reason code.
- [ ] Both totals recompute exactly from the supplied lines.

## Pitfalls

- Leaving a line out of `matches` because it had no obvious counterpart — it still needs an `unmatched` row.
- Marking a pair `matched` when the amounts actually differ, because they were "close enough".
- Reporting a total that "looks right" instead of summing the lines exactly.
- Approving or acting on a match from within this skill — matching is a read-only report, not an approval.
