# finance/invoice-po-matching checker (FR-AGT-04).
from decimal import Decimal

from skills._lib import guard

_STATUSES = {"matched", "mismatched", "unmatched"}
_REASONS = {"amount_mismatch", "description_mismatch"}


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    inv_lines, po_lines = inputs.get("invoice_lines", []), inputs.get("po_lines", [])
    inv_by_id, po_by_id = guard.index_by(inv_lines, "line_id"), guard.index_by(po_lines, "line_id")

    is_list = isinstance(matches := output.get("matches"), list)
    inv_rows = [{"id": m.get("invoice_line_id")} for m in matches if isinstance(m, dict) and m.get("invoice_line_id")]
    po_rows = [{"id": m.get("po_line_id")} for m in matches if isinstance(m, dict) and m.get("po_line_id")]
    inv_rows, po_rows = (inv_rows, po_rows) if is_list else (matches, matches)
    findings = guard.ids_exactly_once(list(inv_by_id), inv_rows, "id")
    findings += guard.ids_exactly_once(list(po_by_id), po_rows, "id")

    for m in matches if is_list else []:
        bad_status = (status := m.get("status") if isinstance(m, dict) else None) not in _STATUSES
        findings += [guard.finding("status-invalid", f"status {status!r} invalid")] if bad_status else []
        reason_bad = status == "mismatched" and isinstance(m, dict) and m.get("reason_code") not in _REASONS
        reason_msg = f"reason {m.get('reason_code')!r} invalid" if isinstance(m, dict) else "reason invalid"
        findings += [guard.finding("reason-code-invalid", reason_msg)] if reason_bad else []

    inv_amt = [guard.parse_decimal(ln.get("amount")) if isinstance(ln, dict) else None for ln in inv_lines]
    po_amt = [guard.parse_decimal(ln.get("amount")) if isinstance(ln, dict) else None for ln in po_lines]
    bad_amt = None in inv_amt or None in po_amt
    findings += [guard.finding("amount-unparseable", "a line amount is not a valid number")] if bad_amt else []
    totals = output.get("totals") if isinstance(output.get("totals"), dict) else {}
    got_inv, got_po = guard.parse_decimal(totals.get("invoice_total")), guard.parse_decimal(totals.get("po_total"))
    wrong = not bad_amt and (got_inv != sum(inv_amt, Decimal("0")) or got_po != sum(po_amt, Decimal("0")))
    findings += [guard.finding("totals-mismatch", "totals do not recompute from the supplied lines")] if wrong else []
    return findings
