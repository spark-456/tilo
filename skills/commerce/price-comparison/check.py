# commerce/price-comparison checker (FR-AGT-04).
import operator as op
from decimal import Decimal

from skills._lib import guard

_OPS = {"eq": op.eq, "gte": op.ge, "lte": op.le, "gt": op.gt, "lt": op.lt, "in": lambda a, b: a in b}
_4DP = Decimal("0.0001")


def _meets(offer: dict, requirements: list) -> bool:
    try:
        return all(_OPS[r["op"]](offer[r["field"]], r["value"]) for r in requirements)
    except Exception:  # noqa: BLE001 - a malformed requirement/offer just fails the match
        return False


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    rates, reqs = inputs.get("rates", {}), inputs.get("requirements", [])
    by_id = guard.index_by(inputs.get("offers"), "offer_id")

    findings = guard.ids_exactly_once(list(by_id), (unit_prices := output.get("unit_prices")), "offer_id")

    expected: dict[str, Decimal] = {}
    for oid, offer in by_id.items():
        rate = guard.parse_decimal(rates.get(cur)) if isinstance(cur := offer.get("currency"), str) else None
        price, count = guard.parse_decimal(offer.get("price")), guard.parse_decimal(offer.get("unit_count"))
        if price is not None and rate is not None and count:
            expected[oid] = (price * rate / count).quantize(_4DP)

    for row in unit_prices if isinstance(unit_prices, list) else []:
        want = expected.get(oid := (row.get("offer_id") if isinstance(row, dict) else None))
        got = guard.parse_decimal(row.get("unit_price")) if isinstance(row, dict) else None
        src_ok = isinstance(row, dict) and row.get("source_id") == by_id.get(oid, {}).get("source_id")
        bad = want is None or got is None or got.quantize(_4DP) != want or not src_ok
        findings += [guard.finding("unit-price-mismatch", f"{oid!r} does not recompute")] if bad else []

    qualifying = [oid for oid, o in by_id.items() if _meets(o, reqs)]
    cheapest = min(((o, expected[o]) for o in qualifying if o in expected), key=lambda p: p[1], default=(None,))[0]

    if (pick := output.get("pick")) is None:
        findings += [guard.finding("pick-not-cheapest", "null but an offer qualifies")] if qualifying else []
    elif isinstance(pick, dict):
        pick_id, pick_offer = pick.get("offer_id"), by_id.get(pick.get("offer_id"))
        if pick_offer is None or not _meets(pick_offer, reqs):
            findings.append(guard.finding("pick-requirement-fail", f"{pick_id!r} fails a requirement"))
        elif pick.get("source_id") != pick_offer.get("source_id"):
            findings.append(guard.finding("pick-requirement-fail", f"source_id mismatch for {pick_id!r}"))
        elif cheapest is not None and pick_id != cheapest:
            findings.append(guard.finding("pick-not-cheapest", f"cheapest is {cheapest!r}, not {pick_id!r}"))
    else:
        findings.append(guard.finding("pick-requirement-fail", f"pick is not an object or null: {pick!r}"))
    return findings
