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
    must_have_ids = {r.get("requirement_id") for r in requirements if isinstance(r, dict) and r.get("must_have")}
    quotes_by_id = {q.get("quote_id"): q for q in quotes if isinstance(q, dict)}

    findings: list[dict] = []
    expected_pairs: dict[tuple, str] = {}
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        meets = quote.get("meets") if isinstance(quote.get("meets"), dict) else {}
        for req in requirements:
            if not isinstance(req, dict):
                continue
            key = (quote.get("quote_id"), req.get("requirement_id"))
            expected_pairs[key] = meets.get(req.get("requirement_id"), "missing")

    seen_pairs: dict[tuple, object] = {}
    for i, row in enumerate(matrix):
        if not isinstance(row, dict):
            findings.append({"check": "output-malformed", "detail": f"coverage_matrix[{i}] is not an object"})
            continue
        key = (row.get("quote_id"), row.get("requirement_id"))
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

    total_by_quote: dict[str, Decimal] = {}
    for i, total in enumerate(totals):
        if not isinstance(total, dict):
            findings.append({"check": "output-malformed", "detail": f"totals[{i}] is not an object"})
            continue
        quote_id = total.get("quote_id")
        quote = quotes_by_id.get(quote_id)
        if quote is None:
            findings.append(
                {"check": "total-not-recomputed", "detail": f"totals[{i}] references unknown quote {quote_id!r}"}
            )
            continue
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
        else:
            total_by_quote[quote_id] = declared

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
