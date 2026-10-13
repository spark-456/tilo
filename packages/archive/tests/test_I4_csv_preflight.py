import csv
import io
import random
from dataclasses import replace

import pytest
from tilo_archive import document_parsers as parsers


def test_I4_SEC_05_csv_comma_bomb_refused_before_csv_row_allocation(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("row reader must not materialize the oversized row")

    monkeypatch.setattr(parsers.csv, "reader", forbidden)
    with pytest.raises(parsers.Refused, match="^cell_count$"):
        parsers.parse_csv(b"," * (4 * 1024 * 1024))


@pytest.mark.parametrize("data", [b"a,b,c", b"\n\n\n", b"\r\n\r\n\r\n", b"a\nb\nc"])
def test_I4_SEC_05_csv_preflight_counts_cells_and_blank_records(monkeypatch, data):
    def forbidden(*args, **kwargs):
        pytest.fail("over-budget input must be refused before the row reader")

    monkeypatch.setattr(parsers.csv, "reader", forbidden)
    with pytest.raises(parsers.Refused, match="^cell_count$"):
        parsers.parse_csv(data, limits=replace(parsers.Limits(), cells=2))


@pytest.mark.parametrize(
    "data,expected",
    [
        (b'"a,b\r\nc"', "a,b\r\nc"),
        (b'"a""b,c"', 'a"b,c'),
        (b'"' + b"," * 9000 + b'"', "," * 9000),
        (b'a"b', 'a"b'),
    ],
)
def test_I4_FR_INT_02_csv_preflight_keeps_quoted_separators_and_literal_quotes(data, expected):
    assert parsers.parse_csv(data, limits=replace(parsers.Limits(), cells=1)) == (("csv#r1c1", expected),)


@pytest.mark.parametrize("data,code", [(b"private\xff", "invalid_encoding"), (b'"private', "invalid_csv")])
def test_I4_SEC_05_csv_refusal_retains_no_upload_in_exception_context(data, code):
    with pytest.raises(parsers.Refused, match=f"^{code}$") as error:
        parsers.parse_csv(data)
    assert error.value.__context__ is None
    assert error.value.__cause__ is None


def test_I4_FR_INT_02_csv_preflight_exact_boundary_keeps_empty_cells_and_crlf():
    assert parsers.parse_csv(b"a,\r\n\r\n", limits=replace(parsers.Limits(), cells=3)) == (
        ("csv#r1c1", "a"),
        ("csv#r1c2", ""),
    )


def test_I4_FR_INT_02_csv_preflight_matches_reader_for_recorded_dialect_cases():
    rng = random.Random(4)
    values = ["", "a", "a,b", 'a"b', "a\r\nb", "\r", "\n"]
    for _ in range(100):
        rows = [[rng.choice(values) for _ in range(rng.randrange(4))] for _ in range(rng.randrange(1, 6))]
        stream = io.StringIO(newline="")
        csv.writer(stream, lineterminator="\r\n").writerows(rows)
        data = stream.getvalue().encode()
        count = sum(max(1, len(row)) for row in rows)
        result = parsers.parse_csv(data, limits=replace(parsers.Limits(), cells=count))
        assert result == tuple(
            (f"csv#r{r}c{c}", cell) for r, row in enumerate(rows, 1) for c, cell in enumerate(row, 1)
        )
        if count > 1:
            with pytest.raises(parsers.Refused, match="^cell_count$"):
                parsers.parse_csv(data, limits=replace(parsers.Limits(), cells=count - 1))
