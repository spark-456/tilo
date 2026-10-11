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
Limits additionally cap XML at 20,000 nodes and depth 64 per part, and returned text
at 1 Mi characters. Embedded objects and binary parts are conservatively refused.
It does not render page numbers, recover layout, interpret fields, execute content,
or read images. XLSX, PPTX and CSV remain for subsequent slices. Generic ZIP leaf
bytes remain inert and unscreened; use a document parser before offering them as text.
No route, archive persistence, consent, scope or KnowledgeItem schema is added here.
Callers must apply content screening before offering any returned bytes to a model.
