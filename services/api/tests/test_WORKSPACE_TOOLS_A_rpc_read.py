"""WORKSPACE_TOOLS ticket A / ADR-0048 decision 3: `MeetingHostRpc.read`, the client of `/internal/workspace/read`.

A scripted transport stands in for tilo-connectors; the request and answer fixtures are the contract's own. No network,
no paid call; the ID token is assembled at run time.
"""

from __future__ import annotations

import copy
import json
import pathlib
import secrets
from typing import Any

import pytest
from tilo_api.meeting_host_rpc import (
    MAX_READ_REPLY_BYTES,
    READ_PATH,
    HostRpcError,
    MeetingHostRpc,
    Reply,
    TransportError,
)

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
URL = "https://tilo-connectors-" + secrets.token_hex(3) + ".a.run.app"
OWNER = "u_owner"


def fixture(kind: str, name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS / f"meeting_host_rpc.{kind}" / "valid" / f"{name}.json").read_text(encoding="utf-8"))


class Scripted:
    def __init__(self, *replies: Any) -> None:
        self.replies, self.calls = list(replies), []

    def post(self, url: str, body: bytes, headers: dict[str, str], timeout_s: float) -> Reply:
        self.calls.append({"url": url, "json": json.loads(body), "headers": headers, "timeout_s": timeout_s})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def client(*replies: Any) -> tuple[MeetingHostRpc, Scripted, str]:
    token, transport = "idtok." + secrets.token_hex(8), Scripted(*replies)
    return MeetingHostRpc(URL, transport=transport, token_for=lambda audience: token), transport, token


def ok(answer: dict[str, Any]) -> Reply:
    return Reply(200, json.dumps(answer).encode())


ARGS = {
    "search_email": {"query": "x"}, "read_email": {"message_id": "m1"}, "list_files": {},
    "read_events": {"start": "2026-10-17T00:00:00Z", "end": "2026-10-18T00:00:00Z"}, "read_file": {"file_id": "f1"},
}  # fmt: skip
SEARCH = fixture("read_request", "search_email")
SEARCHED = fixture("read_answer", "ok_search_email")


def test_WORKSPACE_TOOLS_A_rpc_read_posts_the_checked_request_to_the_read_route_with_an_id_token() -> None:
    rpc, transport, token = client(ok(SEARCHED))
    got = rpc.read(OWNER, SEARCH["tool"], SEARCH["args"])
    call = transport.calls[0]
    assert call["url"] == URL + READ_PATH and call["headers"]["Authorization"] == f"Bearer {token}"
    assert call["json"] == {"user_id": OWNER, "tool": "search_email", "args": SEARCH["args"]}
    assert (
        got.outcome == "ok" and got.tool == "search_email" and got.result is not None and got.connected_at is not None
    )


@pytest.mark.parametrize("name", ["ok_read_file_pdf", "ok_read_events", "ok_list_files", "ok_read_email_html_only"])
def test_WORKSPACE_TOOLS_A_rpc_read_accepts_every_valid_answer_fixture_of_its_tool(name: str) -> None:
    answer = fixture("read_answer", name)
    rpc, _, _ = client(ok(answer))
    assert rpc.read(OWNER, answer["tool"], ARGS[answer["tool"]]).outcome == "ok"


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("send_email", {"query": "x"}),  # a write is no read tool
        ("search_email", {"message_id": "m1"}),  # another tool's args
        ("search_email", {"query": "x", "world_id": "w_1"}),  # a world is never named
        ("read_events", {"start": "2026-10-17T00:00:00", "end": "2026-10-18T00:00:00Z"}),  # no offset
        ("list_files", {"query": "x" * 101}),  # list_files' own cap, not search_email's 200
        ("read_file", {"file_id": "https://drive.example/f"}),
    ],
)
def test_WORKSPACE_TOOLS_A_rpc_read_refuses_a_request_that_breaks_the_contract_before_any_call(
    tool: str, args: dict[str, Any]
) -> None:
    rpc, transport, _ = client()
    with pytest.raises(HostRpcError) as caught:
        rpc.read(OWNER, tool, args)
    assert caught.value.kind == "refused" and transport.calls == []


def test_WORKSPACE_TOOLS_A_rpc_read_an_address_is_no_user_id() -> None:
    rpc, transport, _ = client()
    with pytest.raises(HostRpcError):
        rpc.read("owner@example.com", "search_email", {"query": "x"})
    assert transport.calls == []


def broken(**changes: Any) -> dict[str, Any]:
    answer = copy.deepcopy(SEARCHED)
    answer.update(changes)
    return answer


@pytest.mark.parametrize(
    "answer",
    [
        broken(tool="read_email"),  # another tool's answer
        broken(connected_at=None),  # ok without the consent time
        broken(result=None),
        broken(outcome="not_connected"),  # not ok with a result
        broken(extra=1),
        broken(result={"messages": [], "link": "https://x.example"}),
        broken(outcome="refused"),
    ],
)
def test_WORKSPACE_TOOLS_A_rpc_read_an_answer_that_breaks_the_contract_is_unknown(answer: dict[str, Any]) -> None:
    rpc, _, _ = client(ok(answer))
    with pytest.raises(HostRpcError) as caught:
        rpc.read(OWNER, "search_email", SEARCH["args"])
    assert caught.value.kind == "unknown"


def test_WORKSPACE_TOOLS_A_rpc_read_an_answer_over_6_mib_or_not_json_is_unknown() -> None:
    for reply in (Reply(200, b"x" * (MAX_READ_REPLY_BYTES + 1)), Reply(200, b"not json"), Reply(200, b"[]")):
        rpc, _, _ = client(reply)
        with pytest.raises(HostRpcError) as caught:
            rpc.read(OWNER, "search_email", SEARCH["args"])
        assert caught.value.kind == "unknown"


def test_WORKSPACE_TOOLS_A_rpc_read_parts_naming_another_user_are_dropped() -> None:
    mine = {"type": "connection.expired", "connector": "gmail", "user_id": OWNER}
    theirs = {"type": "connection.expired", "connector": "gmail", "user_id": "u_other"}
    answer = fixture("read_answer", "expired_with_its_part")
    answer["parts"] = [theirs, mine]
    rpc, _, _ = client(ok(answer))
    got = rpc.read(OWNER, answer["tool"], ARGS[answer["tool"]])
    assert [p.model_dump() for p in got.parts] == [mine]


@pytest.mark.parametrize(
    ("status", "kind"), [(401, "refused"), (403, "refused"), (422, "refused"), (500, "unknown"), (503, "unknown")]
)
def test_WORKSPACE_TOOLS_A_rpc_read_connectors_refusals_and_failures_are_fixed_kinds(status: int, kind: str) -> None:
    rpc, _, _ = client(Reply(status, b'{"error":"x"}'))
    with pytest.raises(HostRpcError) as caught:
        rpc.read(OWNER, "search_email", SEARCH["args"])
    assert caught.value.kind == kind


def test_WORKSPACE_TOOLS_A_rpc_read_a_cut_connection_is_unknown_and_is_not_retried() -> None:
    rpc, transport, _ = client(TransportError(), Reply(200, json.dumps(SEARCHED).encode()))
    with pytest.raises(HostRpcError) as caught:
        rpc.read(OWNER, "search_email", SEARCH["args"])
    assert caught.value.kind == "unknown" and len(transport.calls) == 1
