"""Deterministic quality-bar checker for research/table-extraction.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]

    records = output.get("records")
    if not isinstance(records, list):
        return [{"check": "output-malformed", "detail": "output.records must be an array"}]

    inputs = inputs if isinstance(inputs, dict) else {}
    table = inputs.get("table") if isinstance(inputs.get("table"), dict) else {}
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []

    known_refs: set[str] = set()
    ref_to_text: dict[str, str] = {}
    ref_to_row_index: dict[str, int] = {}
    row_count = 0
    for row in rows:
        if not isinstance(row, list):
            continue
        row_index = row_count
        row_count += 1
        for cell in row:
            if isinstance(cell, dict) and isinstance(cell.get("ref"), str):
                known_refs.add(cell["ref"])
                ref_to_text[cell["ref"]] = cell.get("value")
                ref_to_row_index[cell["ref"]] = row_index

    findings: list[dict] = []
    if len(records) > row_count:
        findings.append(
            {
                "check": "no-invented-rows",
                "detail": f"{len(records)} records were produced for only {row_count} input rows",
            }
        )

    # Each input row may produce at most one record (fix round 3,
    # code-reviewer): counting alone (no-invented-rows above) does not catch
    # a record duplicated in place of a dropped row, since the total count
    # can still match the row count exactly.
    row_index_use_count: dict[int, int] = {}
    for i, record in enumerate(records):
        if not isinstance(record, dict):
            findings.append({"check": "output-malformed", "detail": f"records[{i}] is not an object"})
            continue
        fields = record.get("fields")
        if not isinstance(fields, dict):
            findings.append({"check": "output-malformed", "detail": f"records[{i}].fields must be an object"})
            continue

        row_ref = record.get("row_ref")
        row_idx = ref_to_row_index.get(row_ref) if isinstance(row_ref, str) else None
        if row_idx is None:
            findings.append(
                {
                    "check": "output-malformed",
                    "detail": f"records[{i}].row_ref must name a known cell reference",
                }
            )
        else:
            row_index_use_count[row_idx] = row_index_use_count.get(row_idx, 0) + 1
            if row_index_use_count[row_idx] > 1:
                findings.append(
                    {
                        "check": "row-reused",
                        "detail": f"records[{i}] row_ref {row_ref!r} names a row already used by an earlier record",
                    }
                )

        for name, field in fields.items():
            if (
                not isinstance(field, dict)
                or "value" not in field
                or "source_ref" not in field
                or not isinstance(field.get("source_ref"), str)
            ):
                findings.append(
                    {
                        "check": "output-malformed",
                        "detail": f"records[{i}].fields[{name!r}] must have value and a string source_ref",
                    }
                )
                continue
            ref = field.get("source_ref")
            if ref not in known_refs:
                findings.append(
                    {"check": "source-ref-known", "detail": f"records[{i}].fields[{name!r}] cites unknown cell {ref!r}"}
                )
                continue
            if row_idx is not None and ref_to_row_index.get(ref) != row_idx:
                findings.append(
                    {
                        "check": "source-ref-in-row",
                        "detail": (
                            f"records[{i}].fields[{name!r}] cites cell {ref!r}, which is not in the row "
                            f"named by row_ref {row_ref!r}"
                        ),
                    }
                )
            value = field.get("value")
            if isinstance(value, (list, dict)):
                findings.append(
                    {
                        "check": "output-malformed",
                        "detail": f"records[{i}].fields[{name!r}] value must be a string, number, boolean or null",
                    }
                )
                continue
            raw = ref_to_text.get(ref)
            parsed = _parse_number(raw)
            if parsed is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value != parsed:
                    findings.append(
                        {
                            "check": "number-parses-exactly",
                            "detail": f"records[{i}].fields[{name!r}] value {value!r} does not exactly match {raw!r}",
                        }
                    )
            elif isinstance(value, str) and isinstance(raw, str):
                if value != raw and value != raw.strip():
                    findings.append(
                        {
                            "check": "text-matches-cell",
                            "detail": (
                                f"records[{i}].fields[{name!r}] value {value!r} does not match cell "
                                f"{ref!r}'s text {raw!r}"
                            ),
                        }
                    )
    return findings


def _parse_number(raw: object) -> float | int | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        if any(c in text for c in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return None
