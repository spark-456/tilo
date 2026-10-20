"""DEMO-BROWSER: a session whose caller went away does not keep its browser open.

tilo-api gives up on a call after its timeout, and a run can stop between calls; the session it opened would otherwise
hold a whole Chromium in the service's memory until the instance is replaced. A session nobody has used for the idle
limit is closed the next time a session starts.
"""

from _browser_lib import FakeEngine, FakeWeb, doc

URL = "https://example.org/page"


def _sessions(clock):
    from tilo_browser.session import BrowserSessions

    web = FakeWeb()
    web.add(URL, title="Page", text="Public text", tree=doc())
    engine = FakeEngine(web)
    return BrowserSessions(engine, clock=clock), engine


def _open(sessions, session):
    return sessions.start(
        {
            "session": session,
            "world_id": "w_demo",
            "run_id": "r_demo",
            "unit_id": "U1",
            "allow_hosts": ["example.org"],
            "start_url": URL,
            "viewport": {"width": 1200, "height": 800},
        }
    )


def test_DEMO_BROWSER_idle_session_is_closed_when_the_next_one_starts():
    from tilo_browser.session import IDLE_SECONDS, SessionRefused

    now = [1000.0]
    sessions, engine = _sessions(lambda: now[0])
    _open(sessions, "bs_01JB7A0000000000000000IDL1")
    now[0] += IDLE_SECONDS + 1
    _open(sessions, "bs_01JB7A0000000000000000IDL2")
    assert engine.contexts[0].closed and not engine.contexts[1].closed
    try:
        sessions.act(
            "bs_01JB7A0000000000000000IDL1",
            {"step": 1, "action": {"kind": "extract"}, "digest": None, "outbox_id": None},
        )
    except SessionRefused as refused:
        assert refused.reason == "session_lost"
    else:
        raise AssertionError("an idle session must be gone")


def test_DEMO_BROWSER_a_session_in_use_stays_open():
    from tilo_browser.session import IDLE_SECONDS

    now = [1000.0]
    sessions, engine = _sessions(lambda: now[0])
    _open(sessions, "bs_01JB7A0000000000000000IDL1")
    now[0] += IDLE_SECONDS - 5
    sessions.act(
        "bs_01JB7A0000000000000000IDL1", {"step": 1, "action": {"kind": "extract"}, "digest": None, "outbox_id": None}
    )
    now[0] += IDLE_SECONDS - 5
    _open(sessions, "bs_01JB7A0000000000000000IDL2")
    assert not engine.contexts[0].closed
