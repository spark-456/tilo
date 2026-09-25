"""Deterministic quality-bar checker for commerce/price-comparison.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

# A bound on any single price, rate or unit_count. The input schema types
# each as an unbounded JSON `number`, so a schema-valid input can still carry
# an absurd value (round 2, qa-breaker: the same class of bug as invoice
# quantities). Plain float arithmetic on such a value can raise OverflowError
# ("int too large to convert to float"); a value this size is not a real
# price either way, so it is treated as unusable input rather than silently
# computed with.
_MAX_MAGNITUDE = Decimal("1e12")

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


def _dec(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not dec.is_finite() or dec.copy_abs() > _MAX_MAGNITUDE:
        return None
    return dec


def _meets_requirements(offer: object, requirements: list) -> bool:
    if not isinstance(offer, dict):
        return False
    for req in requirements:
        if not isinstance(req, dict):
            return False
        field, op, value = req.get("field"), req.get("op"), req.get("value")
        # op/field could be any JSON type (e.g. a list), which is unhashable
        # and would raise on a dict lookup or `in` a dict — check first.
        if not isinstance(op, str):
            return False
        fn = _OPS.get(op)
        if fn is None or not isinstance(field, str) or field not in offer:
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
    offers_by_id = {o.get("offer_id"): o for o in offers if isinstance(o, dict) and isinstance(o.get("offer_id"), str)}

    findings: list[dict] = []
    for offer_id, offer in offers_by_id.items():
        for field in ("price", "unit_count"):
            raw = offer.get(field)
            if raw is not None and _dec(raw) is None:
                findings.append(
                    {
                        "check": "input-malformed",
                        "detail": f"offer {offer_id!r} {field} {raw!r} is not a usable number",
                    }
                )

    # Expected unit price for every offer, computed from the inputs alone —
    # never from the output (fix round 3, qa-breaker): the cheapest
    # qualifying offer and the pick must be judged against what the offers
    # actually cost, not against whichever unit_prices rows the output chose
    # to report. An output that omits a cheap offer's row entirely must not
    # be able to make a dearer offer look cheapest just because its row is
    # the only one present.
    expected_by_offer: dict[str, Decimal] = {}
    for offer_id, offer in offers_by_id.items():
        price_dec = _dec(offer.get("price"))
        rate_dec = _dec(rates.get(offer.get("currency"))) if isinstance(offer.get("currency"), str) else None
        unit_count_dec = _dec(offer.get("unit_count"))
        if price_dec is not None and rate_dec is not None and unit_count_dec:
            try:
                expected_by_offer[offer_id] = (price_dec * rate_dec) / unit_count_dec
            except (InvalidOperation, ArithmeticError):
                pass

    unit_price_rows_by_offer: dict[str, dict] = {}
    for i, up in enumerate(unit_prices):
        if not isinstance(up, dict):
            findings.append({"check": "output-malformed", "detail": f"unit_prices[{i}] is not an object"})
            continue
        offer_id = up.get("offer_id")
        # offer_id could be any JSON type (e.g. a list), which is unhashable
        # and would raise on a dict lookup — check the type before it.
        if not isinstance(offer_id, str):
            findings.append({"check": "output-malformed", "detail": f"unit_prices[{i}].offer_id must be a string"})
            continue
        unit_price_rows_by_offer[offer_id] = up
        offer = offers_by_id.get(offer_id)
        source_ok = (
            offer is not None
            and up.get("source_id") == offer.get("source_id")
            and up.get("currency") == target_currency
        )

        expected = expected_by_offer.get(offer_id)
        declared_dec = _dec(up.get("unit_price"))
        value_ok = False
        if expected is not None and declared_dec is not None:
            try:
                value_ok = abs(declared_dec - expected) <= Decimal("0.000001")
            except (InvalidOperation, ArithmeticError):
                value_ok = False
        if not (source_ok and value_ok):
            findings.append(
                {
                    "check": "unit-price-mismatch",
                    "detail": f"unit_prices[{i}] for offer {offer_id!r} does not recompute from the offer and rates",
                }
            )

    # Every offer whose price is usable and computable must get its own
    # unit_prices row. unit-price-mismatch alone cannot catch a row that is
    # simply missing, only a row whose declared value is wrong.
    for offer_id in expected_by_offer:
        if offer_id not in unit_price_rows_by_offer:
            findings.append({"check": "unit-price-missing", "detail": f"offer {offer_id!r} has no unit_prices row"})

    qualifying = [oid for oid, offer in offers_by_id.items() if _meets_requirements(offer, requirements)]
    priced_qualifying = [(oid, expected_by_offer[oid]) for oid in qualifying if oid in expected_by_offer]
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
        else:
            if not isinstance(pick.get("source_id"), str) or pick.get("source_id") != pick_offer.get("source_id"):
                findings.append(
                    {
                        "check": "pick-source-mismatch",
                        "detail": (
                            f"pick.source_id {pick.get('source_id')!r} does not match offer "
                            f"{pick.get('offer_id')!r}'s own source_id {pick_offer.get('source_id')!r}"
                        ),
                    }
                )
            if cheapest_id is not None and pick.get("offer_id") != cheapest_id:
                findings.append(
                    {
                        "check": "pick-is-cheapest-qualifying",
                        "detail": f"the cheapest qualifying offer is {cheapest_id!r}, not {pick.get('offer_id')!r}",
                    }
                )
    return findings
