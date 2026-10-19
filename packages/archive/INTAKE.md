# I4 deterministic intake library

`tilo_archive.document_parsers.expand_zip(bytes, limits=Limits())` returns a tuple
of `(relative label, inert bytes)` in stored order, recursively expanding ZIP
containers identified by their byte signature. It never writes files or uses the
network. Labels are provenance hints, not filesystem destinations.

Defaults: 4 MiB input, 16 MiB cumulative decompression (including nested containers),
256 cumulative entries, two nested archive levels, 16 path components, 100:1 ratio.
Invalid limits raise `ValueError`; refused input raises `Refused` with a stable code
and no uploaded content. Encrypted ZIPs, unsupported compression, special entries,
ambiguous paths and duplicate output labels are refused.

`parse_docx` reads UTF-8 Word paragraph text with part/paragraph provenance. All XML
parts are screened: DTD/entities, external references and active content are refused.
Relationship targets are separator-normalised before the test, so a URL scheme, drive letter,
`//host`, `\\host`, `/\host`, `\/host` and a rooted `\host\share` (optionally behind a BOM or
zero-width character) are all refused as `external_reference`; `/word/media/a.png` stays allowed.
Limits additionally cap each XML part at 1 MiB before decoding or XML parsing,
20,000 nodes and 20,000 attributes across the entire package, depth 64 during
incremental parsing, and returned text at 1 Mi characters. Each tree is screened,
used and dropped; trees are not retained for the whole package. Limits have hard
ceilings (32 MiB cumulative expanded bytes, 8,192 cells, 4,096 paragraphs;
other ceilings match their defaults).
Embedded objects and binary parts are conservatively refused.
It does not render page numbers, recover layout, interpret fields, execute content,
or read images. Generic ZIP leaf
bytes remain inert and unscreened; use a document parser before offering them as text.
No route, archive persistence, consent, scope or KnowledgeItem schema is added here.
Callers must apply content screening before offering any returned bytes to a model.

`parse_csv` reads comma-separated UTF-8 (optional BOM), preserving quoted multiline
and empty cells with logical `csv#rNcN` provenance. It never evaluates formulas.
No delimiter or encoding is guessed. Malformed quoting, invalid UTF-8 and NUL bytes
are refused. Input/text caps apply; the cell cap counts cells (blank rows count
as one cell). Python's field-size cap also applies without global mutation.
CSV has no reliable magic signature: the caller must explicitly select this parser.
Cells remain untrusted data and need screening before use or spreadsheet export.

`parse_xlsx` resolves shared and inline strings and reads stored worksheet cell
values with `xl/worksheets/<part>.xml#<cell>` citations. Formula cached values are
returned as inert text; a missing cached value is empty. It never evaluates formulas
or interprets styles, dates, layout, charts or sheet display names. All XML parts
use the same bounded Office screening as DOCX; external-link parts are refused.
Invalid/duplicate cell references, unknown cell types and missing shared-string
indices are refused. The cell cap bounds emitted cells; text caps apply to
resolved output. Numeric, boolean, date and error values preserve stored text.

`parse_pptx` reads DrawingML paragraphs from slide parts, including table cells,
with `ppt/slides/slideN.xml#pN` provenance and explicit line breaks. Stored part
order is preserved; labels are package parts, not presentation display positions.
All XML parts use the same Office screening; text and paragraph caps apply,
including empty paragraphs. Notes, layouts, images and animation are not read;
no fields or links are evaluated. Text remains untrusted data requiring screening.
Structural XML screening covers declarations, relationship targets, xml:base and
active-content markers; it is not a safety verdict on arbitrary text or attributes.
When wired, both parsing and safety screening require a sandbox memory limit.

Coverage: DOCX paragraphs include hidden text and comments in word parts; page
layout, images and altChunk payloads are not interpreted. A caller must describe
this coverage and the skipped content when presenting the result.

XLSX coverage: stored values on hidden sheets are included; images, charts, styles, dates and layout are not interpreted. The caller must state this coverage.

PPTX coverage: hidden slide parts are included; speaker notes, images, layouts and animation are not interpreted. The caller must state this coverage.

## Route prerequisite decisions (I4 / FR-INT-02)

ZIP entries remain 256 cumulative. CSV/XLSX cells have a separate default of 4,096
and hard ceiling of 8,192; DOCX/PPTX paragraphs have a default of 2,048 and ceiling
of 4,096, including empty paragraphs across all read parts. These are independent
of ZIP entries. Existing package-wide XML ceilings stay 20,000 nodes and 20,000
attributes, depth 64, with a 1 MiB per-part ceiling; a requested output count never
overrides them. Large documents can still be refused for these resource budgets.

`read_document(bytes, kind=..., limits=...)` returns cited fragments and explicit
`read` / `skipped` capability lists for DOCX, XLSX, PPTX and CSV. This internal
result is not a KnowledgeItem or safety verdict. Successful parsing means text
was extracted, not that the user-facing item was understood. ZIP/unknown kinds
are refused by this reader; existing `expand_zip` still returns inert bytes.

Before route wiring, parsing must run in a process sandbox with an enforced
memory limit and wall-clock timeout; safety screening and a quarantined reader
must precede model use. Verify production Expat >= 2.6 and measure process peak
including its native heap. The existing tracemalloc probes are insufficient for
that deployment claim. CSV cells are counted before row materialization, with
quoted separators, multiline fields and doubled quotes respected. Blank records
and empty cells consume the budget. Encoding/CSV refusals retain no exception
context. Office verdicts remain converted-text-only;
outbound attachments remain T3 pending the screening-scope ADR amendment.

`process_reader.read_isolated` runs the reader in an isolated Python child and
installs a 256 MiB memory ceiling before reading uploaded bytes (Linux address
space via RLIMIT_AS; Windows committed memory via a Job Object). The default and
maximum wall timeout is 10 seconds; expiry kills and reaps the child. Callers may
lower memory to at least 64 MiB and lower the timeout. Unsupported systems or
failed memory-limit installation refuse before parsing. Office parsing refuses
Expat older than 2.6 at runtime. The worker inherits only OS/temp-directory
settings, never cloud credentials; stderr and unknown failures become stable
refusals. Input, output and parser limits apply inside the child.

This is resource isolation for the fixed byte-only parsers, not an arbitrary-code
execution sandbox or a safety verdict. Safety screening and the quarantined
reader still precede model use. No route is wired here; production process-peak
and deployed-runtime evidence remain MERGE prerequisites.
