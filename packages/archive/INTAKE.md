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
Limits additionally cap each XML part at 1 MiB before decoding or XML parsing,
20,000 nodes and 20,000 attributes across the entire package, depth 64 during
incremental parsing, and returned text at 1 Mi characters. Each tree is screened,
used and dropped; trees are not retained for the whole package. Limits have hard
ceilings (32 MiB cumulative expanded bytes; other ceilings match their defaults).
Embedded objects and binary parts are conservatively refused.
It does not render page numbers, recover layout, interpret fields, execute content,
or read images. Generic ZIP leaf
bytes remain inert and unscreened; use a document parser before offering them as text.
No route, archive persistence, consent, scope or KnowledgeItem schema is added here.
Callers must apply content screening before offering any returned bytes to a model.

`parse_csv` reads comma-separated UTF-8 (optional BOM), preserving quoted multiline
and empty cells with logical `csv#rNcN` provenance. It never evaluates formulas.
No delimiter or encoding is guessed. Malformed quoting, invalid UTF-8 and NUL bytes
are refused. Input/text caps apply; the entry cap counts cells (blank rows count
as one entry). Python's field-size cap also applies without global mutation.
CSV has no reliable magic signature: the caller must explicitly select this parser.
Cells remain untrusted data and need screening before use or spreadsheet export.

`parse_xlsx` resolves shared and inline strings and reads stored worksheet cell
values with `xl/worksheets/<part>.xml#<cell>` citations. Formula cached values are
returned as inert text; a missing cached value is empty. It never evaluates formulas
or interprets styles, dates, layout, charts or sheet display names. All XML parts
use the same bounded Office screening as DOCX; external-link parts are refused.
Invalid/duplicate cell references, unknown cell types and missing shared-string
indices are refused. The entry cap also bounds emitted cells; text caps apply to
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
