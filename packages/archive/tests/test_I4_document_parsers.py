import io
import zipfile
from dataclasses import replace

import pytest
from tilo_archive.document_parsers import Limits, Refused, expand_zip, parse_docx


def archive(entries, compression=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as handle:
        for name, value in entries:
            handle.writestr(name, value)
    data = stream.getvalue()
    # Windows ZipInfo normalizes backslashes while writing; restore hostile bytes.
    for name, _ in entries:
        if "\\" in name:
            data = data.replace(name.replace("\\", "/").encode(), name.encode())
    return data


def test_I4_zip_expansion_is_bytes_only_and_deterministic():
    data = archive([("b.txt", b"two"), ("folder/a.txt", b"one")])
    assert expand_zip(data) == (("b.txt", b"two"), ("folder/a.txt", b"one"))


@pytest.mark.parametrize("name", ["../x", "/x", "C:/x", "a\\x", "a/../x", "a//x", "a/./x"])
def test_I4_zip_refuses_path_traversal(name):
    with pytest.raises(Refused, match="^unsafe_path$"):
        expand_zip(archive([(name, b"x")]))


def test_I4_zip_refuses_bomb_before_reading():
    data = archive([("large", b"x" * 10000)], zipfile.ZIP_DEFLATED)
    with pytest.raises(Refused, match="^compression_ratio$"):
        expand_zip(data)


@pytest.mark.parametrize(
    "field,code",
    [
        ("input_bytes", "input_size"),
        ("expanded_bytes", "expanded_size"),
        ("entries", "entry_count"),
        ("path_depth", "path_depth"),
    ],
)
def test_I4_zip_caps(field, code):
    limits = replace(Limits(), **{field: 1})
    with pytest.raises(Refused, match=f"^{code}$"):
        expand_zip(archive([("a/b", b"xx"), ("c", b"y")]), limits=limits)


def test_I4_zip_nested_budget_and_depth_are_shared():
    nested = archive([("inner", archive([("leaf", b"1234")]))])
    assert expand_zip(nested) == (("inner/leaf", b"1234"),)
    for limits, code in [
        (replace(Limits(), nesting=0), "nesting"),
        (replace(Limits(), entries=1), "entry_count"),
        (replace(Limits(), expanded_bytes=110), "expanded_size"),
    ]:
        with pytest.raises(Refused, match=f"^{code}$"):
            expand_zip(nested, limits=limits)


def test_I4_zip_refuses_duplicates_and_symlinks():
    with pytest.warns(UserWarning):
        data = archive([("same", b"a"), ("same", b"b")])
    with pytest.raises(Refused, match="^duplicate_path$"):
        expand_zip(data)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as handle:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        handle.writestr(info, "target")
    with pytest.raises(Refused, match="^special_entry$"):
        expand_zip(stream.getvalue())


@pytest.mark.parametrize("data", [b"not a zip", b"PK\x03\x04broken"])
def test_I4_zip_refuses_malformed_without_echoing_content(data):
    with pytest.raises(Refused, match="^invalid_zip$"):
        expand_zip(data)


def test_I4_zip_refuses_invalid_limits():
    with pytest.raises(ValueError, match="invalid_limits"):
        expand_zip(b"", limits=replace(Limits(), expanded_bytes=0))


def test_I4_zip_refuses_nested_output_collisions():
    data = archive([("inner", archive([("leaf", b"a")])), ("inner/leaf", b"b")])
    with pytest.raises(Refused, match="^duplicate_path$"):
        expand_zip(data)


def test_I4_zip_refuses_encrypted_flags_without_password_requests():
    data = bytearray(archive([("leaf", b"x")]))
    data[6] |= 1
    data[data.index(b"PK\x01\x02") + 8] |= 1
    with pytest.raises(Refused, match="^encrypted_zip$"):
        expand_zip(bytes(data))


def test_I4_zip_refuses_unsupported_compression_and_bad_crc():
    with pytest.raises(Refused, match="^compression_method$"):
        expand_zip(archive([("leaf", b"x")], zipfile.ZIP_BZIP2))
    data = bytearray(archive([("leaf", b"private-content")]))
    data[34] ^= 1
    with pytest.raises(Refused, match="^invalid_zip$"):
        expand_zip(bytes(data))


WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx(xml, extras=()):
    return archive(
        [
            (
                "[Content_Types].xml",
                b'<Types><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
                b'officedocument.wordprocessingml.document.main+xml"/></Types>',
            ),
            ("word/document.xml", xml),
            *extras,
        ]
    )


def test_I4_docx_reads_text_with_part_and_paragraph_provenance():
    xml = f'<w:document xmlns:w="{WORD}"><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:document>'.encode()
    assert parse_docx(docx(xml)) == (("word/document.xml#p1", "Hello"),)


@pytest.mark.parametrize(
    "xml,code",
    [
        (b'<!DOCTYPE x [<!ENTITY a "bomb">]><x>&a;</x>', "xml_declaration"),
        (b"<x>", "invalid_xml"),
        (b'<Relationship TargetMode="External" Target="https://example.invalid"/>', "external_reference"),
        (b'<x xml:base="https://example.invalid"/>', "external_reference"),
    ],
)
def test_I4_docx_refuses_hostile_xml_in_any_part(xml, code):
    with pytest.raises(Refused, match=f"^{code}$"):
        parse_docx(docx(b"<x/>", [("customXml/item.xml", xml)]))


def test_I4_docx_refuses_macros_unknown_types_and_output_overflow():
    with pytest.raises(Refused, match="^active_content$"):
        parse_docx(docx(b"<x/>", [("word/vbaProject.bin", b"macro")]))
    with pytest.raises(Refused, match="^unknown_type$"):
        parse_docx(archive([("renamed.docx", b"not office")]))
    xml = f'<w:document xmlns:w="{WORD}"><w:p><w:t>too much</w:t></w:p></w:document>'.encode()
    with pytest.raises(Refused, match="^output_size$"):
        parse_docx(docx(xml), limits=replace(Limits(), output_chars=1))


def test_I4_docx_xml_depth_and_node_caps():
    for limits, code in [(replace(Limits(), xml_depth=1), "xml_depth"), (replace(Limits(), xml_nodes=1), "xml_nodes")]:
        with pytest.raises(Refused, match=f"^{code}$"):
            parse_docx(docx(b"<a><b/></a>"), limits=limits)
