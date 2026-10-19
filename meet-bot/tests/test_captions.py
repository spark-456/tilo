from pathlib import Path

from bot.captions import CaptionMerger, TranscriptStore, Utterance, parse_caption_html

FX = Path(__file__).parent / "fixtures"


def blocks(name):
    return parse_caption_html((FX / name).read_text(encoding="utf-8"))


def test_parser_single_speaker_ignores_ui_noise():
    b = blocks("caption_growth_3.html")
    assert [(x.speaker, x.text) for x in b] == [("Alex Rivera", "Okay, so let us start with the roadmap for Q3.")]


def test_parser_two_speakers_in_order():
    b = blocks("caption_two_speakers.html")
    assert [x.speaker for x in b] == ["Alex Rivera", "Priya Nair"]
    assert b[1].text == "Sounds good to me."


def test_parser_ui_only_and_empty_give_nothing():
    assert blocks("caption_ui_only.html") == []
    assert parse_caption_html("") == []


def test_parser_accepts_snapshot_without_region_wrapper():
    html = '<div><div><img src="x"><div>Sam</div></div><div>Hi all</div></div>'
    assert [(x.speaker, x.text) for x in parse_caption_html(html)] == [("Sam", "Hi all")]


def test_merger_growing_caption_becomes_one_utterance():
    m = CaptionMerger(settle_s=2.5)
    done = []
    for n, t in enumerate(["caption_growth_1.html", "caption_growth_2.html", "caption_growth_3.html"]):
        done += m.feed(blocks(t), now=float(n))
    assert done == []  # still partial
    done += m.tick(now=2 + 2.6)
    assert [(u.speaker, u.text) for u in done] == [("Alex Rivera", "Okay, so let us start with the roadmap for Q3.")]


def test_merger_new_speaker_finalizes_via_disappearance_and_no_duplicates():
    m = CaptionMerger()
    out = []
    out += m.feed(blocks("caption_growth_3.html"), 0.0)
    out += m.feed(blocks("caption_two_speakers.html"), 1.0)
    out += m.tick(10.0)  # both settle; Alex's block is unchanged so must not re-emit
    out += m.feed(blocks("caption_two_speakers.html"), 11.0)
    out += m.tick(20.0)
    assert [u.speaker for u in out] == ["Alex Rivera", "Priya Nair"]


def test_merger_growth_after_settle_emits_only_suffix():
    m = CaptionMerger(settle_s=2.0)
    from bot.captions import CaptionBlock as B

    out = m.feed([B("Sam", "We ship on Friday.")], 0.0)
    out += m.tick(3.0)
    out += m.feed([B("Sam", "We ship on Friday. Then we retro.")], 4.0)
    out += m.flush(10.0)
    assert [u.text for u in out] == ["We ship on Friday.", "Then we retro."]


def test_merger_ignores_self_and_bot_name():
    m = CaptionMerger(ignore_speakers=("you", "Tilo Bot"))
    m.add_ignored("Extra Name")
    out = m.feed(blocks("caption_with_self.html"), 0.0) + m.flush(5.0)
    assert [u.speaker for u in out] == ["Priya Nair"]


def test_merger_handles_word_corrections():
    from bot.captions import CaptionBlock as B

    m = CaptionMerger()
    m.feed([B("Sam", "we should ship the beta on friday")], 0.0)
    m.feed([B("Sam", "We should ship the beta on Friday.")], 1.0)  # capitalized/punctuated revision
    out = m.flush(5.0)
    assert [u.text for u in out] == ["We should ship the beta on Friday."]


def test_transcript_store_writes_jsonl_and_windows(tmp_path):
    s = TranscriptStore(tmp_path / "transcript.jsonl")
    for t in (0, 100, 400):
        s.append(Utterance("A", f"x{t}", float(t)))
    assert len((tmp_path / "transcript.jsonl").read_text().splitlines()) == 3
    assert [u.text for u in s.window(400, 5)] == ["x100", "x400"]
