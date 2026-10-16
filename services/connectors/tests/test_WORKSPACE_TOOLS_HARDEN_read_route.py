"""WORKSPACE_TOOLS hardening pass (security review follow-ups, ADR-0048 WT-02, WT-03, HB-06): tilo-connectors half.

Hostile HTML cannot make the text stripper slow, a window out of the calendar range is invalid_request, a trashed Drive
file and an attachment list over 20 are cut as the contract says, and a person whose disconnect has begun is read
nothing, as an execute is refused. Same rig and fakes as test_WORKSPACE_TOOLS_A_read_route.py: no network, no paid call.
"""

from __future__ import annotations

import time

import pytest
from _meeting_host_lib import OWNER
from _workspace_lib import file_part, header_list, text_part
from test_WORKSPACE_TOOLS_A_read_route import WINDOW, WRig, mail
from tilo_connectors.adapters.calendar import window
from tilo_connectors.adapters.gmail import _text_of_html


@pytest.mark.parametrize(
    "markup",
    [
        "<a " * 20000,
        "<!--" * 20000,
        "<script>" * 20000,
        "<" * 20000,
        "<a x='" * 20000,
        "</" * 20000,
        "<!" * 20000,
        "<a>" * 20000,
        "<p>x</p>" * 20000,
        "<style>" + "<" * 30000,
        "&amp;" * 50000,
    ],
    ids=[
        "open-tag",
        "open-comment",
        "open-script",
        "lt",
        "open-quote",
        "end-open",
        "bang",
        "tags",
        "blocks",
        "style",
        "entities",
    ],
)
def test_WORKSPACE_TOOLS_HARDEN_the_html_stripper_is_linear_on_hostile_input(markup: str) -> None:
    started = time.monotonic()
    got = _text_of_html(markup)
    assert time.monotonic() - started < 1.0 and isinstance(got, str)


def test_WORKSPACE_TOOLS_HARDEN_the_html_stripper_still_keeps_the_text_and_drops_the_rest() -> None:
    html = "<!doctype html><HEAD><title>t</title></HEAD><body><!-- note --><p>Hi <b>there</b> &amp; a < b</p>"
    html += "<SCRIPT>x()</SCRIPT>"
    got = _text_of_html(html + "<div>end</div><br/>last")
    assert "Hi there & a < b" in got and "end" in got and "last" in got
    assert "note" not in got and "x()" not in got and got.startswith("Hi")


def test_ADR_0048_WT_03_malformed_numeric_entity_remains_undecoded() -> None:
    markup = "&#" + "9" * 5000
    assert _text_of_html(markup) == markup


@pytest.mark.parametrize(
    ("markup", "visible"),
    [
        ("\u0130" * 18 + "</script><script>xx>LEAK</script>shown", "shown"),
        ("\u0130" * 20 + "<script>hidden</script>VISIBLE", "VISIBLE"),
    ],
)
def test_ADR_0048_WT_03_unicode_casefold_cannot_shift_hidden_tag_boundary(markup: str, visible: str) -> None:
    got = _text_of_html(markup)
    assert got.endswith(visible)
    assert "LEAK" not in got and "hidden" not in got


@pytest.mark.parametrize("zone", ["-05:00", "-23:59"])
def test_WORKSPACE_TOOLS_HARDEN_a_window_out_of_the_calendar_range_is_invalid_request_not_an_error(zone: str) -> None:
    start, end = f"9999-12-31T23:00:00{zone}", f"9999-12-31T23:30:00{zone}"  # year 10000 in UTC
    with pytest.raises(ValueError):
        window(start, end)
    rig = WRig()
    response = rig.raw({"user_id": OWNER, "tool": "read_events", "args": {"start": start, "end": end}})
    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert rig.google.requests == []


def test_WORKSPACE_TOOLS_HARDEN_the_normal_window_still_passes() -> None:
    assert window(WINDOW["start"], WINDOW["end"])[0] < window(WINDOW["start"], WINDOW["end"])[1]


def test_WORKSPACE_TOOLS_HARDEN_a_trashed_drive_file_is_not_found() -> None:
    rig = WRig()
    rig.google.add_file("t1", "gone.txt", "text/plain", b"x", trashed=True)
    assert rig.read("read_file", {"file_id": "t1"})["outcome"] == "not_found"
    assert not [r for r in rig.google.requests if r[2].get("alt") == "media"]  # not even downloaded


def test_WORKSPACE_TOOLS_HARDEN_a_message_with_over_20_attachments_lists_20() -> None:
    rig = WRig()
    payload = {
        "mimeType": "multipart/mixed",
        "headers": mail()["headers"] + header_list(To="me@example.org"),
        "parts": [text_part("body"), *[file_part(f"f{n}.pdf", "application/pdf", n) for n in range(25)]],
    }
    rig.google.add_message("m1", payload)
    got = rig.read("read_email", {"message_id": "m1"})["result"]
    assert len(got["attachments"]) == 20 and got["attachments"][0]["filename"] == "f0.pdf"


def test_WORKSPACE_TOOLS_HARDEN_a_person_whose_disconnect_has_begun_is_read_nothing() -> None:
    rig = WRig()
    with rig.rig.runtime.closing(OWNER):
        got = rig.read("search_email", {"query": "x"})
    assert (got["outcome"], got["result"], got["connected_at"]) == ("not_connected", None, None)
    assert rig.google.requests == []
    rig.google.add_message("m1", mail())
    assert rig.read("search_email", {"query": "x"})["outcome"] == "ok"  # and reads again once it has ended
