"""Native tool results are screened, archived, cached and tainted; quiz output fails closed."""

import asyncio
import copy
import json
from pathlib import Path

import pytest
from tilo_evals.web_replay import ScriptedModel
from tilo_harness.deliverable import DeliverableRefused
from tilo_harness.executor import UnitContext
from tilo_harness.quiz import quiz_output, verify_answers
from tilo_harness.skills import LoadedSkill
from tilo_harness.tool_runner import ToolUnitRunner
from tilo_harness.tools import MemoryToolArchive, ToolRegistry, ToolResult
from tilo_providers.media import MediaPart
from tilo_providers.safety import FakeSafetyProvider
from tilo_sandbox_web.fetch_fixtures import PAPERS, WRONG_MAGIC_PNG

SPEC = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/appspec/valid/true_false_one_question.json").read_text()
)
PDF = MediaPart(mime_type="application/pdf", data=PAPERS["paper-1.pdf"])
PNG = MediaPart(mime_type="image/png", data=WRONG_MAGIC_PNG)


class FileTool:
    name, description = "fetch_url", "Read a file"
    tier, external_content, side_effect = "T1", True, False
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    calls = 0

    def run(self, args):
        self.calls += 1
        return ToolResult("Stored source", parts=(PDF, PNG))


class Screen(FakeSafetyProvider):
    def __init__(self, mode):
        self.mode = mode

    def _check(self, text, *, content, mime_type):
        if content is not None:
            if self.mode == "error":
                raise RuntimeError("private error")
            return {"flagged": self.mode == "flagged", "reason": None}
        return {"flagged": False, "reason": None}


@pytest.mark.parametrize("mode", ["clean", "flagged", "error", "no_archive"])
def test_native_files_screened_before_model_and_not_written_as_raw_tool_data(mode):
    tool, archive = FileTool(), MemoryToolArchive()
    model = ScriptedModel([[("fetch_url", {})], [("fetch_url", {})], "Done"])
    runner = ToolUnitRunner(
        {"specialist": model},
        tools=ToolRegistry([tool]),
        safety=Screen(mode),
        archive=None if mode == "no_archive" else archive,
    )
    skill = LoadedSkill("file", "1.0.0", "Read", "0" * 64, tools_allowed=("fetch_url",))
    result = asyncio.run(
        runner.run_unit(
            {"id": "U1", "title": "Read", "role": "specialist", "unit_type": "research"}, UnitContext("A_s1", (skill,))
        )
    )
    assert result.outcome.read_external
    assert tool.calls == 1
    assert result.calls[-1].outcome == "cached"
    assert model.requests[-1].parts == ([PDF, PNG] if mode == "clean" else None)
    assert all("data" not in part for record in archive.records.values() for part in record.get("parts", []))
    if mode != "no_archive":
        assert result.calls[0].outcome == ("ok" if mode == "clean" else "dropped")


@pytest.mark.parametrize("flaw", ["duplicate", "answer", "gap", "script", "unknown", "page", "unrecorded"])
def test_quiz_refuses_invalid_or_unrecorded_sources(flaw):
    spec = copy.deepcopy(SPEC)
    spec["questions"][0]["source"]["page"] = 1
    if flaw == "duplicate":
        spec["questions"].append(copy.deepcopy(spec["questions"][0]))
    elif flaw == "answer":
        spec["questions"][0]["answer"] = "f"
    elif flaw == "gap":
        spec["questions"][0]["options"]["d"] = "later"
    elif flaw == "script":
        spec["script"] = "execute me"
    elif flaw == "unknown":
        spec["questions"][0]["source"]["url"] = "https://invalid.test"
    elif flaw == "page":
        spec["questions"][0]["source"]["page"] = 2
    with pytest.raises(DeliverableRefused):
        quiz_output(json.dumps(spec), lambda _r: None if flaw == "unrecorded" else PDF)


@pytest.mark.parametrize(
    "reply",
    [
        '{"confirmed":true}',
        '{"confirmed":false}',
        '{"confirmed":1}',
        '{"confirmed":true,"confirmed":true}',
        "uncertain",
    ],
)
def test_independent_verifier_checks_native_page_and_fails_closed(reply):
    spec = copy.deepcopy(SPEC)
    spec["questions"][0]["source"]["page"] = 1
    output = quiz_output(json.dumps(spec), lambda _r: PDF)
    assert output.media_type == "application/json"
    model = ScriptedModel([reply])
    assert verify_answers(spec, model, lambda _r: PDF) is (reply == '{"confirmed":true}')
    assert model.requests[0].parts == [PDF]


def test_quiz_caps_unique_sources_before_any_load_and_reuses_one_native_file():
    spec = copy.deepcopy(SPEC)
    first = spec["questions"][0]
    questions = []
    for index in range(11):
        question = copy.deepcopy(first)
        question["id"] = f"q{index + 1}"
        question["source"] = {"artifact": {"artifact_id": f"art_source_{index}", "version": 1}, "page": 1}
        questions.append(question)
    spec["questions"] = questions
    loads = []

    def load(ref):
        loads.append(ref)
        return PDF

    with pytest.raises(DeliverableRefused):
        quiz_output(json.dumps(spec), load)
    assert not loads
    for question in questions:
        question["source"]["artifact"] = questions[0]["source"]["artifact"]
    assert quiz_output(json.dumps(spec), load).media_type == "application/json"
    assert len(loads) == 1
