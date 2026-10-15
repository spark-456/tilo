"""WORKSPACE_TOOLS ticket B / ADR-0048 WT-01 to WT-05 (tilo-api half): the agents' read tools.

Unit level: `WorkspaceUnit` and its five tools over a fake connectors client (the contract's own answer fixtures) and a
fake run. Run level: the production `ApiUnitRunner` and `BoundRunRunner` on RUN-FAIL-1's rig, with a scripted model
that asks for `search_email`. No network, no paid call, no live switch; every id is a contract fixture's.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
import test_RUN_FAIL_1_tool_unit_after_answer as rig
from _tsw1_lib import ASHA, LAUNCH, NOW, OTHER_WORLD, T_GRANT, WORLD, person, share
from fastapi import HTTPException
from tilo_api import deps, workspace_tools
from tilo_api.meeting_host_rpc import HostRpcError
from tilo_api.run_tools import ApiUnitRunner, BoundRunRunner
from tilo_api.workspace_tools import (
    CONNECTOR_OF,
    LABELS,
    NOT_READABLE,
    SHARED,
    SUMMARIES,
    UNAVAILABLE,
    WINDOW,
    WorkspaceAccess,
    WorkspaceUnit,
    note,
    team_share_in_force,
)
from tilo_contracts import MeetingHostRpcReadAnswer
from tilo_harness.tools import ToolCallRecord, args_hash
from tilo_people.stores import PeopleStores

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
OWNER = rig.OWNER
ARGS = {
    "search_email": {"query": "from:ana"}, "read_email": {"message_id": "m1"}, "list_files": {"query": "plan"},
    "read_events": {"start": "2026-10-17T00:00:00+05:30", "end": "2026-10-24T00:00:00+05:30"},
    "read_file": {"file_id": "f1"},
}  # fmt: skip


def answer(name: str) -> MeetingHostRpcReadAnswer:
    path = CONTRACTS / "fixtures" / "meeting_host_rpc.read_answer" / "valid" / f"{name}.json"
    return MeetingHostRpcReadAnswer.model_validate_json(path.read_text(encoding="utf-8"))


def refused(tool: str, outcome: str, parts: list[Any] | None = None) -> MeetingHostRpcReadAnswer:
    body = {"tool": tool, "outcome": outcome, "connected_at": None, "result": None, "parts": parts or []}
    return MeetingHostRpcReadAnswer.model_validate(body)


class FakeRpc:
    def __init__(self, *answers: Any) -> None:
        self.answers, self.calls = list(answers), []

    def read(self, user_id: str, tool: str, args: Any) -> Any:
        self.calls.append((user_id, tool, dict(args)))
        got = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(got, Exception):
            raise got
        return got


class FakeRun:
    """What `WorkspaceUnit` uses of a run: the store's world record, `put` and the connection-part sink."""

    def __init__(self, world_owner: str | None = OWNER) -> None:
        worlds = {} if world_owner is None else {"w_1": deps.WorldRecord(world_owner, {}, run_id="r_1")}
        self.store, self.world_id, self.owner = deps.Store(worlds=worlds), "w_1", "u_the_task_owner"
        self.put_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.parts: list[dict[str, Any]] = []

    def put(self, *args: Any, **kw: Any) -> dict[str, Any]:
        self.put_calls.append((args, kw))
        return {}

    def _part_sink(self, part: dict[str, Any]) -> None:
        self.parts.append(part)


def make(rpc: Any, *, shared: Any = lambda world, owner: False, world_owner: str | None = OWNER):
    run = FakeRun(world_owner)
    access = WorkspaceAccess(lambda: rpc, shared)
    unit = WorkspaceUnit(run, access, {"id": "U1", "district": "D1"}, "A_s0", "B1", {"01JARCHIVE": "r_1/7"})
    return run, unit, {t.name: t for t in unit.tools()}


def record(tool: str, args: dict[str, Any], ref: str | None = "01JARCHIVE") -> ToolCallRecord:
    return ToolCallRecord("U1", 1, tool, args_hash(tool, args), "ok", 0.0, 3, ref, True)


