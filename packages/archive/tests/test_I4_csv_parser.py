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
        (b"a,b", replace(Limits(), entries=1), "entry_count"),
        (b"abc", replace(Limits(), output_chars=2), "output_size"),
    ],
)
def test_I4_csv_enforces_input_cell_and_text_caps(data, limits, code):
    with pytest.raises(Refused, match=f"^{code}$"):
        parse_csv(data, limits=limits)


def test_I4_csv_refuses_invalid_limits():
    with pytest.raises(ValueError, match="^invalid_limits$"):
        parse_csv(b"a", limits=replace(Limits(), entries=0))


@pytest.mark.parametrize("data", [b"bad\xff", b'"unterminated'])
def test_I4_csv_refusal_carries_no_uploaded_exception_context(data):
    with pytest.raises(Refused) as caught:
        parse_csv(data)
    assert caught.value.__context__ is None


def test_I4_csv_wide_hostile_row_is_refused_before_csv_reader_allocates(monkeypatch):
    import tilo_archive.document_parsers as parsers

    def forbidden(*args, **kwargs):
        raise AssertionError("wide row reached the allocating CSV reader")

    monkeypatch.setattr(parsers.csv, "reader", forbidden)
    with pytest.raises(Refused, match="^entry_count$"):
        parse_csv(b"," * (4 * 1024 * 1024))


def test_I4_csv_width_guard_preserves_quoted_commas_escapes_and_multiline():
    cell = "," * 1000
    assert parse_csv(f'"{cell}","a""b\nc"\r\n'.encode(), limits=replace(Limits(), entries=2)) == (
        ("csv#r1c1", cell),
        ("csv#r1c2", 'a"b\nc'),
    )
    assert parse_csv(b'a"b,c', limits=replace(Limits(), entries=2))[0][1] == 'a"b'


def test_I4_csv_blank_rows_count_towards_entry_budget_at_exact_boundary():
    limits = replace(Limits(), entries=2)
    assert parse_csv(b"\n\n", limits=limits) == ()
    with pytest.raises(Refused, match="^entry_count$"):
        parse_csv(b"\n\n\n", limits=limits)
