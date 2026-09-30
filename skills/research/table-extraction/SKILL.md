# Table extraction

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to turn a supplied table (rows of named cells) into typed records, one per row, every value traceable back to the exact cell it came from.

## Steps

1. Read `inputs.table.rows`, each a row_ref and a mapping of cell name to cell text.
2. Emit exactly one record per row you extract, naming that row's `row_ref`; never emit two records for the same row and never invent a row_ref that was not supplied.
3. For every field on a record, name the `cell` it came from (a key of that row's cells) and give the parsed `value`.
4. A text value must equal the cell's text with only leading/trailing whitespace trimmed — never reworded, corrected or reformatted.
5. A numeric value must equal the cell's text parsed as a plain number exactly — never rounded, rescaled or approximated.

## Quality bar

- `row-ref-invalid`: every record's row_ref must name a supplied row, and no two records may share one.
- `field-outside-row`: every field's cell must be a cell of that record's own row.
- `text-value-mismatch`: a text value must equal its cell's trimmed text exactly.
- `number-value-mismatch`: a numeric value must equal its cell's number, parsed exactly.

## Checklist

- [ ] Every record's row_ref names a supplied row, used at most once.
- [ ] Every field's cell exists in that row.
- [ ] Text values are the cell's own trimmed text, not a paraphrase.
- [ ] Numeric values match the cell's number exactly.

## Pitfalls

- "Cleaning up" a cell's text (title-casing a name, expanding an abbreviation) instead of copying it exactly.
- Rounding a numeric cell's value, or parsing a differently-formatted number that happens to look close.
- Reusing one row's data for a record whose row_ref names a different row.
- Inventing a field whose cell was never in that row, because it "seemed implied" by the row's other values.
