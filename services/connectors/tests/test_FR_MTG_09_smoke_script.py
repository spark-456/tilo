"""FR-MTG-09 (live smoke script, the user only): `services/connectors/scripts/live_meeting_host_smoke.py`.
API_FR_MTG_09.md "First live step (the user only)" and "Builder notes": one command, `LIVE=1` plus `GOOGLE_OAUTH_*`,
modelled on `live_gmail_smoke.py` (`main(argv, *, environ, out)`, returns 1 when stopped): the browser opens
Google's consent page, the person signs in as the bot, the script creates one event and prints the conference
status and the event id, never the link.

Only the parts that are safe offline are tested: the script exists, it stops without `LIVE=1` before any network,
it needs `--invite`, and it cannot print a link. The live run itself is the user's (EFF-01); `LIVE` stays unset here
and every socket call raises (autouse guard in `_meeting_host_lib`).

Every test fails today: the script does not exist.
"""

from __future__ import annotations

import importlib.util
import io

import pytest
from _meeting_host_lib import (
    SCRIPT,
    module_source,
    no_network_and_no_live,  # noqa: F401 - autouse guard
)

INVITE = "tilo.smoke.target@example.com"


def script():
    assert SCRIPT.is_file(), "services/connectors/scripts/live_meeting_host_smoke.py does not exist yet"
    spec = importlib.util.spec_from_file_location("live_meeting_host_smoke_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_FR_MTG_09_smoke_the_script_exists_with_a_main_and_a_main_guard():
    module = script()

    assert callable(module.main)
    source = module_source(SCRIPT)
    assert '__name__ == "__main__"' in source or "__name__ == '__main__'" in source


@pytest.mark.parametrize("environ", [{}, {"LIVE": ""}, {"LIVE": "0"}, {"LIVE": "true"}, {"LIVE": " 1"}, {"LIVE": "01"}])
def test_FR_MTG_09_smoke_without_LIVE_equal_to_1_it_stops_before_any_network_and_names_the_switch(environ):
    out = io.StringIO()

    code = script().main(["--invite", INVITE, "--start-in-min", "30"], environ=environ, out=out)

    assert code == 1, "stopped, not crashed"
    assert "LIVE=1" in out.getvalue(), "it says how the user turns it on"
    assert INVITE not in out.getvalue(), "it never echoes the address"


def test_FR_MTG_09_smoke_the_invite_address_is_required():
    with pytest.raises(SystemExit) as stopped:
        script().main(["--start-in-min", "30"], environ={}, out=io.StringIO())

    assert stopped.value.code != 0


def test_FR_MTG_09_smoke_it_prints_the_conference_status_and_event_id_and_can_never_print_the_link():
    source = module_source(SCRIPT)

    for link_field in ("hangoutLink", "htmlLink", "entryPoints", "meet.google.com"):
        assert link_field not in source, f"the script cannot read or print {link_field}"
    assert "LIVE" in source, "the EFF-01 gate is in the script's own path"


def test_FR_MTG_09_smoke_it_asks_only_for_the_host_scope():
    source = module_source(SCRIPT)

    assert "calendar.events" not in source.replace("calendar.events.owned", ""), "no wider scope"
    for scope in ("gmail", "drive", "calendar.readonly"):
        assert f"auth/{scope}" not in source
