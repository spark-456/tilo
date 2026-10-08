"""Shared helpers for the FR-MTG-17 (recording upload) acceptance tests: a synthetic 2-minute recording (a tiny
deterministic bytes blob; the committed replay recording stands in for the audio), its transcript fixture, a word
error rate helper and the schema check against contracts/transcript.schema.json."""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from _planning_contracts_lib import build_registry, load_schema, validator_for

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "mtg17"
MEETING_ID = "mt_fixture17"
MEDIA_TYPE = "audio/mpeg"


def recording_bytes() -> bytes:
    """A stand-in for a 2-minute recording: deterministic, a few KB, never real audio."""
    return b"ID3-fixture-recording-120s\n" + bytes(range(256)) * 16


def reference_transcript() -> dict[str, Any]:
    return json.loads((FIXTURES / "transcript.reference.json").read_text(encoding="utf-8"))


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word-level Levenshtein distance over the reference length."""
    ref, hyp = words(reference), words(hypothesis)
    row = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        previous, row[0] = row[0], i
        for j, hyp_word in enumerate(hyp, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ref_word != hyp_word))
    return row[len(hyp)] / max(len(ref), 1)


def joined_text(transcript: dict[str, Any]) -> str:
    return " ".join(u["text"] for u in transcript["utterances"])


def assert_valid_transcript(transcript: dict[str, Any]) -> None:
    schema = load_schema(REPO_ROOT, "transcript")
    errors = list(validator_for(schema, build_registry(REPO_ROOT)).iter_errors(transcript))
    assert not errors, [e.message for e in errors]
