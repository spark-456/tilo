"""Deterministic quality-bar checker for commerce/quote-comparison.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


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
    matrix = output.get("coverage_matrix")
    totals = output.get("totals")
    if not isinstance(matrix, list) or not isinstance(totals, list) or "recommendation" not in output:
        return [{"check": "output-malformed", "detail": "output must have coverage_matrix, totals and recommendation"}]

    inputs = inputs if isinstance(inputs, dict) else {}
    requirements = inputs.get("requirements") if isinstance(inputs.get("requirements"), list) else []
    quotes = inputs.get("quotes") if isinstance(inputs.get("quotes"), list) else []
    # requirement_id and quote_id could each be any JSON type (e.g. a list),
    # which is unhashable and would raise in a set/dict comprehension or a
    # tuple-key assignment — only a string id is usable.
    must_have_ids = {
        r.get("requirement_id")
        for r in requirements
        if isinstance(r, dict) and r.get("must_have") and isinstance(r.get("requirement_id"), str)
    }
    quotes_by_id = {q.get("quote_id"): q for q in quotes if isinstance(q, dict) and isinstance(q.get("quote_id"), str)}

    findings: list[dict] = []
    expected_pairs: dict[tuple, str] = {}
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        quote_id = quote.get("quote_id")
        if not isinstance(quote_id, str):
            continue
        meets = quote.get("meets") if isinstance(quote.get("meets"), dict) else {}
        for req in requirements:
            if not isinstance(req, dict):
                continue
            requirement_id = req.get("requirement_id")
            if not isinstance(requirement_id, str):
                continue
            key = (quote_id, requirement_id)
            expected_pairs[key] = meets.get(requirement_id, "missing")

    seen_pairs: dict[tuple, object] = {}
    for i, row in enumerate(matrix):
        if not isinstance(row, dict):
            findings.append({"check": "output-malformed", "detail": f"coverage_matrix[{i}] is not an object"})
            continue
        row_quote_id = row.get("quote_id")
        row_requirement_id = row.get("requirement_id")
        # Both must be strings before they can be used as a dict/tuple key:
        # an unhashable value (e.g. a list) would otherwise raise here.
        if not isinstance(row_quote_id, str) or not isinstance(row_requirement_id, str):
            findings.append(
                {
                    "check": "output-malformed",
                    "detail": f"coverage_matrix[{i}] quote_id and requirement_id must be strings",
                }
            )
            continue
        key = (row_quote_id, row_requirement_id)
        seen_pairs[key] = row.get("status")
        if key in expected_pairs and row.get("status") != expected_pairs[key]:
            findings.append(
                {
                    "check": "coverage-matrix-incomplete",
                    "detail": f"coverage_matrix[{i}] {key} status != supplied {expected_pairs[key]!r}",
                }
            )
    missing_pairs = set(expected_pairs) - set(seen_pairs)
    if missing_pairs:
        findings.append(
            {
                "check": "coverage-matrix-incomplete",
                "detail": f"coverage_matrix is missing {len(missing_pairs)} requirement x quote pair(s)",
            }
        )

    quote_qualifies: dict[str, bool] = {}
    for quote_id, quote in quotes_by_id.items():
        meets = quote.get("meets") if isinstance(quote.get("meets"), dict) else {}
        quote_qualifies[quote_id] = all(meets.get(req_id) == "met" for req_id in must_have_ids)

    totals_seen_count: dict[str, int] = {}
    for i, total in enumerate(totals):
        if not isinstance(total, dict):
            findings.append({"check": "output-malformed", "detail": f"totals[{i}] is not an object"})
            continue
        quote_id = total.get("quote_id")
        # quote_id could be any JSON type (e.g. a list), which is unhashable
        # and would raise on a dict lookup — check the type before it. Unlike
        # coverage_matrix's ids (checked above), totals[].quote_id here comes
        # straight from the output, which schema validation does not cover
        # for a failing case, so this path is reachable, not just defensive.
        if not isinstance(quote_id, str):
            findings.append({"check": "output-malformed", "detail": f"totals[{i}].quote_id must be a string"})
            continue
        quote = quotes_by_id.get(quote_id)
        if quote is None:
            findings.append(
                {"check": "total-not-recomputed", "detail": f"totals[{i}] references unknown quote {quote_id!r}"}
            )
            continue
        totals_seen_count[quote_id] = totals_seen_count.get(quote_id, 0) + 1
        line_items = quote.get("line_items") if isinstance(quote.get("line_items"), list) else []
        expected = sum(
            (_dec(li.get("quantity")) or Decimal(0)) * (_dec(li.get("unit_price")) or Decimal(0))
            for li in line_items
            if isinstance(li, dict)
        )
        declared = _dec(total.get("total_cost"))
        if declared is None or declared != expected or total.get("source_id") != quote.get("source_id"):
            findings.append(
                {
                    "check": "total-not-recomputed",
                    "detail": f"totals[{i}] total_cost does not match the exact recomputed sum",
                }
            )

    # "total cost of each quote recomputed" (ticket FR-AGT-04) means exactly
    # one totals row per input quote — a short totals array or a duplicated
    # quote_id must fail just as loudly as a wrong sum.
    for quote_id in quotes_by_id:
        count = totals_seen_count.get(quote_id, 0)
        if count == 0:
            findings.append({"check": "total-not-recomputed", "detail": f"totals has no row for quote {quote_id!r}"})
        elif count > 1:
            findings.append(
                {"check": "total-not-recomputed", "detail": f"totals has {count} rows for quote {quote_id!r}"}
            )

    recommendation = output.get("recommendation")
    any_qualifies = any(quote_qualifies.values())
    if recommendation is None:
        if any_qualifies:
            findings.append(
                {
                    "check": "recommendation-should-be-null",
                    "detail": "recommendation is null but at least one quote meets every must-have requirement",
                }
            )
    elif not isinstance(recommendation, dict) or not isinstance(recommendation.get("quote_id"), str):
        findings.append(
            {"check": "output-malformed", "detail": "output.recommendation must be an object with quote_id, or null"}
        )
    else:
        rec_id = recommendation.get("quote_id")
        if not quote_qualifies.get(rec_id, False):
            findings.append(
                {
                    "check": "recommendation-fails-must-have",
                    "detail": f"recommended quote {rec_id!r} does not meet every must-have requirement",
                }
            )
        quote = quotes_by_id.get(rec_id)
        if quote is not None and recommendation.get("source_id") != quote.get("source_id"):
            findings.append(
                {
                    "check": "coverage-matrix-incomplete",
                    "detail": "recommendation.source_id does not match the recommended quote",
                }
            )
    return findings
