"""tilo_providers._pdf_pages_child -- counts the pages of ONE untrusted PDF read from stdin, in its own process (LW-06).
`media.pdf_pages` runs this under a wall-clock timeout and kills it on overrun, because a parser has no CPU or memory
bound of its own: a PDF of a few kilobytes can ask for seconds of work or hundreds of megabytes. Here the decoded sizes
are limited too (a stream that inflates past DECODED_LIMIT is refused, so no object stream, xref stream or filter can
fill memory), and pypdf's logging is off. Prints one line: `ok <pages>`, `many 0` (over MAX_PDF_PAGES, or a page tree
over MAX_PDF_NODES) or `bad 0` (unreadable, encrypted, malformed). Nothing of the file is ever printed. This module
imports no PDF parser until `count` runs, so importing it (or `media`) in a service loads none."""

from __future__ import annotations

import io
import logging
import os
import sys
import threading
from typing import Any

MAX_PDF_PAGES = 100
MAX_PDF_NODES = 4 * MAX_PDF_PAGES  # page-tree nodes visited, a shared or cyclic tree counts each visit
DECODED_LIMIT = 1_000_000  # bytes any one stream may decode to; real object streams are far smaller
WATCHDOG_SECONDS = 10.0  # the child ends itself after this, so an orphan (its parent died) cannot run for hours
MEMORY_LIMIT_BYTES = 1 << 30  # address space of the child on POSIX; Windows has no setrlimit


def count(data: bytes) -> tuple[str, int]:
    """("ok", pages), ("many", 0) or ("bad", 0): the pages of `data` by walking its page tree, never its /Count."""
    logging.disable(logging.CRITICAL)
    import pypdf  # noqa: PLC0415 -- lazy on purpose: the importing service loads no PDF parser
    from pypdf.generic import DictionaryObject  # noqa: PLC0415

    pypdf.overwrite_configuration(  # the current configuration is what the decoders read; the class attributes are not
        zlib_maximum_output_length=DECODED_LIMIT,
        zlib_maximum_recovery_input_length=DECODED_LIMIT,
        lzw_maximum_output_length=DECODED_LIMIT,
        run_length_maximum_output_length=DECODED_LIMIT,
        array_based_stream_maximum_output_length=DECODED_LIMIT,
        jbig2_maximum_output_length=DECODED_LIMIT,
        maximum_declared_stream_length=DECODED_LIMIT,
        page_tree_maximum_entries=MAX_PDF_NODES,
        page_tree_maximum_depth=MAX_PDF_NODES,
    )
    pages = nodes = 0
    too_many = False
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            return "bad", 0
        stack: list[object] = [reader.trailer["/Root"]["/Pages"]]  # type: ignore[index]
        while stack and not too_many:
            nodes += 1
            node = stack.pop().get_object()  # type: ignore[attr-defined]
            if not isinstance(node, DictionaryObject):
                return "bad", 0
            kids = node.get("/Kids")
            if kids is None:
                pages += 1  # every node without /Kids is a page, whatever its /Type
            else:
                kids = kids.get_object()
                if not isinstance(kids, list):
                    return "bad", 0
                too_many = len(stack) + len(kids) > MAX_PDF_NODES  # before the extend: a huge Kids array costs nothing
                stack.extend([] if too_many else kids)
            too_many = too_many or pages > MAX_PDF_PAGES or nodes > MAX_PDF_NODES
    except BaseException:  # noqa: BLE001 -- pypdf raises many types, RecursionError and MemoryError included
        return "bad", 0
    if too_many:
        return "many", 0
    return ("ok", pages) if pages >= 1 else ("bad", 0)


def arm_watchdog() -> None:
    """Ends this process hard (exit status 1) WATCHDOG_SECONDS from now, whatever the parser is doing."""
    timer = threading.Timer(WATCHDOG_SECONDS, lambda: os._exit(1))
    timer.daemon = True
    timer.start()


def limit_memory() -> None:
    """RLIMIT_AS where the platform has it (POSIX); a failure to set it is not a reason to refuse every PDF."""
    try:
        resource: Any = __import__("resource")  # not available on Windows

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    except (ImportError, ValueError, OSError):
        pass


def main() -> None:
    arm_watchdog()
    limit_memory()
    status, pages = count(sys.stdin.buffer.read())
    sys.stdout.write(f"{status} {pages}\n")


if __name__ == "__main__":
    main()
