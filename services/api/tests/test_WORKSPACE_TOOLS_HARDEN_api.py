"""WORKSPACE_TOOLS hardening pass (security review follow-ups, ADR-0048 WT-01, WT-02, WT-05): tilo-api half.

A window out of range is refused, not an error; a PDF the media layer refuses was still read and so still recorded; the
team-share check reads the owner's own record and the world's shares only; and the answer of another tool is never
taken for the one asked. Fakes only: no network, no paid call.
"""

from __future__ import annotations

from typing import Any

import pytest
from _tsw1_lib import ASHA, LAUNCH, NOW, ORG, WORLD, person, share
from test_WORKSPACE_TOOLS_A_rpc_read import ARGS as RPC_ARGS
from test_WORKSPACE_TOOLS_A_rpc_read import OWNER as RPC_OWNER
from test_WORKSPACE_TOOLS_A_rpc_read import client, fixture, ok
from test_WORKSPACE_TOOLS_B_workspace_tools import ARGS, FakeRpc, answer, make, record
from tilo_api.meeting_host_rpc import HostRpcError
from tilo_api.workspace_tools import NOT_READABLE, team_share_in_force, window_ok
from tilo_people.stores import PeopleStores


def test_WORKSPACE_TOOLS_HARDEN_year_9999_with_an_offset_is_not_a_window() -> None:
    assert window_ok("9999-12-31T23:00:00-05:00", "9999-12-31T23:30:00-05:00") is False
    rpc = FakeRpc(answer("ok_read_events"))
    _, _, tools = make(rpc)
    tools["read_events"].run({"start": "9999-12-31T23:00:00-05:00", "end": "9999-12-31T23:30:00-05:00"})
    assert rpc.calls == []


def test_WORKSPACE_TOOLS_HARDEN_a_pdf_the_media_layer_refuses_was_still_read_and_is_recorded() -> None:
    run, unit, tools = make(FakeRpc(answer("ok_read_file_pdf")))  # the fixture's bytes have no pages
    assert tools["read_file"].run(ARGS["read_file"]).content == NOT_READABLE
    unit.on_call(record("read_file", ARGS["read_file"]))
    ((args, kw),) = run.put_calls
    assert args[0] == "data.transfer" and kw["item"]["label"] == "1 Drive file"


class Spy:
    """A record store that counts what is read from it."""

    def __init__(self, inner: Any) -> None:
        self._inner, self.calls = inner, []

    def get(self, *a: Any) -> Any:
        self.calls.append(("get", *a))
        return self._inner.get(*a)

    def list(self, *a: Any) -> Any:
        self.calls.append(("list", *a))
        return self._inner.list(*a)


def spied() -> tuple[Any, Spy, Spy]:
    people = PeopleStores.in_memory()
    for p in (person("u_orgowner", role="owner", teams=(LAUNCH,)), person(ASHA, teams=(LAUNCH,)), person("u_ben")):
        people.persons.create(p)
    people.world_shares.create(share())
    persons, shares = Spy(people.persons), Spy(people.world_shares)
    return type("P", (), {"persons": persons, "world_shares": shares})(), persons, shares


def test_WORKSPACE_TOOLS_HARDEN_the_share_check_reads_the_owners_record_and_the_worlds_shares_only() -> None:
    people, persons, shares = spied()
    assert team_share_in_force(WORLD, ASHA, stores=lambda: people, clock=lambda: NOW) is True
    assert sorted(persons.calls) == [("get", ORG, ASHA), ("get", ORG, "u_orgowner")]  # never "u_ben", never a list
    assert shares.calls == [("list", ORG, "world_id", WORLD)]


def test_WORKSPACE_TOOLS_HARDEN_a_world_with_no_share_reads_no_person_at_all() -> None:
    people, persons, shares = spied()
    assert team_share_in_force("w_other", ASHA, stores=lambda: people, clock=lambda: NOW) is False
    assert persons.calls == [] and len(shares.calls) == 1


def test_WORKSPACE_TOOLS_HARDEN_an_owner_with_no_record_has_no_share_in_force() -> None:
    people, persons, _ = spied()
    assert team_share_in_force(WORLD, "u_nobody", stores=lambda: people, clock=lambda: NOW) is False


def test_WORKSPACE_TOOLS_HARDEN_the_answer_of_another_tool_is_never_taken_for_the_one_asked() -> None:
    other = fixture("read_answer", "ok_list_files")  # valid for list_files, not for search_email
    rpc, _, _ = client(ok(other))
    with pytest.raises(HostRpcError) as caught:
        rpc.read(RPC_OWNER, "search_email", RPC_ARGS["search_email"])
    assert caught.value.kind == "unknown"
