import base64
import io
import random
import time
import tracemalloc
import zipfile
from dataclasses import replace

import pytest
from test_I4_document_parsers import WORD, archive, docx
from tilo_archive.document_parsers import Limits, Refused, parse_docx


def test_I4_xml_node_budget_is_total_across_parts():
    main = f'<w:document xmlns:w="{WORD}"><w:p><w:t>ok</w:t></w:p></w:document>'.encode()
    data = docx(main, [(f"customXml/{n}.xml", b"<x><a/><b/></x>") for n in range(3)])
    with pytest.raises(Refused, match="^xml_nodes$"):
        parse_docx(data, limits=replace(Limits(), xml_nodes=8))


def hostile_xml(shape):
    # Entropy keeps the expanded 16 MiB fixture BELOW the accepted 100:1 ratio.
    salt = b"<!--" + base64.b64encode(random.Random(4).randbytes(300_000)) + b"-->"
    target = 16 * 1024 * 1024
    if shape == "flat":
        body = b"<a/>" * ((target - len(salt)) // 4)
    elif shape == "deep":
        n = (target - len(salt)) // 7
        body = b"<a>" * n + b"</a>" * n
    elif shape == "attributes":
        body = b"<a " + b" ".join(f'a{n}="x"'.encode() for n in range(1_500_000)) + b"/>"
    else:
        raise AssertionError(shape)
    return b"<x>" + salt + body + b"</x>"


def compressed_office(main, kind, root, extras):
    stream = io.BytesIO()
    entries = [
        ("[Content_Types].xml", f'<Types><Override PartName="/{main}" ContentType="{kind}"/></Types>'.encode()),
        (main, root),
        *extras,
    ]
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as handle:
        for name, value in entries:
            handle.writestr(name, value)
    data = stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        assert sum(info.file_size for info in handle.infolist()) >= 16 * 1024 * 1024
        assert all(info.file_size <= 100 * max(1, info.compress_size) for info in handle.infolist())
    assert len(data) <= Limits().input_bytes
    return data


def assert_bounded_refusal(parser, data, limits=Limits()):
    tracemalloc.start()
    started = time.monotonic()
    try:
        with pytest.raises(Refused):
            parser(data, limits=limits)
        assert tracemalloc.get_traced_memory()[1] < 80 * 1024 * 1024
        assert time.monotonic() - started < 5
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("shape", ["flat", "deep", "attributes", "parts"])
def test_I4_docx_hostile_expanded_xml_has_bounded_peak_and_time(shape):
    root = f'<w:document xmlns:w="{WORD}"/>'.encode()
    if shape == "parts":
        part = b"<x>" + b"<a/>" * 15_000 + b"<pad>" + b"x" * 110_000 + b"</pad></x><!--"
        part += base64.b64encode(random.Random(7).randbytes(5_000)) + b"-->"
        extras = [(f"customXml/{n}.xml", part) for n in range(110)]
    else:
        extras = [("customXml/hostile.xml", hostile_xml(shape))]
    data = compressed_office(
        "word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        root,
        extras,
    )
    assert_bounded_refusal(parse_docx, data, replace(Limits(), expanded_bytes=32 * 1024 * 1024))


def test_I4_xml_attribute_budget_is_total_and_single_part_bytes_are_capped():
    root = f'<w:document xmlns:w="{WORD}"/>'.encode()
    with pytest.raises(Refused, match="^xml_attributes$"):
        parse_docx(
            docx(root, [("a.xml", b'<x a="1" b="2"/>'), ("b.xml", b'<x c="3" d="4"/>')]),
            limits=replace(Limits(), xml_attributes=5),
        )
    with pytest.raises(Refused, match="^xml_part_size$"):
        parse_docx(docx(root), limits=replace(Limits(), xml_part_bytes=16))


@pytest.mark.parametrize(
    "name",
    [
        "bidi\u202e.xml",
        "del\x7f.xml",
        "c1\x85.xml",
        "line\u2028.xml",
        "paragraph\u2029.xml",
        "private\ue000.xml",
        "unassigned\u0378.xml",
    ],
)
def test_I4_labels_refuse_display_controls(name):
    from tilo_archive.document_parsers import expand_zip

    with pytest.raises(Refused, match="^unsafe_path$"):
        expand_zip(archive([(name, b"inert")]))


@pytest.mark.parametrize("names", [("A.xml", "a.xml"), ("\u00e9.xml", "e\u0301.xml")])
def test_I4_labels_refuse_case_and_normalization_twins(names):
    from tilo_archive.document_parsers import expand_zip

    with pytest.raises(Refused, match="^duplicate_path$"):
        expand_zip(archive([(name, b"inert") for name in names]))


def test_I4_refusal_does_not_retain_uploaded_error_context():
    from tilo_archive.document_parsers import expand_zip

    for operation, data in [(expand_zip, b"not zip"), (parse_docx, docx(b"<x>"))]:
        with pytest.raises(Refused) as caught:
            operation(data)
        assert caught.value.__context__ is None


@pytest.mark.parametrize("field", ["nesting", "expanded_bytes", "xml_nodes", "xml_attributes", "xml_part_bytes"])
def test_I4_limit_configuration_cannot_remove_hard_resource_ceilings(field):
    with pytest.raises(ValueError, match="^invalid_limits$"):
        parse_docx(b"", limits=replace(Limits(), **{field: 10**9}))


@pytest.mark.parametrize(
    "xml,code",
    [
        (b'<x Target="http://x"/>', "external_reference"),
        (b'<x Target="//h/x"/>', "external_reference"),
        (b'<x Target="\\\\host/share"/>', "external_reference"),
        (b'<x Type="urn:oleObject"/>', "active_content"),
        (b'<x Type="urn:activeX"/>', "active_content"),
        (b'<x ContentType="application/macroEnabled"/>', "active_content"),
    ],
)
def test_I4_xml_surviving_security_mutants_are_refused(xml, code):
    with pytest.raises(Refused, match=f"^{code}$"):
        parse_docx(docx(b"<x/>", [("customXml/item.xml", xml)]))


def test_I4_content_types_bytes_are_screened_even_outside_contenttype_attribute():
    with pytest.raises(Refused, match="^active_content$"):
        types = b'<Types note="macroEnabled"><Override PartName="/word/document.xml" '
        types += (
            b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
        )
        parse_docx(archive([("[Content_Types].xml", types), ("word/document.xml", b"<x/>")]))


def test_I4_labels_refuse_surrogates_before_encoding():
    from tilo_archive.document_parsers import _path

    with pytest.raises(Refused, match="^unsafe_path$"):
        _path("surrogate\ud800.xml", Limits())
