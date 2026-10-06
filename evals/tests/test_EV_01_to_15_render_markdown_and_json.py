"""EV-01..EV-15 rendering (PRD 19.3 "counts first, then percentages"; PRD 3.5): `render_markdown(rows, *, build_hash,
now_utc)` and `render_json(rows)` in `tilo_evals.metrics_report`. The caller passes the clock and the build hash, so
rendering is a pure function of its input.

Pinned: the table header cells are ID | Metric | Basis | Status | Value | n | Target; a share row prints
"3 of 4 (75%)" (counts, then percent); a needs_live_or_pilot row prints "needs live or pilot data" and a no_data row
"no data"; a "## Method and gaps" section lists each row's method and note; `render_json` returns a JSON-serialisable
dict whose "rows" are the MetricRow fields."""

import dataclasses
import json
import re

import pytest
from _metrics_lib import CLAIM_SENTENCE, EV_IDS, compute, metric_row, metrics_report

BUILD, NOW = "abc1234", "2026-10-06T09:30:00Z"


def _render(rows):
    return metrics_report().render_markdown(rows, build_hash=BUILD, now_utc=NOW)


def _table_rows(text):
    lines = [ln for ln in text.splitlines() if ln.startswith("|")]
    cells = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    return cells[0], [c for c in cells[1:] if not set("".join(c)) <= set("-: ")]


def _sample_rows():
    return [
        metric_row(),
        metric_row(
            id="EV-02",
            name="Time to first plan",
            target="p50 <= 12 s; p95 <= 25 s",
            basis=None,
            status="needs_live_or_pilot",
            value=None,
            n=0,
            of=0,
            method="Needs live wall-clock latency from real intake runs.",
            note="0 cases measure this, 0 recorded.",
        ),  # fmt: skip
        metric_row(
            id="EV-06",
            name="Recovery rate",
            target=">= 70%",
            basis=None,
            status="no_data",
            value=None,
            n=0,
            of=0,
            method="Needs failed steps; the chaos suite with 10% tool failures produces them.",
            note="0 cases measure this, 0 recorded.",
        ),  # fmt: skip
        metric_row(
            id="EV-07",
            name="Cost per task",
            target="Reported",
            basis="scripted_fakes",
            value=3.52,
            n=1,
            of=1,
            method="Mean credits_used of runs that reached world.completed.",
            note="mechanics only. 1 run; USD 0.0176. 38 cases measure this, 0 recorded.",
        ),  # fmt: skip
    ]


def test_EV_01_to_15_markdown_headline_states_scope_build_and_time_before_the_table():
    text = _render(_sample_rows())

    first = text.splitlines()[0]
    assert first.startswith("# ") and "metric" in first.lower()
    assert CLAIM_SENTENCE in text and text.index(CLAIM_SENTENCE) < text.index("\n|")
    assert BUILD in text and NOW in text
    assert "## Method and gaps" in text


def test_EV_01_to_15_markdown_table_has_the_pinned_columns_and_one_line_per_row():
    header, body = _table_rows(_render(_sample_rows()))

    assert [h.lower() for h in header] == ["id", "metric", "basis", "status", "value", "n", "target"]
    assert [row[0] for row in body] == ["EV-01", "EV-02", "EV-06", "EV-07"], "rows keep their order"
    assert all(len(row) == 7 for row in body)


def test_EV_01_to_15_a_share_prints_counts_first_then_the_percent():
    _, body = _table_rows(_render([metric_row()]))

    value_cell = body[0][4]
    assert re.fullmatch(r"3 of 4 \(75%\)", value_cell), value_cell


def test_EV_01_to_15_a_needs_live_row_prints_the_phrase_its_method_and_no_number():
    text = _render(_sample_rows())
    _, body = _table_rows(text)
    ev02 = next(r for r in body if r[0] == "EV-02")

    assert "needs live or pilot data" in ev02[3]
    assert not re.search(r"\d", ev02[4]), f"no number for a live-only metric: {ev02[4]!r}"
    method_section = text.split("## Method and gaps", 1)[1]
    assert "Needs live wall-clock latency from real intake runs." in method_section


def test_EV_01_to_15_a_no_data_row_prints_no_data_and_no_number():
    _, body = _table_rows(_render(_sample_rows()))
    ev06 = next(r for r in body if r[0] == "EV-06")

    assert "no data" in ev06[3]
    assert not re.search(r"\d", ev06[4])


def test_EV_01_to_15_each_row_basis_is_printed_and_a_basis_less_row_shows_a_dash():
    _, body = _table_rows(_render(_sample_rows()))

    assert body[0][2] == "recorded" and body[3][2] == "scripted_fakes"
    assert body[1][2] in ("-", "—", "n/a", "none")


def test_EV_01_to_15_every_rows_method_and_note_are_printed_in_the_method_and_gaps_section():
    rows = _sample_rows()

    section = _render(rows).split("## Method and gaps", 1)[1]

    for row in rows:
        assert row.method in section, f"{row.id} method missing"
        assert row.note in section, f"{row.id} note (with its coverage) missing"


def test_EV_01_to_15_rendering_is_deterministic_lf_only_and_takes_its_clock_from_the_caller():
    rows = _sample_rows()

    first, second = _render(rows), _render(rows)

    assert first == second
    assert "\r" not in first and first.endswith("\n")
    other = metrics_report().render_markdown(rows, build_hash=BUILD, now_utc="2030-01-01T00:00:00Z")
    assert other != first and other.replace("2030-01-01T00:00:00Z", NOW) == first, "only the caller's time differs"


def test_EV_01_to_15_markdown_of_an_empty_run_set_still_lists_all_fifteen_ids():
    text = _render(compute([]))

    _, body = _table_rows(text)
    assert [r[0] for r in body] == list(EV_IDS)


def test_EV_01_to_15_render_json_is_serialisable_and_keeps_every_field_including_none():
    rows = _sample_rows()

    payload = metrics_report().render_json(rows)
    decoded = json.loads(json.dumps(payload))

    assert [r["id"] for r in decoded["rows"]] == ["EV-01", "EV-02", "EV-06", "EV-07"]
    expected = {f.name for f in dataclasses.fields(rows[0])}
    assert all(set(r) == expected for r in decoded["rows"])
    ev02 = decoded["rows"][1]
    assert ev02["value"] is None and ev02["basis"] is None and ev02["status"] == "needs_live_or_pilot"


@pytest.mark.parametrize("bad", [0.75, 3.52])
def test_EV_01_to_15_json_values_are_the_row_values_not_rounded_strings(bad):
    payload = metrics_report().render_json([metric_row(value=bad)])

    assert payload["rows"][0]["value"] == bad