# ---- the five tools --------------------------------------------------------------------------------------------


def test_WORKSPACE_TOOLS_B_the_five_tools_are_named_after_their_actions_with_the_contracts_args_as_schema() -> None:
    _, _, tools = make(FakeRpc(answer("ok_search_email")))
    schema = json.loads((CONTRACTS / "meeting_host_rpc.schema.json").read_text(encoding="utf-8"))["$defs"]
    assert set(tools) == set(CONNECTOR_OF) == {"search_email", "read_email", "read_events", "list_files", "read_file"}
    for name, tool in tools.items():
        assert dict(tool.input_schema) == schema[f"{name}_args"] and "$ref" not in json.dumps(tool.input_schema)
        assert (tool.tier, tool.external_content, tool.side_effect, tool.reads_private) == ("T1", True, False, True)


def test_WORKSPACE_TOOLS_B_WT01_the_user_read_is_the_world_records_owner_never_the_run_or_an_argument() -> None:
    rpc = FakeRpc(answer("ok_search_email"))
    run, _, tools = make(rpc)
    tools["search_email"].run(ARGS["search_email"])
    assert rpc.calls == [(OWNER, "search_email", ARGS["search_email"])]
    assert run.owner != OWNER  # the run's own field is not the source
    assert "user_id" not in json.dumps([dict(t.input_schema) for t in tools.values()])  # and no tool takes one


def test_WORKSPACE_TOOLS_B_WT01_a_world_with_a_team_share_reads_nothing_and_the_check_is_made_at_every_call() -> None:
    rpc, shared = FakeRpc(answer("ok_search_email")), {"now": False}
    run, unit, tools = make(rpc, shared=lambda world, owner: shared["now"])
    assert tools["search_email"].run(ARGS["search_email"]).content != SHARED
    shared["now"] = True  # the owner shares the world mid-run
    assert tools["search_email"].run(ARGS["search_email"]).content == SHARED
    assert len(rpc.calls) == 1
    unit.on_call(record("search_email", ARGS["search_email"]))
    assert len(run.put_calls) == 1  # only the read that happened is recorded


def test_WORKSPACE_TOOLS_B_WT01_a_world_the_store_does_not_know_reads_nothing() -> None:
    rpc = FakeRpc(answer("ok_search_email"))
    _, _, tools = make(rpc, world_owner=None)
    assert tools["search_email"].run(ARGS["search_email"]).content == SHARED and rpc.calls == []


@pytest.mark.parametrize(
    "window",
    [
        {"start": "2026-10-17T00:00:00Z", "end": "2026-10-17T00:00:00Z"},
        {"start": "2026-10-18T00:00:00Z", "end": "2026-10-17T00:00:00Z"},
        {"start": "2026-10-01T00:00:00Z", "end": "2026-11-02T00:00:00Z"},
        {"start": "2026-10-17T00:00:00", "end": "2026-10-18T00:00:00"},
    ],
)
def test_WORKSPACE_TOOLS_B_WT02_a_window_that_is_not_one_is_refused_before_the_call(window: dict[str, str]) -> None:
    rpc = FakeRpc(answer("ok_read_events"))
    _, _, tools = make(rpc)
    assert tools["read_events"].run(window).content == WINDOW and rpc.calls == []


def test_WORKSPACE_TOOLS_B_an_unconfigured_connectors_client_or_a_failed_call_is_a_fixed_note() -> None:
    _, _, tools = make(None)
    assert tools["search_email"].run(ARGS["search_email"]).content == UNAVAILABLE  # `rpc()` gives None: not configured
    for broken in (HostRpcError("unknown"), HostRpcError("refused"), RuntimeError("boom with a secret")):
        _, _, tools = make(FakeRpc(broken))
        got = tools["search_email"].run(ARGS["search_email"])
        assert got.content == UNAVAILABLE and "secret" not in got.content


