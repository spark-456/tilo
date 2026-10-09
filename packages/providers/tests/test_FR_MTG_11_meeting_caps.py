"""FR-MTG-11 (security follow-up): a per-meeting cap on the bot's provider calls, from `config/meeting.yaml`. Outside
participants can make the bot ask questions, so the number of paid calls one meeting can cost is bounded in config."""

from __future__ import annotations

import pathlib
import threading

import pytest
import yaml
from tilo_providers.config import ProviderConfigError
from tilo_providers.meeting import CallCounter, MeetingCaps, load_meeting_caps

REPO = pathlib.Path(__file__).resolve().parents[3]


def write(tmp_path: pathlib.Path, **meeting) -> pathlib.Path:
    path = tmp_path / "meeting.yaml"
    path.write_text(yaml.safe_dump({"meeting": meeting}), encoding="utf-8")
    return path


def test_FR_MTG_11_the_shipped_meeting_caps_are_conservative_positive_whole_numbers():
    caps = load_meeting_caps(REPO / "config" / "meeting.yaml")
    assert caps == MeetingCaps(max_model_calls=200, max_speech_calls=400)


@pytest.mark.parametrize("bad", [0, -1, 1.5, "200", True, None])
def test_FR_MTG_11_a_bad_cap_fails_start_up_loudly(tmp_path, bad):
    with pytest.raises(ProviderConfigError):
        load_meeting_caps(write(tmp_path, max_model_calls=bad, max_speech_calls=10))
    with pytest.raises(ProviderConfigError):
        load_meeting_caps(write(tmp_path, max_model_calls=10, max_speech_calls=bad))


def test_FR_MTG_11_a_missing_file_or_section_fails_start_up(tmp_path):
    with pytest.raises(ProviderConfigError):
        load_meeting_caps(tmp_path / "absent.yaml")
    (tmp_path / "x.yaml").write_text("other: 1\n", encoding="utf-8")
    with pytest.raises(ProviderConfigError):
        load_meeting_caps(tmp_path / "x.yaml")


def test_FR_MTG_11_the_counter_allows_exactly_the_cap_then_refuses_each_kind_separately():
    counter = CallCounter(MeetingCaps(max_model_calls=2, max_speech_calls=1))
    assert [counter.take("model") for _ in range(3)] == [True, True, False]
    assert [counter.take("speech") for _ in range(2)] == [True, False]
    assert counter.used == {"model": 2, "speech": 1}  # a refused call is not counted as made


def test_FR_MTG_11_the_counter_announces_the_cap_once_per_kind():
    counter = CallCounter(MeetingCaps(max_model_calls=1, max_speech_calls=1))
    counter.take("model")
    assert [counter.take("model") for _ in range(3)] == [False, False, False]
    assert counter.newly_capped("model") is True and counter.newly_capped("model") is False
    assert counter.newly_capped("speech") is False  # not reached


def test_FR_MTG_11_the_counter_is_exact_under_threads():
    counter = CallCounter(MeetingCaps(max_model_calls=50, max_speech_calls=1))
    allowed: list[bool] = []

    def worker():
        for _ in range(20):
            allowed.append(counter.take("model"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert allowed.count(True) == 50 and allowed.count(False) == 110


def test_FR_MTG_11_an_unknown_kind_is_a_programming_error():
    with pytest.raises(ValueError):
        CallCounter(MeetingCaps(1, 1)).take("video")
