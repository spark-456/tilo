"""FR-MTG-09: when the bot leaves on its own (MEETING-LOOP-DESIGN item 4).

It leaves 60 s after the last other person left, 900 s after joining when nobody arrives, and, new here, when the
People panel and the head count are both unreadable for a sustained time with no caption in that time.
"""

import asyncio
import logging

from test_ui import session  # noqa: F401

from bot.captions import Utterance
from bot.clock import FakeClock


class Panel:
    """A browser whose People panel and head count are scripted by the test."""

    def __init__(self):
        self.others: list[str] | None = ["Sam"]  # None: the panel is unreadable
        self.count: int | None = 2  # None: the head count is unreadable too
        self.ended = False

    async def participants(self):
        return None if self.others is None else {"others": self.others, "waiting": [], "self": "Tilo"}

    async def people_count(self):
        return self.count

    async def meeting_ended(self):
        return self.ended

    async def show_chat(self):
        return None

    async def set_mic(self, on):
        return True


def rig(session, gate_at=0.0):  # noqa: F811
    session.clock = FakeClock(1000.0)
    session.start = 1000.0
    session.gate_at = gate_at
    session.br = Panel()
    return session, session.br


def step(s, advance=0.0):
    s.clock.advance(advance)
    return asyncio.run(s._status_step())


def test_FR_MTG_09_the_bot_leaves_60_seconds_after_everyone_else_left(session):  # noqa: F811
    s, panel = rig(session)
    assert step(s) is False  # Sam is here: seen
    panel.others = []
    assert step(s, 15) is False  # alone, grace running
    assert step(s, 40) is False  # 40 s alone
    assert step(s, 20) is True  # 60 s alone


def test_FR_MTG_09_someone_coming_back_restarts_the_alone_grace(session):  # noqa: F811
    s, panel = rig(session)
    step(s)
    panel.others = []
    step(s, 15)
    step(s, 40)
    panel.others = ["Priya"]
    assert step(s, 10) is False
    panel.others = []
    assert step(s, 15) is False
    assert step(s, 40) is False  # the earlier 55 s do not count
    assert step(s, 20) is True


def test_FR_MTG_09_an_empty_meeting_nobody_joins_is_left_after_900_seconds(session):  # noqa: F811
    s, panel = rig(session, gate_at=None)
    s.required = ["Sam"]
    panel.others = []
    assert step(s, 5) is False
    assert step(s, 890) is False  # 895 s
    assert step(s, 10) is True  # 905 s


def test_FR_MTG_09_an_unreadable_panel_and_head_count_leave_after_five_quiet_minutes(session, caplog):  # noqa: F811
    s, panel = rig(session)
    step(s)
    panel.others, panel.count = None, None
    assert step(s, 15) is False  # first unreadable read: the timer starts
    assert step(s, 285) is False  # 285 s unreadable
    with caplog.at_level(logging.INFO, logger="bot.session"):
        assert step(s, 20) is True  # 305 s
    assert "unreadable" in caplog.text


def test_FR_MTG_09_a_caption_while_unreadable_keeps_the_bot_in_the_meeting(session):  # noqa: F811
    s, panel = rig(session)
    panel.others, panel.count = None, None
    step(s)
    step(s, 280)
    s.store.items.append(Utterance("Sam", "still talking", 280.0))  # someone is speaking: not an empty room
    assert step(s, 20) is False
    assert step(s, 280) is False
    assert step(s, 30) is True  # silent and unreadable for 310 s since the caption


def test_FR_MTG_09_reading_the_panel_again_clears_the_unreadable_timer(session):  # noqa: F811
    s, panel = rig(session)
    panel.others, panel.count = None, None
    step(s)
    step(s, 250)
    panel.others = ["Sam"]
    assert step(s, 15) is False
    panel.others = None
    assert step(s, 100) is False  # a fresh unreadable stretch starts here, not at 250 s
    assert step(s, 250) is False
    assert step(s, 60) is True
