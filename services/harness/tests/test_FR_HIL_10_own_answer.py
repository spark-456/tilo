import asyncio

from hil_wait_support import answered_part, events_of
from test_FR_HIL_10_run_plan_resumes_asked_unit import _setup, _until_asked


def test_FR_HIL_10_unit_continues_with_typed_text(tmp_path):
    start, store, clock = _setup(tmp_path)

    async def go():
        run, wait, must_ask, runner = start()
        await _until_asked(store, runner, clock)
        part = answered_part(must_ask.cards["U1"], option="per_pack")
        part["option"] = None
        part["data"]["text"] = "Compare net price per kilogram"
        wait.write(part)
        await asyncio.wait_for(run, timeout=20)
        assert runner.answers["U1"].text == "Compare net price per kilogram"
        assert runner.answers["U1"].option is None
        assert runner.answers["U2"] is None

    asyncio.run(go())
    (event,) = events_of(store, "question.answered")
    assert event["data"]["text"] == "Compare net price per kilogram"
    assert event["summary"] == "The question was answered (person)."