# ---- WT-03: results ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    ["not_connected", "missing_scope", "expired", "not_found", "too_large", "unsupported_type", "unavailable"],
)
def test_WORKSPACE_TOOLS_B_WT03_every_other_outcome_is_a_fixed_plain_note_and_records_nothing(outcome: str) -> None:
    tool = "read_file"
    run, unit, tools = make(FakeRpc(refused(tool, outcome)))
    got = tools[tool].run(ARGS[tool])
    assert got.content == note("google_drive", outcome) and got.parts == ()
    unit.on_call(record(tool, ARGS[tool]))
    assert run.put_calls == []  # a refused or failed read writes no event (the archive keeps the call)


def test_WORKSPACE_TOOLS_B_WT03_notes_say_what_to_connect_and_only_that() -> None:
    assert "Read mail" in note("gmail", "not_connected") and "Read calendar" in note("google_calendar", "missing_scope")
    assert "Read Drive" in note("google_drive", "missing_scope")
    assert all("@" not in note(c, o) and "http" not in note(c, o) for c in SUMMARIES for o in ("expired", "not_found"))


@pytest.mark.parametrize(
    "name", ["ok_search_email", "ok_read_email", "ok_read_events", "ok_list_files", "ok_read_file_doc"]
)
def test_WORKSPACE_TOOLS_B_WT03_an_ok_result_is_the_contracts_result_as_json(name: str) -> None:
    fixture = answer(name)
    tool = fixture.tool
    _, _, tools = make(FakeRpc(fixture))
    got = tools[tool].run(ARGS[tool])
    assert json.loads(got.content) == fixture.result.model_dump(mode="json") and got.parts == ()


def test_WORKSPACE_TOOLS_B_WT03_a_pdf_goes_as_a_native_part_not_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = answer("ok_read_file_pdf")
    made: list[dict[str, Any]] = []
    monkeypatch.setattr(workspace_tools, "MediaPart", lambda **kw: made.append(kw) or ("part", kw["mime_type"]))
    _, _, tools = make(FakeRpc(fixture))
    got = tools["read_file"].run(ARGS["read_file"])
    assert got.parts == (("part", "application/pdf"),) and made[0]["data"].startswith(b"%PDF")
    body = json.loads(got.content)
    assert "pdf_b64" not in body and body["name"] == "Lease.pdf"


def test_WORKSPACE_TOOLS_B_WT03_a_pdf_the_media_layer_refuses_is_a_fixed_note() -> None:
    _, unit, tools = make(FakeRpc(answer("ok_read_file_pdf")))  # the fixture's bytes are a header only: no pages
    assert tools["read_file"].run(ARGS["read_file"]).content == NOT_READABLE
    assert unit._pending == {} or not any(unit._pending.values())


def test_WORKSPACE_TOOLS_B_WT03_connection_parts_of_the_call_reach_the_runs_sink_once_and_only_for_the_owner() -> None:
    mine = {"type": "connection.expired", "connector": "google_calendar", "user_id": OWNER}
    other = {"type": "connection.expired", "connector": "google_calendar", "user_id": "u_other"}
    fixture = refused("read_events", "expired", [mine, other])
    run, _, tools = make(FakeRpc(fixture))
    tools["read_events"].run(ARGS["read_events"])
    assert run.parts == [{"type": "connection.expired", "authz": None, "data": {"connector": "google_calendar"},
                          "user_id": OWNER}]  # fmt: skip


# ---- WT-05: one data.transfer per ok read -------------------------------------------------------------------------


