"""Deterministic quality-bar checker for commerce/price-comparison.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

_OPS = {
    "eq": lambda a, b: a == b,
    "gte": lambda a, b: _both_numeric(a, b) and a >= b,
    "lte": lambda a, b: _both_numeric(a, b) and a <= b,
    "gt": lambda a, b: _both_numeric(a, b) and a > b,
    "lt": lambda a, b: _both_numeric(a, b) and a < b,
    "in": lambda a, b: isinstance(b, list) and a in b,
}


def _both_numeric(a: object, b: object) -> bool:
    return (
        isinstance(a, (int, float))
        and not isinstance(a, bool)
        and isinstance(b, (int, float))
        and not isinstance(b, bool)
    )


def _meets_requirements(offer: object, requirements: list) -> bool:
    if not isinstance(offer, dict):
        return False
    for req in requirements:
        if not isinstance(req, dict):
            return False
        field, op, value = req.get("field"), req.get("op"), req.get("value")
        fn = _OPS.get(op)
        if fn is None or field not in offer:
            return False
        if not fn(offer.get(field), value):
            return False
    return True


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]
    unit_prices = output.get("unit_prices")
    if not isinstance(unit_prices, list) or "pick" not in output:
        return [{"check": "output-malformed", "detail": "output must have a unit_prices array and a pick"}]

    inputs = inputs if isinstance(inputs, dict) else {}
    offers = inputs.get("offers") if isinstance(inputs.get("offers"), list) else []
    rates = inputs.get("rates") if isinstance(inputs.get("rates"), dict) else {}
    target_currency = inputs.get("currency")
    requirements = inputs.get("requirements") if isinstance(inputs.get("requirements"), list) else []
    offers_by_id = {o.get("offer_id"): o for o in offers if isinstance(o, dict)}

    findings: list[dict] = []
    computed: dict[str, float] = {}
    for i, up in enumerate(unit_prices):
        if not isinstance(up, dict):
            findings.append({"check": "output-malformed", "detail": f"unit_prices[{i}] is not an object"})
            continue
        offer_id = up.get("offer_id")
        offer = offers_by_id.get(offer_id)
        source_ok = (
            offer is not None
            and up.get("source_id") == offer.get("source_id")
            and up.get("currency") == target_currency
        )

        expected = None
        if offer is not None:
            price, currency, unit_count = offer.get("price"), offer.get("currency"), offer.get("unit_count")
            rate = rates.get(currency)
            if (
                isinstance(price, (int, float))
                and not isinstance(price, bool)
                and isinstance(rate, (int, float))
                and not isinstance(rate, bool)
                and isinstance(unit_count, (int, float))
                and not isinstance(unit_count, bool)
                and unit_count
            ):
                expected = (price * rate) / unit_count

        declared = up.get("unit_price")
        value_ok = (
            expected is not None
            and isinstance(declared, (int, float))
            and not isinstance(declared, bool)
            and round(declared, 6) == round(expected, 6)
        )
        if not (source_ok and value_ok):
            findings.append(
                {
                    "check": "unit-price-mismatch",
                    "detail": f"unit_prices[{i}] for offer {offer_id!r} does not recompute from the offer and rates",
                }
            )
        elif offer is not None:
            computed[offer_id] = declared

    qualifying = [oid for oid, offer in offers_by_id.items() if _meets_requirements(offer, requirements)]
    priced_qualifying = [(oid, computed[oid]) for oid in qualifying if oid in computed]
    cheapest_id = min(priced_qualifying, key=lambda pair: pair[1])[0] if priced_qualifying else None

    pick = output.get("pick")
    if pick is None:
        if qualifying:
            findings.append(
                {
                    "check": "pick-is-cheapest-qualifying",
                    "detail": "pick is null but at least one offer meets every stated requirement",
                }
            )
    elif not isinstance(pick, dict) or not isinstance(pick.get("offer_id"), str):
        findings.append({"check": "output-malformed", "detail": "output.pick must be an object with offer_id, or null"})
    else:
        pick_offer = offers_by_id.get(pick.get("offer_id"))
        if pick_offer is None or not _meets_requirements(pick_offer, requirements):
            findings.append(
                {
                    "check": "pick-meets-requirements",
                    "detail": f"picked offer {pick.get('offer_id')!r} fails a stated requirement or is unknown",
                }
            )
        elif cheapest_id is not None and pick.get("offer_id") != cheapest_id:
            findings.append(
                {
                    "check": "pick-is-cheapest-qualifying",
                    "detail": f"the cheapest qualifying offer is {cheapest_id!r}, not {pick.get('offer_id')!r}",
                }
            )
    return findings
