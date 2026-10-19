from dataclasses import replace

import pytest
from test_I4_document_parsers import archive
from tilo_archive.document_parsers import Limits, Refused, parse_xlsx

SHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def xlsx(cells, extras=()):
    return archive(
        [
            (
                "[Content_Types].xml",
                b'<Types><Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
                b'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>',
            ),
            ("xl/workbook.xml", f'<workbook xmlns="{SHEET}"/>'.encode()),
            (
                "xl/worksheets/sheet1.xml",
                f'<worksheet xmlns="{SHEET}"><sheetData><row>{cells}</row></sheetData></worksheet>'.encode(),
            ),
            *extras,
        ]
    )


def test_I4_xlsx_shared_inline_and_cached_values_have_cell_provenance():
    cells = '<c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>inline</t></is></c>'
    cells += '<c r="C1"><f>1+2</f><v>3</v></c><c r="D1"><f>UNSUPPORTED()</f></c>'
    strings = f'<sst xmlns="{SHEET}"><si><r><t>shared </t></r><r><t>text</t></r></si></sst>'
    assert parse_xlsx(xlsx(cells, [("xl/sharedStrings.xml", strings.encode())])) == (
        ("xl/worksheets/sheet1.xml#A1", "shared text"),
        ("xl/worksheets/sheet1.xml#B1", "inline"),
        ("xl/worksheets/sheet1.xml#C1", "3"),
        ("xl/worksheets/sheet1.xml#D1", ""),
    )


@pytest.mark.parametrize(
    "cells",
    [
        '<c r="A1" t="s"><v>7</v></c>',
        '<c r="A1" t="s"><v>-1</v></c>',
        '<c r="A1" t="s"><v>bad</v></c>',
        "<c><v>1</v></c>",
        '<c r="../A1"><v>1</v></c>',
        '<c r="A1"/><c r="A1"/>',
        '<c r="A1" t="unknown"/>',
    ],
)
def test_I4_xlsx_refuses_ambiguous_cells_and_invalid_shared_indices(cells):
    with pytest.raises(Refused, match="^invalid_spreadsheet$"):
        parse_xlsx(xlsx(cells))


@pytest.mark.parametrize(
    "name,value,code",
    [
        ("xl/vbaProject.bin", b"macro", "active_content"),
        ("xl/externalLinks/externalLink1.xml", b"<x/>", "external_reference"),
        ("customXml/item.xml", b'<!DOCTYPE x [<!ENTITY a "bomb">]><x>&a;</x>', "xml_declaration"),
        ("xl/_rels/workbook.xml.rels", b'<Relationship TargetMode="External"/>', "external_reference"),
    ],
)
def test_I4_xlsx_screens_all_parts(name, value, code):
    with pytest.raises(Refused, match=f"^{code}$"):
        parse_xlsx(xlsx("", [(name, value)]))


def test_I4_xlsx_output_and_cell_caps_and_unknown_type():
    for limits, code in [
        (replace(Limits(), output_chars=1), "output_size"),
        (replace(Limits(), cells=3), "cell_count"),
    ]:
        with pytest.raises(Refused, match=f"^{code}$"):
            parse_xlsx(xlsx('<c r="A1"><v>123</v></c><c r="B1"/><c r="C1"/><c r="D1"/>'), limits=limits)
    with pytest.raises(Refused, match="^unknown_type$"):
        parse_xlsx(archive([("renamed.xlsx", b"text")]))


def test_I4_xlsx_hostile_expanded_xml_has_bounded_peak_and_time():
    from test_I4_xml_allocation import assert_bounded_refusal, compressed_office, hostile_xml

    data = compressed_office(
        "xl/workbook.xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        f'<workbook xmlns="{SHEET}"/>'.encode(),
        [("xl/worksheets/hostile.xml", hostile_xml("flat"))],
    )
    assert_bounded_refusal(parse_xlsx, data, replace(Limits(), expanded_bytes=32 * 1024 * 1024))
