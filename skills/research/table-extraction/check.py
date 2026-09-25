# research/table-extraction checker (FR-AGT-04).
from skills._lib import guard


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    rows_by_id = guard.index_by(inputs.get("table", {}).get("rows"), "row_ref")
    rows_by_ref = {k: v.get("cells", {}) for k, v in rows_by_id.items()}

    if not isinstance(records := output.get("records"), list):
        return [guard.finding("row-ref-invalid", "output.records must be a list")]

    findings: list[dict] = []
    seen: dict[str, int] = {}
    for i, rec in enumerate(records):
        ref = rec.get("row_ref") if isinstance(rec, dict) else None
        if not isinstance(ref, str) or ref not in rows_by_ref:
            findings.append(guard.finding("row-ref-invalid", f"records[{i}] row_ref {ref!r} unknown"))
            continue
        seen[ref] = seen.get(ref, 0) + 1
        cells = rows_by_ref.get(ref, {})
        fields = rec.get("fields", {})
        for fname, f in fields.items() if isinstance(fields, dict) else []:
            if not isinstance(f, dict):
                findings.append(guard.finding("field-outside-row", f"records[{i}].{fname} not an object"))
                continue
            cell_name, value = f.get("cell"), f.get("value")
            if not isinstance(cell_name, str) or not isinstance(cells, dict) or cell_name not in cells:
                findings.append(guard.finding("field-outside-row", f"records[{i}].{fname}.cell {cell_name!r} unknown"))
                continue
            cell_str = cells.get(cell_name) if isinstance(cells.get(cell_name), str) else None
            if isinstance(value, str):
                bad = cell_str is None or value != cell_str.strip()
                findings += [guard.finding("text-value-mismatch", f"records[{i}].{fname} != cell text")] if bad else []
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cell_dec, val_dec = guard.parse_decimal(cell_str), guard.parse_decimal(value)
                bad = cell_dec is None or val_dec is None or cell_dec != val_dec
                findings += [guard.finding("number-value-mismatch", f"records[{i}].{fname} bad num")] if bad else []
            else:
                findings.append(guard.finding("field-outside-row", f"records[{i}].{fname} value type invalid"))

    findings += [guard.finding("row-ref-invalid", f"{r!r} used twice") for r, c in seen.items() if c > 1]
    return findings
