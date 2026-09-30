---
name: untrusted-zip-fuzz-probe
description: Byte-mutation fuzz of OOXML/zip uploads finds ValueError/UnicodeDecodeError escaping narrow except tuples (FR-INT-02 intake)
metadata:
  type: feedback
---

When a ticket parses untrusted zip/XML (DOCX/PPTX/XLSX), fuzz it: flip 1-8 random bytes in a valid
fixture 3000 times and count exception types outside the module's own error class.

**Why:** FR-INT-02 extraction caught BadZipFile/zlib.error/RuntimeError etc. but not ValueError
("negative seek value" from a corrupt central directory) or UnicodeDecodeError (bad member-name
bytes); ~1.3% of mutations turned into a 500 on POST /intake instead of a per-file "failed" status.

**How to apply:** scratchpad script importing the test lib's `make_docx_bytes`; also hit the HTTP
route with `TestClient(app, raise_server_exceptions=False)` to confirm a 500. Done looks like: catch
ValueError (covers UnicodeDecodeError) and a regression test with a corrupt central directory.