def test_WORKSPACE_TOOLS_B_WT05_an_ok_read_writes_one_data_transfer_in_with_fixed_text_only() -> None:
    fixture = answer("ok_search_email")
    run, unit, tools = make(FakeRpc(fixture))
    tools["search_email"].run(ARGS["search_email"])
    assert run.put_calls == []  # written once the tool loop has archived the call, not before
    unit.on_call(record("search_email", ARGS["search_email"]))
    unit.on_call(record("search_email", ARGS["search_email"]))  # a second record for the same call writes nothing more
    ((args, kw),) = run.put_calls
    assert args == ("data.transfer", "A_s0", "B1", "An agent read from Gmail.", {
        "connector": "gmail", "action_type": "search_email", "direction": "in", "artifact": None, "outbox_id": None,
        "risk_tier": "T1",
    })  # fmt: skip
    assert kw["authz"] == {"by": "person", "ref": OWNER, "at": fixture.connected_at}
    assert kw["item"] == {"kind": "scroll", "artifact_id": None, "label": "Mail search"} and kw["district"] == "D1"
    assert kw["trace"]["tool"] == "search_email" and kw["trace"]["archive_ref"] == "r_1/7"
    assert isinstance(kw["trace"]["latency_ms"], int) and kw["trace"]["model_role"] is None
    blob = json.dumps([args, kw], default=str)
    for secret in (ARGS["search_email"]["query"], "Invoice 1042", "ana@example.org", "18c2f0a9b7d4e611"):
        assert secret not in blob  # no query, subject, sender or id in the event


@pytest.mark.parametrize(
    "name", ["ok_search_email", "ok_read_email", "ok_read_events", "ok_list_files", "ok_read_file_doc"]
)
def test_WORKSPACE_TOOLS_B_WT05_each_tool_has_its_fixed_label_and_connector_summary(name: str) -> None:
    fixture = answer(name)
    tool = fixture.tool
    run, unit, tools = make(FakeRpc(fixture))
    tools[tool].run(ARGS[tool])
    unit.on_call(record(tool, ARGS[tool]))
    ((args, kw),) = run.put_calls
    assert args[3] == SUMMARIES[CONNECTOR_OF[tool]] and kw["item"]["label"] == LABELS[tool]


def test_WORKSPACE_TOOLS_B_WT05_a_result_the_screen_dropped_was_still_read_and_is_still_recorded() -> None:
    run, unit, tools = make(FakeRpc(answer("ok_search_email")))
    tools["search_email"].run(ARGS["search_email"])
    unit.on_call(dataclasses.replace(record("search_email", ARGS["search_email"]), outcome="dropped"))
    assert len(run.put_calls) == 1  # the data left the account; the archive and the event say so


def test_WORKSPACE_TOOLS_B_WT05_a_record_for_a_call_that_read_nothing_writes_nothing() -> None:
    run, unit, tools = make(FakeRpc(answer("ok_search_email")))
    unit.on_call(record("search_email", ARGS["search_email"]))
    assert run.put_calls == []


def test_WORKSPACE_TOOLS_B_WT05_a_failed_write_never_raises_into_the_tool_loop() -> None:
    run, unit, tools = make(FakeRpc(answer("ok_search_email")))
    run.put = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("store down"))  # type: ignore[method-assign]
    tools["search_email"].run(ARGS["search_email"])
    unit.on_call(record("search_email", ARGS["search_email"]))


# ---- notifications ------------------------------------------------------------------------------------------------


def test_WORKSPACE_TOOLS_B_WT05_a_read_is_not_an_item_that_was_sent_in_the_bell(client: Any, store: Any) -> None:
    from _api_lib import base_event
    from test_S_06_cards_feed import World, at, sign_in

    World(store, "w_a", "u_alice")
    for seq, direction in enumerate(("in", "out"), start=1):
        event = base_event(seq=seq, type_="data.transfer", data={"direction": direction}, world_id="w_a", ts=at(seq))
        store.events.setdefault("w_a", []).append(event)
    sign_in("u_alice")
    items = client.get("/v1/notifications").json()["notifications"]
    assert [n["id"] for n in items] == [f"e:{store.events['w_a'][1]['id']}"] and items[0]["title"] == "An item was sent"


# ---- WT-01: the team share check ----------------------------------------------------------------------------------


def people_with_share(**changes: Any) -> PeopleStores:
    people = PeopleStores.in_memory()
    people.persons.create(person("u_orgowner", role="owner", teams=(LAUNCH,)))
    people.persons.create(person(ASHA, teams=(LAUNCH,)))
    people.world_shares.create(share(**changes))
    return people


