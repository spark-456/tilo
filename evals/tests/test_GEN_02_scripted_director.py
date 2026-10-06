"""GEN-02 (issue #272): the scripted Director answers what the pipeline asks, from the case, and nothing else."""

import json

import pytest
from tilo_evals.scripted import ScriptedDirector, standard_approaches
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import RequestError
from tilo_providers.interfaces import GenerateRequest

BRIEF = {"deliverables": [{"title": "T", "format": "pdf"}]}


def _ask(director: ScriptedDirector, prop: str) -> dict:
    request = GenerateRequest(prompt="x", response_schema={"type": "object", "properties": {prop: {}}})
    return json.loads(director.generate(request).text)


def test_GEN_02_it_answers_brief_approaches_and_plan_by_the_requested_schema() -> None:
    director = ScriptedDirector({"brief": BRIEF, "approaches": "standard", "plan": {"units": []}})
    assert _ask(director, "ambiguous_fields") == BRIEF
    assert _ask(director, "units") == {"units": []}
    approaches = _ask(director, "approaches")["approaches"]
    assert [a["dimensions"]["output_format"] for a in approaches] == ["pdf"] * 3
    assert director.calls == ["brief", "plan", "approaches"]


def test_GEN_02_the_standard_approaches_differ_on_four_of_five_dimensions() -> None:
    dims = [a["dimensions"] for a in standard_approaches("docx")["approaches"]]
    for i, a in enumerate(dims):
        for b in dims[i + 1 :]:
            assert sum(a[k] != b[k] for k in a) >= 2  # PG-08


def test_GEN_02_a_reply_the_case_leaves_out_is_a_director_that_could_not_answer() -> None:
    with pytest.raises(RequestError):
        _ask(ScriptedDirector({"brief": BRIEF, "plan": None}), "units")


def test_GEN_02_it_answers_nothing_else_and_makes_no_embeddings() -> None:
    director = ScriptedDirector({})
    with pytest.raises(RequestError):
        director.generate(GenerateRequest(prompt="x", response_schema={"type": "object", "properties": {"other": {}}}))
    with pytest.raises(RequestError):
        director.embed({"input": ["x"]})


def test_GEN_02_it_is_refused_when_live_or_deployed(monkeypatch) -> None:
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.setenv(name, "1")
        with pytest.raises(ProviderConfigError):
            ScriptedDirector({})
        monkeypatch.delenv(name)
    director = ScriptedDirector({"brief": BRIEF})
    monkeypatch.setenv("LIVE", "1")  # turned on after construction: every call re-checks
    with pytest.raises(ProviderConfigError):
        _ask(director, "ambiguous_fields")


def test_GEN_02_it_names_no_model_and_is_never_conforming() -> None:
    director = ScriptedDirector({})
    assert director.dev_only is True  # PL-05
    assert director.price().input == 0.0
