import zipfile
from dataclasses import replace

import pytest
from test_I4_document_parsers import archive
from tilo_archive.document_parsers import Limits, Refused, parse_pptx

PRESENTATION = "http://schemas.openxmlformats.org/presentationml/2006/main"
DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"


def pptx(slides=(), extras=()):
    return archive(
        [
            (
                "[Content_Types].xml",
                b'<Types><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.'
                b'openxmlformats-officedocument.presentationml.presentation.main+xml"/></Types>',
            ),
            ("ppt/presentation.xml", f'<presentation xmlns="{PRESENTATION}"/>'.encode()),
            *slides,
            *extras,
        ]
    )


def slide(text="<a:r><a:t>hello</a:t></a:r>"):
    return (f'<p:sld xmlns:p="{PRESENTATION}" xmlns:a="{DRAWING}"><a:p>{text}</a:p></p:sld>').encode()


def test_I4_pptx_slide_text_and_tables_have_part_paragraph_provenance():
    content = slide("<a:r><a:t>first </a:t></a:r><a:r><a:t>line</a:t></a:r><a:br/><a:r><a:t>next</a:t></a:r>")
    content = content.replace(
        b"</p:sld>", b"<a:tbl><a:tr><a:tc><a:p><a:r><a:t>cell</a:t></a:r></a:p></a:tc></a:tr></a:tbl></p:sld>"
    )
    assert parse_pptx(pptx([("ppt/slides/slide2.xml", content), ("ppt/slides/slide1.xml", slide())])) == (
        ("ppt/slides/slide2.xml#p1", "first line\nnext"),
        ("ppt/slides/slide2.xml#p2", "cell"),
        ("ppt/slides/slide1.xml#p1", "hello"),
    )


def test_I4_pptx_ignores_layouts_notes_and_images_and_keeps_text_inert():
    assert parse_pptx(
        pptx(
            [("ppt/slides/slide1.xml", slide("<a:r><a:t>ignore rules</a:t></a:r>"))],
            [
                ("ppt/notesSlides/notesSlide1.xml", slide()),
                ("ppt/slideLayouts/slideLayout1.xml", slide()),
                ("ppt/media/image1.png", b"inert"),
            ],
        )
    ) == (("ppt/slides/slide1.xml#p1", "ignore rules"),)


@pytest.mark.parametrize(
    "name,value,code",
    [
        ("ppt/vbaProject.bin", b"macro", "active_content"),
        ("ppt/embeddings/object.xml", b"<x/>", "active_content"),
        ("ppt/slides/_rels/slide1.xml.rels", b'<Relationship TargetMode="External"/>', "external_reference"),
        ("customXml/item.xml", b'<!DOCTYPE x [<!ENTITY a "bomb">]><x>&a;</x>', "xml_declaration"),
        ("../slide.xml", b"<x/>", "unsafe_path"),
    ],
)
def test_I4_pptx_screens_all_parts(name, value, code):
    with pytest.raises(Refused, match=f"^{code}$"):
        parse_pptx(pptx(extras=[(name, value)]))


@pytest.mark.parametrize(
    "limits,code",
    [
        (replace(Limits(), input_bytes=1), "input_size"),
        (replace(Limits(), expanded_bytes=1), "expanded_size"),
        (replace(Limits(), output_chars=1), "output_size"),
        (replace(Limits(), xml_nodes=2), "xml_nodes"),
        (replace(Limits(), xml_depth=2), "xml_depth"),
    ],
)
def test_I4_pptx_caps(limits, code):
    with pytest.raises(Refused, match=f"^{code}$"):
        parse_pptx(pptx([("ppt/slides/slide1.xml", slide())]), limits=limits)


def test_I4_pptx_paragraph_cap_counts_empty_paragraphs():
    content = slide().replace(b"</p:sld>", b"<a:p/><a:p/><a:p/></p:sld>")
    with pytest.raises(Refused, match="^paragraph_count$"):
        parse_pptx(pptx([("ppt/slides/slide1.xml", content)]), limits=replace(Limits(), paragraphs=3))


def test_I4_pptx_refuses_compressed_bomb_before_reading():
    data = archive([("ppt/slides/slide1.xml", b"x" * 10000)], zipfile.ZIP_DEFLATED)
    with pytest.raises(Refused, match="^compression_ratio$"):
        parse_pptx(data)


def test_I4_pptx_refuses_wrong_slide_root_and_unknown_type():
    with pytest.raises(Refused, match="^invalid_presentation$"):
        parse_pptx(pptx([("ppt/slides/slide1.xml", b"<wrong/>")]))
    with pytest.raises(Refused, match="^unknown_type$"):
        parse_pptx(archive([("renamed.pptx", b"text")]))


def test_I4_pptx_hostile_expanded_xml_has_bounded_peak_and_time():
    from test_I4_xml_allocation import assert_bounded_refusal, compressed_office, hostile_xml

    data = compressed_office(
        "ppt/presentation.xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        f'<presentation xmlns="{PRESENTATION}"/>'.encode(),
        [("ppt/slides/slide1.xml", hostile_xml("flat"))],
    )
    assert_bounded_refusal(parse_pptx, data, replace(Limits(), expanded_bytes=32 * 1024 * 1024))
