import pytest
from tilo_api import makers
from tilo_planning.brief import BriefValidationError, validate_brief

OWNER = "u_maker_owner"
WEBSITE = dict(
    goal="Build a four page client portal",
    audience="Clients",
    deadline=None,
    constraints=[],
    sources=[],
    sensitivity="business",
    assumptions=[],
    applied_preferences=[],
    deliverables=[{"title": "Client portal", "format": "website"}],
)


class Views:
    def __init__(self, states=None):
        self.states = states or {}

    def view(self, owner, connector):
        assert owner == OWNER
        return self.states.get(connector), [], None


def test_WEBSITE_MK_01_options_MK_02_config_and_setup_MK_06_model_field_rules(monkeypatch):
    choices = makers.make_choices(WEBSITE, OWNER, views=Views())

    choice = choices[0]
    assert [o["make_with"] for o in choice["options"]] == ["native", "connector:lovable"]
    assert (
        choice["options"][1]["suggested"] is True
        and "4 pages" in choice["options"][1]["note"]
        and choice["selected"] == "connector:lovable"
    )
    small = {**WEBSITE, "goal": "Build a one page site"}
    website = makers.make_choices(small, OWNER, views=Views())[0]
    deck = {"goal": "Build slides", "deliverables": [{"title": "Deck", "format": "pptx"}]}
    pptx = makers.make_choices(deck, OWNER, views=Views())[0]

    assert website["selected"] == "native" and not any(o["suggested"] for o in website["options"])
    canva = next(o for o in pptx["options"] if o["make_with"] == "connector:canva")
    assert canva["status"] == "needs_setup" and canva["note"] == "Needs the workspace owner's Canva app."
    with pytest.raises(makers.MakerSelectionError, match="needs setup"):
        makers.resolve_picks([pptx], [{"deliverable": 0, "make_with": "connector:canva"}], deck)
    original = makers._read_yaml
    raw = original(makers._CONFIG_DIR / "makers.yaml")
    raw["formats"]["website"]["partners"][0]["make_with"] = "connector:missing_partner"
    monkeypatch.setattr(makers, "_read_yaml", lambda path: raw if path.name == "makers.yaml" else original(path))

    with pytest.raises(makers.MakerConfigError):
        makers.load_makers_config()
    invalid = {**WEBSITE, "deliverables": [{**WEBSITE["deliverables"][0], "make_with": "connector:lovable"}]}
    with pytest.raises(BriefValidationError):
        validate_brief(invalid)


def test_WEBSITE_MK_06_approve_saves_events_after_grant_and_compiles_the_persons_pick(run_flow):
    from _clint2_lib import wait_for

    intake = run_flow.start()
    run_flow.store.tasks[intake["task_id"]].brief = WEBSITE
    offered = run_flow.flow.approaches(intake["task_id"])
    assert offered.json()["make_choices"]
    response = run_flow.flow.client.post(
        f"/tasks/{intake['task_id']}/approve",
        json={"approach_id": "quick", "budget_cap": 50, "make_with": [{"deliverable": 0, "make_with": "native"}]},
    )

    assert response.status_code == 200, response.text
    wait_for(lambda: run_flow.compile_calls, what="the selected maker to reach plan compilation")
    stream = run_flow.stream()
    indexes = {event["type"]: i for i, event in enumerate(stream)}
    grant, chosen = indexes["budget.granted"], indexes["plan.maker_chosen"]
    event = stream[chosen]
    assert grant < chosen and event["actor"] == "u_flow_owner" and event["data"]["make_with"] == "native"
    assert event["cause"] == stream[grant]["id"]
    assert (
        run_flow.store.tasks[intake["task_id"]].maker_picks[0]["make_with"]
        == run_flow.compile_calls[0]["brief"]["deliverables"][0]["make_with"]
        == "native"
    )


def test_WEBSITE_MK_06_unoffered_pick_returns_422_without_a_grant(flow_factory):
    flow = flow_factory([])
    intake = flow.new_task()
    flow.store.tasks[intake["task_id"]].brief = WEBSITE
    flow.approaches(intake["task_id"])
    response = flow.client.post(
        f"/tasks/{intake['task_id']}/approve",
        json={
            "approach_id": "quick",
            "budget_cap": 50,
            "make_with": [{"deliverable": 0, "make_with": "connector:missing"}],
        },
    )

    assert response.status_code == 422 and "not offered" in response.text
    assert not any(e["type"] in {"budget.granted", "plan.maker_chosen"} for e in flow.store.events[intake["world_id"]])
