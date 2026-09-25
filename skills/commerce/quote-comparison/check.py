# commerce/quote-comparison checker (FR-AGT-04).
from decimal import Decimal

from skills._lib import guard

_STATUSES = {"met", "partial", "missing"}


def _quote_total(quote: dict) -> Decimal | None:
    total = guard.parse_decimal(quote.get("total"))
    if total is not None:
        return total
    try:
        items = quote["line_items"]
        gen = (guard.parse_decimal(i["quantity"]) * guard.parse_decimal(i["unit_price"]) for i in items)
        return sum(gen, Decimal("0"))
    except Exception:  # noqa: BLE001 - a malformed line item just makes the total unknown
        return None


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    reqs = inputs.get("requirements", [])
    req_ids = guard.str_ids(reqs, "requirement_id")
    must = guard.str_ids([r for r in reqs if isinstance(r, dict) and r.get("must_have") is True], "requirement_id")
    by_id = guard.index_by(inputs.get("quotes"), "quote_id")

    cm, cv = output.get("coverage_matrix"), output.get("coverage")
    coverage = cm if isinstance(cm, list) else (cv if isinstance(cv, list) else [])
    expected_pairs = {f"{q}|{r}" for q in by_id for r in req_ids}
    pairs = [{"pair": f"{r.get('quote_id')}|{r.get('requirement_id')}"} for r in coverage if isinstance(r, dict)]
    findings = guard.ids_exactly_once(expected_pairs, pairs, "pair")

    bad_status = [r for r in coverage if isinstance(r, dict) and r.get("status") not in _STATUSES]
    findings += [guard.finding("status-invalid", f"status {r.get('status')!r} invalid") for r in bad_status]

    totals = output.get("totals") if isinstance(output.get("totals"), list) else []
    exp_totals = {qid: t for qid, q in by_id.items() if (t := _quote_total(q)) is not None}
    findings += guard.ids_exactly_once(list(exp_totals), totals, "quote_id")
    for row in totals:
        qid = row.get("quote_id") if isinstance(row, dict) else None
        want = exp_totals.get(qid)
        wrong = isinstance(row, dict) and (want is None or guard.parse_decimal(row.get("total")) != want)
        findings += [guard.finding("totals-mismatch", f"total for {qid!r} not recomputed")] if wrong else []

    met: dict[str, set] = {qid: set() for qid in by_id}
    for row in coverage:
        if isinstance(row, dict) and row.get("status") == "met" and row.get("quote_id") in met:
            met[row["quote_id"]].add(row.get("requirement_id"))
    eligible = [qid for qid, m in met.items() if must <= m]

    rec = output.get("recommendation")
    rid = rec.get("quote_id") if isinstance(rec, dict) else None
    bad_rec = (rec is None and eligible) or (rec is not None and rid not in eligible)
    msg = "null but a quote qualifies" if rec is None else f"{rid!r} misses a must-have"
    findings += [guard.finding("recommendation-invalid", msg)] if bad_rec else []
    return findings
