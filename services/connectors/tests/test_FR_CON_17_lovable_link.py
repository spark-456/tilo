"""FR-CON-17 (supplement s6): Lovable, link route. "Tilo makes a Lovable 'Build with URL' link from the accepted
requirements. The person opens it and presses send in Lovable. No key and no Tilo token; nothing leaves Tilo until
the person clicks." Acceptance: "The link decodes to the approved prompt; it stays under the URL length limit, or
Tilo says the brief is too long and offers the MCP route; no call to Lovable from Tilo."

API_FR_CON_16_17_20.md "tilo_connectors.adapters.lovable". The BriefTooLong cases at prepare time are in
test_FR_CON_16_prepare_handoff.py; the dispatch-time recheck, the link record and the no-network rule are here.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import re
import socket
from urllib.parse import quote

import pytest
from _handoff_lib import (
    GOOD_FRAMING,
    LINK_PREFIX,
    RUN,
    SRC,
    UNIT,
    WORLD,
    accept,
    approved_brief,
    collapse,
    enqueue,
    link_record_bytes,
    link_url,
    lowered,
    lv,
    make_env,
    oracle_link,
    run_flow,
    settle,
)
from hypothesis import given, settings
from hypothesis import strategies as st

SPECIAL = "Fish & chips # 100% + tax ? a=b;c/d é日本語 \U0001f600 ~ _ - . '\"<>"


# --- the link is a percent-encoded fragment of the approved prompt (a) -------------------------------------------


def test_FR_CON_17_the_link_decodes_to_the_approved_prompt():
    flow = run_flow(make_env())
    assert [e["state"] for e in _send(flow)] == ["sent"]
    url = link_url(flow.env)
    assert url.startswith(lv().LOVABLE_LINK_PREFIX) and url.startswith("https://lovable.dev/#prompt=")
    assert "?" not in url
    assert "autosubmit" not in url
    assert lv().decode_link(url) == flow.prepared.prompt
    assert url == oracle_link(flow.prepared.prompt), "the link is the prefix plus quote(prompt, safe='')"


def _send(flow):
    enqueue(flow.env, flow.case)
    return flow.env.outbox.dispatch_due()


def test_FR_CON_17_the_link_prompt_rides_in_the_fragment_with_no_query_and_no_extra_parameters():
    flow = run_flow(make_env())
    _send(flow)
    url = link_url(flow.env)
    assert lv().LOVABLE_LINK_PREFIX == "https://lovable.dev/#prompt="
    assert url.count("#") == 1 and url.count("?") == 0 and url.count("&") == 0 and url.count("=") == 1
    assert "html=" not in url and "autosubmit" not in url


def test_FR_CON_17_the_link_decodes_to_the_prompt_for_text_holding_reserved_characters_and_non_ascii():
    flow = run_flow(
        make_env(),
        accepted=accept(brief=approved_brief(constraints=[SPECIAL, "Works on a phone"])),
        framing=GOOD_FRAMING,
    )
    _send(flow)
    url = link_url(flow.env)
    assert lv().decode_link(url) == flow.prepared.prompt
    assert SPECIAL in flow.prepared.prompt
    raw = url.removeprefix(LINK_PREFIX)
    for reserved in ("&", "#", "?", "+", " ", "\n", "%%", "=", "/", "é", "\U0001f600"):
        assert reserved not in raw, f"{reserved!r} must be percent-encoded in the link"
    assert re.fullmatch(r"[A-Za-z0-9_.~%-]*", raw)


def test_FR_CON_17_the_link_decodes_to_the_prompt_for_granted_excerpt_text_with_every_hostile_character():
    env = make_env()
    text = "line one\r\nline & two # three ? four\n\n%41 %2 %zz + plus\ttab \U0001f600 é ```fence```"
    flow = run_flow(
        env,
        grant_specs=(("art_notes", 1, "Notes"),),
        texts={("art_notes", 1): text},
    )
    _send(flow)
    assert lv().decode_link(link_url(env)) == flow.prepared.prompt
    assert "line one\nline & two # three ? four" in flow.prepared.prompt, "CRLF is normalised to LF in an excerpt"
    assert "\r" not in flow.prepared.prompt


_line = (
    st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc", "Zl", "Zp")), min_size=1, max_size=80)
    .map(collapse)
    .filter(bool)
)


@settings(max_examples=25, deadline=None)
@given(constraints=st.lists(_line, min_size=1, max_size=4), goal=_line)
def test_FR_CON_17_property_the_link_always_decodes_to_the_prepared_prompt(constraints, goal):
    flow = run_flow(make_env(), accepted=accept(brief=approved_brief(goal=goal, constraints=constraints)))
    _send(flow)
    url = link_url(flow.env)
    assert lv().decode_link(url) == flow.prepared.prompt
    assert len(url) == lv().link_length(flow.prepared.prompt) == flow.prepared.link_length


# --- link_length and decode_link -------------------------------------------------------------------------------


def test_FR_CON_17_link_length_is_the_prefix_plus_the_percent_encoded_prompt():
    for prompt in ("", "plain words", SPECIAL, "é" * 10, "\U0001f600", "a\nb\n"):
        assert lv().link_length(prompt) == len(LINK_PREFIX) + len(quote(prompt, safe=""))
    assert lv().link_length("é") == len(LINK_PREFIX) + 6
    assert lv().link_length("\U0001f600") == len(LINK_PREFIX) + 12, "four UTF-8 bytes, three characters each"
    assert lv().link_length(" ") == len(LINK_PREFIX) + 3, "a space is %20, never +"


@settings(max_examples=100, deadline=None)
@given(text=st.text())
def test_FR_CON_17_property_decode_link_inverts_the_encoding_and_link_length_is_exact(text):
    url = LINK_PREFIX + quote(text, safe="")
    assert lv().decode_link(url) == text
    assert len(url) == lv().link_length(text)


@pytest.mark.parametrize(
    "url",
    [
        "http://lovable.dev/#prompt=hello",
        "https://lovable.dev/?prompt=hello",
        "https://lovable.dev/#prompt=hello&autosubmit=true",
        "https://lovable.dev/#prompt=hello#again",
        "https://lovable.dev/#prompt=hello?x=1",
        "https://lovable.dev/#prompt=hello%FFworld",  # not UTF-8
        "https://lovable.dev/#prompt=%C3",  # truncated UTF-8
        "https://lovable.dev.evil.example/#prompt=hello",
        "https://evil.example/#prompt=hello",
        "https://lovable.dev/#prompt=hello&images=https%3A%2F%2Fevil.example%2Fa.png",
        " https://lovable.dev/#prompt=hello",
        "https://lovable.dev/#prompt=hello\n",
        "",
        "hello",
    ],
)
def test_FR_CON_17_decode_link_refuses_anything_but_the_prefix_and_one_percent_encoded_value(url):
    with pytest.raises(ValueError):
        lv().decode_link(url)


def test_FR_CON_17_decode_link_reads_percent_escapes_not_plus_signs():
    assert lv().decode_link(LINK_PREFIX + "a%2Bb%20c%26d%23e%3Ff%25g") == "a+b c&d#e?f%g"
    assert lv().decode_link(LINK_PREFIX + "a%20b+c") == "a b+c", "unquote, not unquote_plus"


# --- dispatch: the limits are checked again against the config in force (b) -----------------------------------------


def test_FR_CON_17_a_handoff_prepared_under_a_larger_url_limit_fails_at_dispatch_after_the_limit_was_lowered(tmp_path):
    flow = run_flow(make_env())
    n = flow.prepared.link_length
    late = flow.env.with_partner(lowered(tmp_path, max_url_length=n - 1))
    assert settle(late, flow.case) == ["failed"]
    assert late.links.links == [] and late.transfers() == []


def test_FR_CON_17_a_handoff_prepared_under_a_larger_character_limit_fails_at_dispatch_after_the_limit_was_lowered(
    tmp_path,
):
    flow = run_flow(make_env())
    n = len(flow.prepared.prompt)
    late = flow.env.with_partner(lowered(tmp_path, max_prompt_chars=n - 1))
    assert settle(late, flow.case) == ["failed"]
    assert late.links.links == [] and late.transfers() == []


def test_FR_CON_17_at_the_exact_limits_dispatch_still_makes_the_link_and_never_truncates(tmp_path):
    flow = run_flow(make_env())
    exact = flow.env.with_partner(
        lowered(tmp_path, max_url_length=flow.prepared.link_length, max_prompt_chars=len(flow.prepared.prompt))
    )
    assert settle(exact, flow.case) == ["sent"]
    assert lv().decode_link(link_url(exact)) == flow.prepared.prompt


# --- the link record -------------------------------------------------------------------------------------------------


def test_FR_CON_17_the_link_record_is_the_pinned_canonical_json_and_the_result_is_link_ready():
    flow = run_flow(make_env())
    (settled,) = _send(flow)
    assert settled["state"] == "sent"
    (link,) = flow.env.links.links
    expected = link_record_bytes(oracle_link(flow.prepared.prompt), flow.record.prompt, flow.case["entry"]["id"])
    assert link.content == expected
    assert link.content.decode("ascii").isascii()
    assert (link.world_id, link.run_id, link.unit_id, link.idempotency_key) == (
        WORLD,
        RUN,
        UNIT,
        flow.record.link_idempotency_key,
    )
    assert link.media_type == "application/json"


def test_FR_CON_17_the_link_record_holds_no_label_and_only_the_two_pinned_prompt_keys():
    flow = run_flow(make_env())
    _send(flow)
    body = json.loads(flow.env.links.links[0].content)
    assert set(body["prompt"]) == {"artifact_id", "version"}
    assert set(body) == {"v", "partner", "route", "url", "prompt", "outbox_id", "project_id", "status"}


def test_FR_CON_17_the_url_is_in_the_stored_record_only_never_in_an_event():
    flow = run_flow(make_env())
    _send(flow)
    url = link_url(flow.env)
    for part in flow.env.emitted:
        assert url not in json.dumps(part)
        assert "lovable.dev" not in json.dumps(part)


def test_FR_CON_17_a_failing_link_store_is_retried_and_the_same_key_leaves_one_link_and_one_transfer():
    class FlakyLinks(lv().InMemoryLinkStore):
        def __init__(self):
            super().__init__()
            self.fail = 1

        def put(self, link):
            if self.fail:
                self.fail -= 1
                raise RuntimeError("link store unavailable")
            return super().put(link)

    flaky = FlakyLinks()
    env = make_env(links=flaky)
    flow = run_flow(env)
    enqueue(env, flow.case)
    for _ in range(5):
        env.outbox.dispatch_due()
    assert len(flaky.links) == 1 and len(env.transfers()) == 1
    assert env.outbox.get(flow.case["entry"]["id"])["state"] == "sent"


def test_FR_CON_17_in_memory_link_store_returns_the_same_ref_for_the_same_key():
    store = lv().InMemoryLinkStore()
    link = lv().LinkArtifact(
        world_id=WORLD,
        run_id=RUN,
        unit_id=UNIT,
        agent_id="A_writer1",
        idempotency_key=f"{RUN}:{UNIT}:1:1",
        media_type="application/json",
        content=b"{}",
    )
    first = store.put(link)
    assert store.put(link) == first
    assert len(store.links) == 1
    other = dataclasses.replace(link, idempotency_key=f"{RUN}:{UNIT}:2:1")
    assert store.put(other) != first
    assert len(store.links) == 2
    assert set(first) >= {"artifact_id", "version"}


# --- no call to Lovable from Tilo (c) --------------------------------------------------------------------------------

FORBIDDEN = (
    "socket",
    "ssl",
    "http",
    "urllib.request",
    "httpx",
    "requests",
    "aiohttp",
    "urllib3",
    "websockets",
    "grpc",
    "google",
    "tilo_connectors.live",
    "tilo_connectors.tokens",
    "tilo_connectors.adapters._transport",
    "tilo_connectors.adapters._google",
    "tilo_providers",
    "openai",
    "anthropic",
)
LOVABLE = SRC / "adapters" / "lovable.py"
MODULES = {
    LOVABLE: "tilo_connectors.adapters.lovable",
    SRC / "handoff.py": "tilo_connectors.handoff",
    SRC / "grants.py": "tilo_connectors.grants",
}


def _imports(path):
    """(resolved dotted name, inside `if TYPE_CHECKING`) for every import in the module, relative ones resolved."""
    assert path.is_file(), f"{path} does not exist yet"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = MODULES[path].rsplit(".", 1)[0]
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            name = test.id if isinstance(test, ast.Name) else getattr(test, "attr", "")
            if name == "TYPE_CHECKING":
                guarded |= {id(n) for child in node.body for n in ast.walk(child)}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, id(node) in guarded) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join(parts + ([node.module] if node.module else []))
            found.append((base, id(node) in guarded))
            found += [(f"{base}.{a.name}", id(node) in guarded) for a in node.names]
    return found


@pytest.mark.parametrize("path", list(MODULES), ids=lambda p: p.name)
def test_FR_CON_17_no_call_to_lovable_from_tilo_the_modules_import_no_network_token_or_model_module(path):
    for name, _guarded in _imports(path):
        for bad in FORBIDDEN:
            assert name != bad and not name.startswith(bad + "."), f"{path.name} imports {name}"


def test_FR_CON_17_the_adapter_imports_handoff_and_grants_only_under_type_checking():
    imports = _imports(LOVABLE)
    for name, guarded in imports:
        if name in ("tilo_connectors.handoff", "tilo_connectors.grants") or name.startswith(
            ("tilo_connectors.handoff.", "tilo_connectors.grants.")
        ):
            assert guarded, f"adapters/lovable.py imports {name} at run time"


def test_FR_CON_17_handoff_gets_link_length_from_the_adapter():
    names = {name for name, _ in _imports(SRC / "handoff.py")}
    assert "tilo_connectors.adapters.lovable" in names or "tilo_connectors.adapters.lovable.link_length" in names


def test_FR_CON_17_only_the_adapter_builds_a_lovable_link():
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if p != LOVABLE
        and ("lovable.dev" in p.read_text(encoding="utf-8") or "LOVABLE_LINK_PREFIX" in p.read_text(encoding="utf-8"))
    ]
    assert LOVABLE.is_file(), "adapters/lovable.py does not exist yet"
    assert offenders == []
    public = [
        n
        for n, v in vars(lv()).items()
        if not n.startswith("_") and callable(v) and re.search(r"(build|make|create|encode|to)_?(link|url)", n)
    ]
    assert public == [], f"a public link builder: {public}"


def test_FR_CON_17_the_adapter_takes_no_transport_broker_or_token():
    params = inspect.signature(lv().LovableLinkAdapter.__init__).parameters
    assert set(params) - {"self"} == {"declaration", "partner", "handoffs", "grants", "artifacts", "links"}
    for p in params.values():
        if p.name != "self":
            assert p.kind is inspect.Parameter.KEYWORD_ONLY


def test_FR_CON_17_the_adapter_id_is_the_declarations_id():
    assert make_env().adapter.id == "lovable"


def test_FR_CON_17_no_call_to_lovable_from_tilo_blocked_sockets_prove_steps_1_to_10_make_no_connection(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a network call was attempted")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    flow = run_flow(
        make_env(),
        grant_specs=(("art_notes", 1, "Notes"),),
        texts={("art_notes", 1): "Notes for the client."},
    )
    assert [e["state"] for e in _send(flow)] == ["sent"]
    assert len(flow.env.links.links) == 1
    assert len(flow.env.transfers()) == 1


def test_FR_CON_17_nothing_leaves_tilo_until_the_person_clicks_so_a_refused_handoff_makes_no_link_at_all():
    flow = run_flow(make_env())
    env = flow.env
    env.artifacts.replace_bytes(WORLD, flow.record.prompt, b"changed")
    assert settle(env, flow.case) == ["failed"]
    assert env.links.links == []