def test_WORKSPACE_TOOLS_B_WT01_a_share_in_force_is_found_and_another_world_has_none() -> None:
    people = people_with_share()
    kw = {"stores": lambda: people, "clock": lambda: NOW}
    assert team_share_in_force(WORLD, ASHA, **kw) is True
    assert team_share_in_force(OTHER_WORLD, ASHA, **kw) is False


def test_WORKSPACE_TOOLS_B_WT01_a_revoked_share_or_one_a_previous_owner_granted_is_not_in_force() -> None:
    kw = {"clock": lambda: NOW}
    revoked = people_with_share(revoked={"by": ASHA, "at": T_GRANT})
    assert team_share_in_force(WORLD, ASHA, stores=lambda: revoked, **kw) is False
    granted_by_another = people_with_share(by="u_orgowner")
    assert team_share_in_force(WORLD, ASHA, stores=lambda: granted_by_another, **kw) is False


def test_WORKSPACE_TOOLS_B_WT01_what_cannot_be_checked_counts_as_shared_unless_no_people_store_exists() -> None:
    def broken() -> Any:
        raise RuntimeError("firestore down")

    def unavailable() -> Any:
        raise HTTPException(status_code=503, detail="not_configured")

    assert team_share_in_force(WORLD, ASHA, stores=broken) is True
    assert team_share_in_force(WORLD, ASHA, stores=unavailable, configured=lambda: True) is True
    assert team_share_in_force(WORLD, ASHA, stores=unavailable, configured=lambda: False) is False


def test_WORKSPACE_TOOLS_B_WT01_only_a_live_run_has_workspace_access_a_demo_is_replay_and_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "_seam_router", lambda mode, meter=None: None)
    assert deps.get_unit_runner("replay").workspace is None
    assert isinstance(deps.get_unit_runner("live").workspace, WorkspaceAccess)


# ---- default tool sets --------------------------------------------------------------------------------------------


def bound(brief: dict[str, Any]) -> BoundRunRunner:
    runner = BoundRunRunner.__new__(BoundRunRunner)
    runner.run_owner = SimpleNamespace(brief=brief)
    return runner


def test_WORKSPACE_TOOLS_B_default_tools_a_connector_source_gives_its_reads_to_the_worker_roles_only() -> None:
    sources = [{"kind": "connector", "ref": "gmail"}, {"kind": "connector", "ref": "google_drive"}]
    got = bound({"sources": [*sources, {"kind": "url", "ref": "https://example.org"}]}).default_tools()
    reads = ("search_email", "read_email", "list_files", "read_file")
    assert got == {"specialist": ("web_search", "fetch_url", *reads), "writer": reads, "verifier": reads}
    assert set(got) == {"specialist", "writer", "verifier"}  # never the Director, a Lead, the Narrator or Autopilot
    calendar = bound({"sources": [{"kind": "connector", "ref": "google_calendar"}]}).default_tools()
    assert calendar["writer"] == ("read_events",)
    assert bound({}).default_tools() == {"specialist": ("web_search", "fetch_url"), "writer": (), "verifier": ()}
    assert bound({"sources": [{"kind": "connector", "ref": "slack"}]}).default_tools()["writer"] == ()


# ---- in a run ------------------------------------------------------------------------------------------------------


class MailModels(rig.FakeModels):
    """The rig's model, except that a unit offered `search_email` asks for it first."""

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        offered = {d.name for t in getattr(config, "tools", None) or [] for d in t.function_declarations}
        if "search_email" in offered and "<<<TOOL_RESULT" not in str(contents):  # the template names TOOL_RESULT too
            self.configs.append(config)
            call = SimpleNamespace(name="search_email", args=ARGS["search_email"])
            text = str(contents)
            usage = SimpleNamespace(
                prompt_token_count=len(text) // 4 + 1, candidates_token_count=20, total_token_count=len(text) // 4 + 21,
                thoughts_token_count=0, cached_content_token_count=None, prompt_tokens_details=None,
            )  # fmt: skip
            return SimpleNamespace(
                prompt_feedback=None,
                candidates=[SimpleNamespace(finish_reason="STOP")],
                usage_metadata=usage,
                function_calls=[call],
                text=None,
            )
        return super().generate_content(model=model, contents=contents, config=config)


