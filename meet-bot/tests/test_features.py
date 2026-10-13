from bot.brain import NO_ANSWER_LINE, Agenda, Brain, ChatPolicy, validate_output
from bot.captions import Utterance
from bot.mock_llm import ScriptedLLM
from bot.people import clean_name, gate_open, missing_required, name_match

AGENDA = Agenda.parse("# Sync\nRequired: John Regi, Priya\n1. Roadmap (10 min)\n2. Hiring (5 min)\n")


def reply(**kw):
    base = {
        "agenda_items": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "drift_note": None,
        "chat_message": None,
    }
    base.update(kw)
    return base


def test_agenda_required_line():
    assert AGENDA.required == ["John Regi", "Priya"]
    assert [i.title for i in AGENDA.items] == ["Roadmap", "Hiring"]


def test_name_helpers():
    assert clean_name("John Regi (You)") == "John Regi" and clean_name("Meeting host") == ""
    assert name_match("john", "John Regi") and not name_match("Priya", "John Regi")


def test_gate_waits_for_every_required_person():
    assert not gate_open(["John", "Priya"], ["John Regi"])
    assert missing_required(["John", "Priya"], ["John Regi"]) == ["Priya"]
    assert gate_open(["John", "Priya"], ["John Regi", "Priya Nair"])
    assert not gate_open([], []) and gate_open([], ["Anyone"])


def test_new_schema_fields_are_optional_and_validated():
    out = validate_output(reply())
    assert out["speaker_notes"] == [] and out["context_summary"] == "" and out["reply_to_assistant"] is None
    out = validate_output(
        reply(
            speaker_notes=[{"speaker": "John", "notes": "wants reminders"}],
            assistant_requests=[{"from": "John", "text": "remind at 7pm"}],
            context_summary="Kickoff so far.",
        )
    )
    assert out["speaker_notes"][0]["speaker"] == "John"
    import pytest

    from bot.brain import SchemaError

    with pytest.raises(SchemaError):
        validate_output(reply(speaker_notes=[{"speaker": 1}]))


def test_per_person_context_accumulates_and_reaches_the_summary(tmp_path):
    llm = ScriptedLLM(
        [
            reply(
                context_summary="Kickoff started.",
                speaker_notes=[{"speaker": "John", "notes": "Wants a 7pm reminder."}],
                assistant_requests=[{"from": "John", "text": "Set a reminder for 7pm"}],
            ),
            reply(
                context_summary="Kickoff, then roadmap.",
                speaker_notes=[{"speaker": "Priya", "notes": "Owns the roadmap."}],
                assistant_requests=[{"from": "John", "text": "set a reminder for 7pm"}],
            ),
        ]
    )
    b = Brain(AGENDA, llm, 30)
    b.step([Utterance("John", "hi", 1)], 30)
    b.step([Utterance("Priya", "hello", 2)], 60)
    assert set(b.state.speaker_notes) == {"John", "Priya"} and len(b.state.assistant_requests) == 1
    assert b.state.context_summary == "Kickoff, then roadmap."
    assert "current_state" in llm.calls[1][1] and "Wants a 7pm reminder." in llm.calls[1][1]  # memory fed back
    b.write_outputs(tmp_path, 60)
    md = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "## Per person" in md and "**Priya**" in md and "Set a reminder for 7pm" in md


def test_prompt_carries_present_people_and_bot_name():
    llm = ScriptedLLM([reply()])
    b = Brain(AGENDA, llm, 30, bot_name="tilo")
    b.present = ["John Regi"]
    b.step([], 10)
    assert '"participants_present": ["John Regi"]' in llm.calls[0][1] and '"bot_name": "tilo"' in llm.calls[0][1]


def test_direct_reply_only_when_addressed_with_a_question_and_only_once():
    p = ChatPolicy()
    said = [Utterance("John", "Tilo, what is left on the agenda?", 100)]
    m = p.decide_direct("Hiring is still open.", said, "tilo", 120)
    assert m and m.kind == "direct_reply"
    p.commit(m, 120)
    assert p.decide_direct("Hiring is still open.", said, "tilo", 400) is None  # same question, answered
    assert p.decide_direct("Blah.", [Utterance("John", "Let's move on.", 5)], "tilo", 500) is None
    assert p.decide_direct("Blah.", [Utterance("John", "Tilo is a nice name", 5)], "tilo", 500) is None  # no question


def test_direct_replies_do_not_use_up_the_four_message_budget():
    p = ChatPolicy()
    said = [Utterance("John", "Tilo, any action items?", 10)]
    p.commit(p.decide_direct("None yet.", said, "tilo", 10), 10)
    assert len(p.sent) == 0 and len(p.direct_sent) == 1


def test_misheard_assistant_name_still_counts_as_addressed():
    from bot.people import addressed

    assert addressed("Hi, Tilo, what's on the agenda?", "tilo")
    assert addressed("Tyler, what's on the accent today?", "tilo")  # real caption from the live test
    assert not addressed("Tell me about it?", "tilo") and not addressed("What time is it?", "tilo")
    assert not addressed("Tilo will send the notes.", "tilo")  # no question


