# Table extraction

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill when a plan needs structured, typed records out of a table that has already been extracted into cells with references (for example from a spreadsheet, a PDF table or a web table), and every value in the result must be traceable back to the exact cell it came from. Do not use it to summarise or reshape a table's meaning — only to turn its cells into typed, sourced records.

## Steps

1. Read `inputs.table.columns` and `inputs.table.rows`. Each row is a list of cells, each cell an object with a `ref` (its location, e.g. `"B3"`) and a `value` (its raw text).
2. Produce exactly one record per input row — never more rows than were supplied, and never a row that does not correspond to an actual input row.
3. For each field you extract from a row, set `source_ref` to the exact cell `ref` it came from. Never invent a cell reference.
4. Parse numeric-looking cell text into a real number exactly: `"1200"` becomes `1200`, `"3.50"` becomes `3.5`. If a cell is not numeric, keep it as its cleaned string, boolean or null — do not force a parse that changes the value.
5. Use `row_ref` on each record to point back to the row (for example the `ref` of its first cell), so the record can be traced to its source row.
6. Do not add columns or fields that were not present in the row's cells.

## Quality bar

- `no-invented-rows`: the number of output records must never exceed the number of input rows.
- `source-ref-known`: every field's source_ref must be an actual cell reference from the supplied table.
- `number-parses-exactly`: a field parsed from numeric-looking cell text must equal that number exactly, with no rounding or truncation drift.
- `output-malformed`: the output must be an object with a records array of row_ref/fields objects; malformed shapes fail closed.

## Checklist

- [ ] Record count does not exceed the input row count.
- [ ] Every field's source_ref names a real, supplied cell.
- [ ] Every numeric field matches its source cell's text exactly when reparsed.
- [ ] No field or row was invented that the table did not contain.

## Pitfalls

- Rounding a parsed number "for readability" — this breaks exact-match provenance and fails the quality bar.
- Reusing a cell reference for a field it did not actually produce, just because the row looks right.
- Treating a merged or repeated header cell as if it were a data row, inflating the record count past the true row count.
- Coercing a non-numeric cell (for example a currency symbol plus text) into a number instead of keeping it as text.