def mail_run(tmp_path: Any, monkeypatch: pytest.MonkeyPatch, access: WorkspaceAccess) -> tuple[Any, Any, Any]:
    monkeypatch.setattr(rig, "FakeModels", MailModels)
    run, state, _asking, models = rig._run(tmp_path, monkeypatch, cap=40)
    compile_plan = run.seams.compiler

    def without_skills(**kwargs: Any) -> dict[str, Any]:
        plan = compile_plan(**kwargs)
        for unit in plan["units"]:
            unit["skills"] = []
        return plan

    workers = run.seams.runner._providers
    runner = ApiUnitRunner(workers, mode="replay", clock=lambda: date(2026, 10, 14), workspace=access)
    run.seams = dataclasses.replace(run.seams, compiler=without_skills, runner=runner)
    run.brief = {**run.brief, "sources": [{"kind": "connector", "ref": "gmail"}]}
    return run, state, models


def tool_sets(models: Any) -> list[set[str]]:
    return [
        {d.name for t in c.tools for d in t.function_declarations} for c in models.configs if getattr(c, "tools", None)
    ]


@pytest.mark.usefixtures("must_ask_ask_mode")
def test_WORKSPACE_TOOLS_B_in_a_run_a_connector_source_offers_the_reads_and_a_read_records_one_event_and_ends_fetch_url(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rpc = FakeRpc(answer("ok_search_email"))
    run, state, models = mail_run(tmp_path, monkeypatch, WorkspaceAccess(lambda: rpc, lambda world, owner: False))
    asyncio.run(rig._answer_and_finish(run, state))
    events = state.events[rig.WORLD]
    assert [e for e in events if e["type"] == "world.failed"] == []
    first, *later = tool_sets(models)
    assert first == {"web_search", "fetch_url", "search_email", "read_email"}
    assert later and all("fetch_url" not in names and "search_email" in names for names in later)  # WT-04
    assert rpc.calls and all(c == (OWNER, "search_email", ARGS["search_email"]) for c in rpc.calls)
    transfers = [e for e in events if e["type"] == "data.transfer"]
    assert len(transfers) == len(rpc.calls) >= 1  # one event per read that happened, none more
    transfer = transfers[0]
    assert transfer["data"]["direction"] == "in" and transfer["data"]["action_type"] == "search_email"
    assert transfer["authz"] == {"by": "person", "ref": OWNER, "at": "2026-10-01T08:00:00.000Z"}
    assert transfer["summary"] == "An agent read from Gmail." and transfer["item"]["label"] == "Mail search"
    assert transfer["trace"]["tool"] == "search_email" and transfer["trace"]["archive_ref"]
    assert "Invoice 1042" not in json.dumps(transfer) and "ana@example.org" not in json.dumps(transfer)


@pytest.mark.usefixtures("must_ask_ask_mode")
def test_WORKSPACE_TOOLS_B_in_a_run_a_world_shared_with_a_team_is_offered_no_read_tool_and_reads_nothing(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rpc = FakeRpc(answer("ok_search_email"))
    run, state, models = mail_run(tmp_path, monkeypatch, WorkspaceAccess(lambda: rpc, lambda world, owner: True))
    asyncio.run(rig._answer_and_finish(run, state))
    assert tool_sets(models) and all(names == {"web_search", "fetch_url"} for names in tool_sets(models))
    assert rpc.calls == [] and [e for e in state.events[rig.WORLD] if e["type"] == "data.transfer"] == []
    assert [e for e in state.events[rig.WORLD] if e["type"] == "world.failed"] == []


@pytest.mark.usefixtures("must_ask_ask_mode")
def test_WORKSPACE_TOOLS_B_in_a_replay_run_without_access_no_read_tool_is_offered(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, state, models = mail_run(tmp_path, monkeypatch, None)  # type: ignore[arg-type]
    asyncio.run(rig._answer_and_finish(run, state))
    assert tool_sets(models) and all(names == {"web_search", "fetch_url"} for names in tool_sets(models))