def test_merger_does_not_repeat_sentences_meet_keeps_in_the_block():
    from bot.captions import CaptionBlock as B
    from bot.captions import CaptionMerger

    m = CaptionMerger(settle_s=2.0)
    out = m.feed([B("John", "Hi, Tilo, what's on the agenda today?")], 0.0)
    out += m.tick(3.0)
    # Meet later shows the earlier sentence plus new ones in the same block (with a small revision up front)
    out += m.feed([B("John", "Hi, Tilo, what's on the agenda today? We should update the pricing page.")], 4.0)
    out += m.feed(
        [B("John", "Hi, Tilo, what's on the agenda today? We should update the pricing page. Remind us at 7.")], 5.0
    )
    out += m.flush(9.0)
    assert [u.text for u in out] == [
        "Hi, Tilo, what's on the agenda today?",
        "We should update the pricing page. Remind us at 7.",
    ]


def test_real_meet_snapshots_parse():
    from pathlib import Path

    from bot.captions import parse_caption_html

    fx = Path(__file__).parent / "fixtures"
    got = [
        parse_caption_html((fx / f"real_{n}.html").read_text(encoding="utf-8"))
        for n in ("0001", "0004", "0010", "0017")
    ]
    assert [g[0].speaker for g in got] == ["Alex Rivera"] * 4
    assert got[0][0].text == "Hi, Tilo." and got[1][0].text.endswith("what is on the agenda today?")
    assert "pricing page" in got[2][0].text and "Jump" not in got[2][0].text and "arrow_downward" not in got[2][0].text


def test_growing_block_across_settle_is_not_duplicated_real_pattern():
    from bot.captions import CaptionBlock as B
    from bot.captions import CaptionMerger

    m = CaptionMerger()
    out = []
    for t, text in [
        (0, "Tyler works on the agenda today."),
        (16, "Tyler works on the agenda today. Uh."),
        (30, "Tyler works on the agenda today. Uh. Toyota."),
    ]:
        out += m.feed([B("J", text)], t)
        out += m.tick(t + 5)
    assert [u.text for u in out] == ["Tyler works on the agenda today.", "Uh.", "Toyota."]


def test_participant_row_junk_is_stripped_from_names():
    assert clean_name("John RegidevicesMute John Regi's microphonemore_vertMore actions") == "John Regi"


def test_quick_reply_is_one_small_call_answered_once_and_never_retried_when_unsure():
    llm = ScriptedLLM(['{"reply": "Kickoff and goals is in progress."}'])
    b = Brain(AGENDA, llm, 30, bot_name="tilo")
    said = [Utterance("John", "Hi, tilo, what is on the agenda today?", 5)]
    assert b.has_pending_question(said)
    msg = b.quick_reply(said, 30)
    assert msg and msg.kind == "direct_reply" and msg.text == "Kickoff and goals is in progress."
    assert len(llm.calls) == 1 and len(llm.calls[0][1]) < 1500  # tiny prompt, not the full analysis
    b.commit_chat(msg, 30)
    assert not b.has_pending_question(said)  # answered
    b2 = Brain(AGENDA, ScriptedLLM(['{"reply": null}']), 30, bot_name="tilo")
    unsure = b2.quick_reply(said, 30)  # addressed but unanswerable: the fallback line (VA-02), not silence
    assert unsure and unsure.text == NO_ANSWER_LINE and not b2.has_pending_question(said)  # tried once, no retry storm
    assert len(b2.llm.calls) == 1


def test_question_mode_answers_questions_without_the_name_and_addressed_mode_does_not():
    from bot.people import question_of

    text = "We should update the pricing page. What action items do we have so far?"
    assert question_of(text, "tilo", "questions") == "What action items do we have so far?"
    assert question_of(text, "tilo", "addressed") is None
    assert question_of("Tyler, what is on the agenda?", "tilo", "addressed")  # misheard name, vocative
    assert question_of("Sure? ok", "tilo", "questions") is None  # too short to be a real question


def test_brain_follow_up_question_without_name_reaches_the_model():
    llm = ScriptedLLM(['{"reply": "The pricing page needs an owner."}'])
    b = Brain(AGENDA, llm, 30, bot_name="tilo")
    said = [Utterance("John", "Who should own the pricing page work?", 90)]  # no name, not a state question: the model
    msg = b.quick_reply(said, 100)
    assert msg and "pricing page" in msg.text
    strict = Brain(AGENDA, ScriptedLLM(['{"reply": "x"}']), 30, bot_name="tilo", answer_mode="addressed")
    assert not strict.has_pending_question(said)


def test_timeline_writes_jsonl(tmp_path):
    from bot.timing import Timeline

    t = Timeline(tmp_path / "latency.jsonl")
    t.record("question_answered", model_s=1.2)
    assert '"model_s": 1.2' in (tmp_path / "latency.jsonl").read_text(encoding="utf-8")


def test_playback_page_links_transcript_lines_to_audio_times(tmp_path):
    import json

    from bot.playback import write_playback

    (tmp_path / "transcript.jsonl").write_text(
        json.dumps({"speaker": "Alex <b>", "text": "Hi there", "t": 65.0}) + chr(10), encoding="utf-8"
    )
    (tmp_path / "audio.wav").write_bytes(b"RIFF")
    page = write_playback(tmp_path).read_text(encoding="utf-8")
    assert 'data-t="61.0"' in page and "01:05" in page and "audio.wav" in page
    assert "Alex &lt;b&gt;" in page  # transcript text is escaped, never injected as HTML
    assert write_playback(tmp_path / "missing") is None


def test_recording_intro_discloses_the_recording():
    from bot.chat import INTRO, INTRO_RECORDING

    assert (
        INTRO_RECORDING.startswith("Hi, I'm an AI assistant taking notes for this meeting")
        and "recorded" in INTRO_RECORDING
    )
    assert "recorded" not in INTRO
