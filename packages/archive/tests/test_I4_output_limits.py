from dataclasses import replace

import pytest
from test_I4_document_parsers import archive
from test_I4_pptx_parser import DRAWING, PRESENTATION, pptx
from test_I4_xlsx_parser import xlsx
from tilo_archive.document_parsers import Limits, Refused, parse_csv, parse_docx, parse_pptx, parse_xlsx


def document(count, text="x"):
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    return archive(
        [
            (
                "[Content_Types].xml",
                b'<Types><Override PartName="/word/document.xml" ContentType="application/vnd.'
                b'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            ),
            (
                "word/document.xml",
                (
                    f'<w:document xmlns:w="{word}">'
                    + f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" * count
                    + "</w:document>"
                ).encode(),
            ),
        ]
    )


def presentation(count, text="x"):
    content = (
        f'<p:sld xmlns:p="{PRESENTATION}" xmlns:a="{DRAWING}">'
        + f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p>" * count
        + "</p:sld>"
    ).encode()
    return pptx([("ppt/slides/slide1.xml", content)])


@pytest.mark.parametrize(
    "parser,data",
    [
        (parse_csv, b"x," * 299 + b"x"),
        (parse_xlsx, xlsx("".join(f'<c r="A{i}"><v>x</v></c>' for i in range(1, 301)))),
        (parse_docx, document(300)),
        (parse_pptx, presentation(300)),
    ],
)
def test_I4_FR_INT_02_output_counts_are_independent_of_zip_entry_budget(parser, data):
    assert len(parser(data, limits=replace(Limits(), entries=3))) == 300


@pytest.mark.parametrize(
    "parser,data,field,code",
    [
        (parse_csv, b"x,x,x", "cells", "cell_count"),
        (parse_xlsx, xlsx('<c r="A1"/><c r="A2"/><c r="A3"/>'), "cells", "cell_count"),
        (parse_docx, document(3, ""), "paragraphs", "paragraph_count"),
        (parse_pptx, presentation(3, ""), "paragraphs", "paragraph_count"),
    ],
)
def test_I4_FR_INT_02_output_caps_count_empty_values_and_refuse_at_boundary(parser, data, field, code):
    parser(data, limits=replace(Limits(), **{field: 3}))
    with pytest.raises(Refused, match=f"^{code}$"):
        parser(data, limits=replace(Limits(), **{field: 2}))


@pytest.mark.parametrize("field,ceiling", [("cells", 8192), ("paragraphs", 4096)])
def test_I4_FR_INT_02_output_caps_have_separate_hard_ceilings(field, ceiling):
    replace(Limits(), **{field: ceiling}).validate()
    for invalid in (0, -1, True, ceiling + 1):
        with pytest.raises(ValueError, match="^invalid_limits$"):
            replace(Limits(), **{field: invalid}).validate()


def test_I4_FR_INT_02_blank_csv_rows_consume_cell_budget():
    assert parse_csv(b"\n\n", limits=replace(Limits(), cells=2)) == ()
    with pytest.raises(Refused, match="^cell_count$"):
        parse_csv(b"\n\n\n", limits=replace(Limits(), cells=2))
