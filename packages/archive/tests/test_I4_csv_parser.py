from dataclasses import replace

import pytest
from tilo_archive.document_parsers import Limits, Refused, parse_csv


def test_I4_csv_reads_utf8_bom_quotes_and_multiline_with_cell_provenance():
    data = '\ufeffname,note\r\n"Jos,na","first\nsecond"\r\n'.encode()
    assert parse_csv(data) == (
        ("csv#r1c1", "name"),
        ("csv#r1c2", "note"),
        ("csv#r2c1", "Jos,na"),
        ("csv#r2c2", "first\nsecond"),
    )


def test_I4_csv_preserves_empty_cells_and_formula_text_without_execution():
    assert parse_csv(b",=1+2,\n") == (
        ("csv#r1c1", ""),
        ("csv#r1c2", "=1+2"),
        ("csv#r1c3", ""),
    )
    assert parse_csv(b"") == ()


@pytest.mark.parametrize(
    "data,code",
    [
        (b'"unterminated', "invalid_csv"),
        (b'"closed"suffix,x', "invalid_csv"),
        (b"bad\xff", "invalid_encoding"),
        (b"binary\x00", "invalid_csv"),
    ],
)
def test_I4_csv_refuses_malformed_or_binary_without_echo(data, code):
    with pytest.raises(Refused, match=f"^{code}$"):
        parse_csv(data)


@pytest.mark.parametrize(
    "data,limits,code",
    [
        (b"abc", replace(Limits(), input_bytes=2), "input_size"),
        (b"a,b", replace(Limits(), cells=1), "cell_count"),
        (b"abc", replace(Limits(), output_chars=2), "output_size"),
    ],
)
def test_I4_csv_enforces_input_cell_and_text_caps(data, limits, code):
    with pytest.raises(Refused, match=f"^{code}$"):
        parse_csv(data, limits=limits)


def test_I4_csv_refuses_invalid_limits():
    with pytest.raises(ValueError, match="^invalid_limits$"):
        parse_csv(b"a", limits=replace(Limits(), entries=0))
