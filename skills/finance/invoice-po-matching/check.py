"""Deterministic quality-bar checker for finance/invoice-po-matching.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

_DISALLOWED_KEYS = {"approved", "approved_for_payment", "payment_status", "paid", "authorization", "authorisation"}


def _dec(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]
    matches = output.get("matches")
    invoice_total = output.get("invoice_total")
    po_total = output.get("po_total")
    if not isinstance(matches, list) or invoice_total is None or po_total is None:
        return [{"check": "output-malformed", "detail": "output must have matches (array), invoice_total and po_total"}]

    findings: list[dict] = []
    if _DISALLOWED_KEYS & set(output.keys()):
        findings.append(
            {
                "check": "unexpected-approval-field",
                "detail": "matching output must never carry an approval or payment field (matching only)",
            }
        )

    inputs = inputs if isinstance(inputs, dict) else {}
    invoice = inputs.get("invoice") if isinstance(inputs.get("invoice"), dict) else {}
    po = inputs.get("purchase_order") if isinstance(inputs.get("purchase_order"), dict) else {}
    inv_lines_raw = invoice.get("lines") if isinstance(invoice.get("lines"), list) else []
    po_lines_raw = po.get("lines") if isinstance(po.get("lines"), list) else []
    inv_lines = {line.get("line_id"): line for line in inv_lines_raw if isinstance(line, dict)}
    po_lines = {line.get("line_id"): line for line in po_lines_raw if isinstance(line, dict)}
    tolerance_pct = inputs.get("quantity_tolerance_pct")
    tolerance_pct = (
        tolerance_pct if isinstance(tolerance_pct, (int, float)) and not isinstance(tolerance_pct, bool) else 0
    )

    inv_line_id_counts: dict[str, int] = {}
    po_line_id_counts: dict[str, int] = {}

    for i, match in enumerate(matches):
        if not isinstance(match, dict):
            findings.append({"check": "output-malformed", "detail": f"matches[{i}] is not an object"})
            continue
        status = match.get("status")
        reason = match.get("reason_code")
        if status != "matched" and not reason:
            findings.append(
                {"check": "mismatch-missing-reason", "detail": f"matches[{i}] status {status!r} has no reason_code"}
            )

        raw_invoice_line_id = match.get("invoice_line_id")
        invoice_line_id = raw_invoice_line_id if isinstance(raw_invoice_line_id, str) else None
        if invoice_line_id is None:
            findings.append({"check": "output-malformed", "detail": f"matches[{i}].invoice_line_id must be a string"})
        else:
            inv_line_id_counts[invoice_line_id] = inv_line_id_counts.get(invoice_line_id, 0) + 1

        raw_po_line_id = match.get("po_line_id")
        po_line_id = raw_po_line_id if isinstance(raw_po_line_id, str) else None
        if raw_po_line_id is not None and po_line_id is None:
            findings.append(
                {"check": "output-malformed", "detail": f"matches[{i}].po_line_id must be a string or null"}
            )
        elif po_line_id is not None:
            po_line_id_counts[po_line_id] = po_line_id_counts.get(po_line_id, 0) + 1

        inv_line = inv_lines.get(invoice_line_id) if invoice_line_id is not None else None
        po_line = po_lines.get(po_line_id) if po_line_id is not None else None
        if status == "matched":
            if inv_line is None or po_line is None:
                findings.append(
                    {
                        "check": "item-mismatch-not-flagged",
                        "detail": f"matches[{i}] is marked matched but references a missing invoice or PO line",
                    }
                )
                continue
            if str(inv_line.get("item", "")).strip().lower() != str(po_line.get("item", "")).strip().lower():
                findings.append(
                    {"check": "item-mismatch-not-flagged", "detail": f"matches[{i}] items differ but is marked matched"}
                )
            inv_qty, po_qty = inv_line.get("quantity"), po_line.get("quantity")
            if (
                isinstance(inv_qty, (int, float))
                and not isinstance(inv_qty, bool)
                and isinstance(po_qty, (int, float))
                and not isinstance(po_qty, bool)
                and po_qty
            ):
                diff_pct = abs(inv_qty - po_qty) / abs(po_qty) * 100
                if diff_pct > tolerance_pct:
                    findings.append(
                        {
                            "check": "quantity-outside-tolerance-not-flagged",
                            "detail": (
                                f"matches[{i}] quantity differs by {diff_pct:.2f}% beyond the "
                                f"{tolerance_pct}% tolerance but is marked matched"
                            ),
                        }
                    )

    for line_id in inv_lines:
        count = inv_line_id_counts.get(line_id, 0)
        if count != 1:
            findings.append(
                {
                    "check": "line-not-covered",
                    "detail": f"invoice line {line_id!r} appears in {count} match row(s), expected exactly 1",
                }
            )
    for line_id in po_lines:
        count = po_line_id_counts.get(line_id, 0)
        if count != 1:
            findings.append(
                {
                    "check": "line-not-covered",
                    "detail": f"PO line {line_id!r} appears in {count} match row(s), expected exactly 1",
                }
            )

    inv_sum = sum(
        (_dec(line.get("quantity")) or Decimal(0)) * (_dec(line.get("unit_price")) or Decimal(0))
        for line in inv_lines.values()
    )
    po_sum = sum(
        (_dec(line.get("quantity")) or Decimal(0)) * (_dec(line.get("unit_price")) or Decimal(0))
        for line in po_lines.values()
    )
    declared_invoice_total = _dec(invoice_total)
    declared_po_total = _dec(po_total)
    if declared_invoice_total is None or declared_invoice_total != inv_sum:
        findings.append(
            {
                "check": "total-not-recomputed",
                "detail": f"invoice_total {invoice_total!r} does not equal the exact recomputed sum",
            }
        )
    if declared_po_total is None or declared_po_total != po_sum:
        findings.append(
            {
                "check": "total-not-recomputed",
                "detail": f"po_total {po_total!r} does not equal the exact recomputed sum",
            }
        )
    return findings
