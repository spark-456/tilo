import pytest
from test_I4_output_limits import document, presentation
from test_I4_xlsx_parser import xlsx
from tilo_archive import document_parsers as parsers


@pytest.mark.parametrize(
    "kind,data,read,skipped",
    [
        ("docx", document(1), "hidden text and comments", "page layout"),
        ("xlsx", xlsx('<c r="A1"><v>x</v></c>'), "hidden sheets", "formula evaluation"),
        ("pptx", presentation(1), "hidden slides", "speaker notes"),
        ("csv", b"x", "UTF-8 comma-separated cells", "formula evaluation"),
    ],
    ids=["docx", "xlsx", "pptx", "csv"],
)
def test_I4_FR_INT_02_read_result_returns_citations_and_coverage(kind, data, read, skipped):
    result = parsers.read_document(data, kind=kind)
    assert result.fragments[0][1] == "x"
    assert result.fragments[0][0]
    assert read in result.read
    assert skipped in result.skipped


def test_I4_FR_INT_02_coverage_is_not_returned_for_unreadable_input():
    for kind in ("zip", "html", "docx"):
        with pytest.raises(parsers.Refused):
            parsers.read_document(b"unreadable", kind=kind)


def test_I4_FR_INT_02_read_result_keeps_caller_caps():
    from dataclasses import replace

    with pytest.raises(parsers.Refused, match="^cell_count$"):
        parsers.read_document(b"x,y", kind="csv", limits=replace(parsers.Limits(), cells=1))
