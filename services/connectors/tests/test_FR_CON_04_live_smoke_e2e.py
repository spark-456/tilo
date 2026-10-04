"""FR-CON-04 live Gmail smoke harness, part 3: `run_smoke` and the CLI end to end (PRD 5.4 CP1 "Gmail sign-in
reads a test inbox", PRD 12.1, 12.6 FR-CON-04, 16.1 SEC-02, EFF-01).

The one command with LIVE=1 prints the Google consent URL, waits for the redirect on 127.0.0.1, exchanges the
code (tokens in memory only), lists up to 5 recent messages as date/from/subject, and with a draft address
creates one draft. It never sends. Here it runs against a fake Google on 127.0.0.1 (real HTTP, real sockets):
the production code is unchanged, Google's hosts are mapped to the fake by the loopback-only test seam.
API_FR_CON_04_live_smoke.md pins the names. No test leaves 127.0.0.0/8.

Every test fails today with `ModuleNotFoundError: tilo_connectors.live`.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import io
import logging
import os
import re
import subprocess
import sys
import time
import traceback

import pytest
import yaml
from _gapi_lib import recipients_of
from _live_lib import (
    CALLBACK_PATH,
    GMAIL_PREFIX,
    Running,
    World,
    approve,
    deny,
    event_problems,
    get_callback,
    has_control,
    live_world,  # noqa: F401 - fixture `world`
    no_external_network,  # noqa: F401 - autouse guard
    port_is_closed,
    start_smoke,
)
from _oauth_lib import GMAIL_COMPOSE, GMAIL_READONLY, GMAIL_SEND, REPO_ROOT, fake_secret, leaks, parse_auth_url

DRAFT_TO = "tilo.smoke.target@example.com"
SCRIPT = REPO_ROOT / "services" / "connectors" / "scripts" / "live_gmail_smoke.py"
FORBIDDEN_SCOPES = {GMAIL_SEND, "https://www.googleapis.com/auth/gmail.modify", "https://mail.google.com/"}


def live():
    return importlib.import_module("tilo_connectors.live")


def script():
    spec = importlib.util.spec_from_file_location("live_gmail_smoke_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gmail_declaration() -> dict:
    entries = yaml.safe_load((REPO_ROOT / "config" / "connectors.yaml").read_text(encoding="utf-8"))
    return next(e for e in entries if e["id"] == "gmail")


def full_run(world: World, **options):
    run = start_smoke(world, **options)
    flow, code, reply = approve(world, run)
    return run, flow, code, reply, run.value()


def chain(error: BaseException) -> str:
    return "".join(traceback.format_exception(error)) + str(error) + repr(error)


def all_text(world: World, run: Running, caplog, capsys, *more: str) -> str:
    printed = capsys.readouterr()
    return "\n".join([run.out.getvalue(), caplog.text, printed.out, printed.err, *more])


# ---------------------------------------------------------------------------
# The happy path (read only)


def test_FR_CON_04_live_smoke_end_to_end_lists_the_five_newest_messages_and_nothing_else(
    world, caplog, capsys, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.DEBUG)
    seeded = world.seed_inbox(7)
    run = start_smoke(world)

    url = run.url()
    flow = parse_auth_url(url)
    assert flow.base == "https://accounts.google.com/o/oauth2/v2/auth"
    assert flow.query["client_id"] == world.environ["GOOGLE_OAUTH_CLIENT_ID"]
    assert flow.query["redirect_uri"] == f"http://127.0.0.1:{world.callback_port}{CALLBACK_PATH}"
    assert flow.query["response_type"] == "code" and flow.query["code_challenge_method"] == "S256"
    assert flow.scopes == [GMAIL_READONLY]  # CP1: read the test inbox, nothing more

    _, code, (status, _, page) = approve(world, run)
    result = run.value()

    assert status == 200 and not leaks(page, [code])
    newest = list(reversed(seeded))[:5]
    assert result.messages == [{"date": m["date"], "from": m["from"], "subject": m["subject"]} for m in newest]
    assert result.draft is None

    out = run.out.getvalue()
    assert out.count(url) == 1, "the consent URL is printed once, in full"
    for m in newest:
        assert m["subject"] in out and m["from"] in out and m["date"] in out
    for m in seeded:  # no body, no id; and the two oldest messages are not listed
        assert m["body"] not in out and m["id"] not in out
    assert seeded[0]["subject"] not in out and seeded[1]["subject"] not in out
    assert "Traceback" not in out

    assert len(world.env.google.exchange_calls()) == 1 and len(world.server.token_posts()) == 1
    assert world.server.writes() == [] and world.server.sends() == [], "a read-only run makes zero write calls"
    list_calls = [h for h in world.server.gmail_hits("GET") if "maxResults" in h.query]
    assert list_calls and all(int(h.query["maxResults"][0]) <= 5 for h in list_calls)
    fetches = [
        h for h in world.server.gmail_hits("GET") if re.fullmatch(rf"{GMAIL_PREFIX}/(messages|threads)/[^/]+", h.path)
    ]
    assert 1 <= len(fetches) <= 5

    assert [connector for _, connector in world.store.live_keys()] == ["gmail"], "one in-memory record"
    assert not leaks(world.store.ever_text(), world.secrets()), "only sealed tokens ever reach the store"
    assert list(tmp_path.iterdir()) == [], "tokens and mail are never written to disk"
    assert not leaks(all_text(world, run, caplog, capsys), world.secrets())
    assert port_is_closed(world.callback_port), "the listener shuts down after its one callback"
    with pytest.raises(OSError):
        get_callback(world.callback_port, {"code": code, "state": flow.state})  # a reused state finds nobody


@pytest.mark.parametrize("count", [0, 3, 5, 6, 12])
def test_FR_CON_04_live_smoke_never_lists_or_reads_more_than_five_messages(world, count):
    seeded = world.seed_inbox(count)
    _, _, _, _, result = full_run(world)
    assert [m["subject"] for m in result.messages] == [m["subject"] for m in reversed(seeded)][:5]
    fetches = [
        h for h in world.server.gmail_hits("GET") if re.fullmatch(rf"{GMAIL_PREFIX}/(messages|threads)/[^/]+", h.path)
    ]
    assert len(fetches) <= 5
    assert all(set(m) == {"date", "from", "subject"} for m in result.messages)


def test_FR_CON_04_live_smoke_neutralises_control_characters_in_mail_headers(world):
    hostile = "\x1b[31mRED\x1b[0m\x07 bell\x9b31m next\u202eevil"
    world.seed_inbox(2, hostile_subject=hostile)
    run, _, _, _, result = full_run(world)
    for message in result.messages:
        assert not any(has_control(value) for value in message.values()), message
    assert any("RED" in m["subject"] and "bell" in m["subject"] for m in result.messages), "text is kept"
    printable = run.out.getvalue().replace("\n", "").replace("\t", "")
    assert not has_control(printable), "terminal escapes from mail never reach the terminal"


# ---------------------------------------------------------------------------
# --draft: one draft, never a send


def test_FR_CON_04_live_smoke_draft_creates_exactly_one_draft_and_never_sends(world):
    seeded = world.seed_inbox(3)
    run, flow, _, _, result = full_run(world, draft_to=DRAFT_TO)

    assert set(flow.scopes) == {GMAIL_READONLY, GMAIL_COMPOSE}
    assert len(world.server.draft_posts()) == 1, "exactly one draft"
    assert world.server.sends() == [], "no send endpoint is ever called"
    assert [(h.method, h.path) for h in world.server.writes()] == [("POST", f"{GMAIL_PREFIX}/drafts")]

    (draft,) = world.apis.draft_messages()
    assert recipients_of(draft) == {DRAFT_TO}, "To is exactly the given address"
    assert not draft.get_all("Cc") and not draft.get_all("Bcc")
    assert str(draft["Subject"]).strip()
    text = draft.as_string()
    for m in seeded:
        assert m["body"] not in text and m["subject"] not in text and m["from"] not in text, "no mailbox data in it"

    assert result.draft and result.draft["outbox_id"], "the draft went through the outbox (SEC-03)"
    (transfer,) = [p for p in result.events if p["type"] == "data.transfer"]
    assert transfer["data"]["direction"] == "out" and transfer["data"]["connector"] == "gmail"
    assert transfer["data"]["action_type"] == "create_draft"
    assert transfer["authz"]["by"] == "person", "T3 and every side effect need a person, never a model"
    assert len(result.messages) == 3 and "Traceback" not in run.out.getvalue()


def test_FR_CON_04_live_smoke_a_draft_google_refuses_is_a_failure_and_is_not_retried(world):
    world.seed_inbox(1)
    world.apis.fail_next(400, times=5, when=lambda r: r.method == "POST" and r.url.endswith("/drafts"))
    run = start_smoke(world, draft_to=DRAFT_TO)
    approve(world, run)
    error = run.raised(live().SmokeError)
    assert str(error) and "Traceback" not in run.out.getvalue()
    assert len(world.server.draft_posts()) == 1 and world.apis.draft_messages() == []
    assert world.server.sends() == []


@pytest.mark.parametrize(
    "address",
    [
        "",
        "nope",
        "a@example.com,b@example.com",
        "a@example.com\nBcc: b@example.net",
        "a@@example.com",
        "a b@example.com",
    ],
)
def test_FR_CON_04_live_smoke_draft_address_must_be_one_plain_address(world, address):
    run = start_smoke(world, draft_to=address, callback_timeout_s=3)
    error = run.raised(live().SmokeError)
    assert not isinstance(error, live().CallbackTimeout), "refused up front, not after waiting"
    assert run.out.getvalue().count("accounts.google.com") == 0 and port_is_closed(world.callback_port)
    assert world.server.hits == []


# ---------------------------------------------------------------------------
# Scopes (FR-CON-03 incremental, PRD 16.1 least privilege)


@pytest.mark.parametrize("draft", [False, True])
def test_FR_CON_04_live_smoke_scopes_are_the_declared_least_privilege_and_incremental(world, draft):
    declared = gmail_declaration()["scopes"]
    assert declared["write"] == [GMAIL_COMPOSE] and declared["read"] == [GMAIL_READONLY]  # the config under test
    run = start_smoke(world, **({"draft_to": DRAFT_TO} if draft else {}))
    flow = parse_auth_url(run.url())
    deny(world, run)  # only the URL was wanted
    run.raised(live().SmokeError)

    asked = set(flow.scopes)
    expected = set(declared["read"]) | set(declared["search"]) | (set(declared["write"]) if draft else set())
    assert asked == expected, "exactly the declared scopes of the capabilities used"
    assert not asked & FORBIDDEN_SCOPES
    assert all(s.startswith("https://www.googleapis.com/auth/gmail.") for s in asked), "no Drive, no openid"
    assert (GMAIL_COMPOSE in asked) is draft, "a read-only run does not ask for compose"
    assert run.out.getvalue().count("accounts.google.com/o/oauth2") == 1, "one consent URL per run"


# ---------------------------------------------------------------------------
# Callback outcomes


def test_FR_CON_04_live_smoke_access_denied_is_a_clean_failure(world, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    world.seed_inbox(2)
    run = start_smoke(world)
    _, (status, _, page) = deny(world, run)
    error = run.raised(live().SmokeError)

    assert status < 500 and "Traceback" not in page
    assert str(error) and "Traceback" not in run.out.getvalue()
    assert world.env.google.exchange_calls() == [] and world.server.gmail_hits() == []
    assert world.store.live_keys() == [] and port_is_closed(world.callback_port)
    assert not leaks(all_text(world, run, caplog, capsys, chain(error)), world.secrets())


def test_FR_CON_04_live_smoke_a_forged_callback_is_rejected_and_never_exchanged(world):
    run = start_smoke(world, callback_timeout_s=1.5)
    flow = parse_auth_url(run.url())
    code = world.env.google.issue_code(
        flow.scopes, challenge=flow.query["code_challenge"], redirect_uri=flow.query["redirect_uri"]
    )
    world.codes.append(code)
    for params in ({"code": code, "state": "forged"}, {"code": code}, {"code": code, "state": flow.state[::-1]}):
        assert get_callback(world.callback_port, params)[0] == 400
    error = run.raised(live().CallbackTimeout)
    assert world.env.google.exchange_calls() == [] and world.server.gmail_hits() == []
    assert not leaks(chain(error) + run.out.getvalue(), world.secrets())


def test_FR_CON_04_live_smoke_times_out_when_no_redirect_arrives(world):
    started = time.monotonic()
    run = start_smoke(world, callback_timeout_s=0.5)
    error = run.raised(live().CallbackTimeout)
    assert time.monotonic() - started < 5.0
    assert isinstance(error, live().SmokeError) and str(error)
    assert world.server.hits == [] and world.store.live_keys() == [] and port_is_closed(world.callback_port)
    assert "Traceback" not in run.out.getvalue()


def test_FR_CON_04_live_smoke_a_refused_code_never_echoes_what_google_sent_back(world, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    run = start_smoke(world)
    flow = parse_auth_url(run.url())
    bogus = fake_secret("code")  # never issued: the fake Google answers 400 and echoes the code, as a careless one does
    world.codes.append(bogus)
    get_callback(world.callback_port, {"code": bogus, "state": flow.state})
    error = run.raised(live().SmokeError)
    assert len(world.env.google.exchange_calls()) == 1 and world.store.live_keys() == []
    assert not leaks(all_text(world, run, caplog, capsys, chain(error)), world.secrets())
    assert world.server.gmail_hits() == []


# ---------------------------------------------------------------------------
# Configuration is checked before anything is bound or printed


@pytest.mark.parametrize(
    "redirect_base",
    [
        "https://tilo.example.com",
        "https://localhost:8080",
        "http://0.0.0.0:8080",
        "http://example.com:8080",
        "ftp://x",
        "nonsense",
    ],
)
def test_FR_CON_04_live_smoke_redirect_must_be_a_loopback_http_address(world, redirect_base):
    environ = {**world.environ, "GOOGLE_OAUTH_REDIRECT_BASE_URL": redirect_base}
    run = start_smoke(world, environ=environ, callback_timeout_s=3)
    error = run.raised(live().SmokeError)
    assert not isinstance(error, live().CallbackTimeout)
    assert "accounts.google.com" not in run.out.getvalue() and world.server.hits == []


@pytest.mark.parametrize("missing", ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"])
def test_FR_CON_04_live_smoke_missing_credentials_name_the_variable_not_its_value(world, missing):
    environ = {k: v for k, v in world.environ.items() if k != missing}
    run = start_smoke(world, environ=environ, callback_timeout_s=3)
    error = run.raised(live().SmokeError)
    assert missing in str(error) and not isinstance(error, live().CallbackTimeout)
    assert not leaks(chain(error) + run.out.getvalue(), world.secrets())
    assert "accounts.google.com" not in run.out.getvalue()


# ---------------------------------------------------------------------------
# Events: nothing new (STOP and report "needs contract change" if the smoke emits an unregistered type)


def test_FR_CON_04_live_smoke_events_are_registered_fixtured_and_valid(world):
    world.seed_inbox(2)
    _, _, _, _, result = full_run(world, draft_to=DRAFT_TO)
    types = {p["type"] for p in result.events}
    assert {"connection.consented", "connection.established", "data.transfer"} <= types
    assert event_problems(result.events) == []
    consented = next(p for p in result.events if p["type"] == "connection.consented")
    assert consented["authz"]["by"] == "person"


def test_FR_CON_04_live_smoke_a_read_only_run_emits_no_transfer(world):
    world.seed_inbox(2)
    _, _, _, _, result = full_run(world)
    assert "data.transfer" not in {p["type"] for p in result.events}
    assert event_problems(result.events) == []


# ---------------------------------------------------------------------------
# The CLI (services/connectors/scripts/live_gmail_smoke.py)


def exit_code(main, argv, **options):
    try:
        return main(argv, **options)
    except SystemExit as stop:
        return stop.code


def test_FR_CON_04_live_smoke_cli_without_live_exits_nonzero_with_the_reason(world):
    out = io.StringIO()
    environ = {k: v for k, v in world.environ.items() if k != "LIVE"}
    code = script().main([], environ=environ, out=out)
    assert code not in (0, None)
    assert "LIVE=1" in out.getvalue() and "Traceback" not in out.getvalue()
    assert world.server.hits == [] and port_is_closed(world.callback_port)


@pytest.mark.parametrize(
    "argv", [["--send"], ["--send-to", DRAFT_TO], ["--draft"], ["--modify"], ["--draft", DRAFT_TO, "--send"]]
)
def test_FR_CON_04_live_smoke_cli_has_no_send_option_and_draft_needs_an_address(world, argv):
    code = exit_code(script().main, argv, environ=world.environ, out=io.StringIO(), callback_timeout_s=1)
    assert code not in (0, None)
    assert world.server.hits == []


def test_FR_CON_04_live_smoke_cli_success_exits_zero_and_creates_one_draft(world):
    world.seed_inbox(2)
    main = script().main

    def target(on_url, out):
        return main(
            ["--draft", DRAFT_TO],
            environ=world.environ,
            out=out,
            on_consent_url=on_url,
            endpoint_overrides=world.server.overrides(),
            allow_loopback_http=True,
            sleep=world.sleeps.append,
            store=world.store,
        )

    run = Running(target)
    approve(world, run)
    assert run.value() == 0
    assert len(world.server.draft_posts()) == 1 and world.server.sends() == []
    assert "Traceback" not in run.out.getvalue()


def test_FR_CON_04_live_smoke_cli_timeout_flag_and_failures_exit_nonzero_without_a_traceback(world, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    main = script().main

    def attempt(argv, react):
        def target(on_url, out):
            return main(
                argv,
                environ=world.environ,
                out=out,
                on_consent_url=on_url,
                endpoint_overrides=world.server.overrides(),
                allow_loopback_http=True,
                sleep=world.sleeps.append,
                store=world.store,
            )

        run = Running(target)
        react(run)
        return run

    timed_out = attempt(["--timeout", "0.5"], lambda run: None)
    assert timed_out.value() not in (0, None)

    denied = attempt([], lambda run: deny(world, run))
    assert denied.value() not in (0, None)

    for run in (timed_out, denied):
        text = run.out.getvalue()
        assert "Traceback" not in text and text.strip()
    assert not leaks(all_text(world, denied, caplog, capsys), world.secrets())
    assert world.server.gmail_hits() == [] and world.env.google.exchange_calls() == []


def _bare_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "LIVE" and not k.startswith("GOOGLE_OAUTH_")}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def test_FR_CON_04_live_smoke_script_run_directly_refuses_without_live():
    done = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        env=_bare_env(),
        stdin=subprocess.DEVNULL,
    )
    text = done.stdout + done.stderr
    assert done.returncode not in (0, None)
    assert "LIVE=1" in text and "Traceback" not in text


def test_FR_CON_04_live_smoke_script_help_offers_draft_and_no_send():
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        env=_bare_env(),
        stdin=subprocess.DEVNULL,
    )
    assert done.returncode == 0
    assert "--draft" in done.stdout and "--timeout" in done.stdout
    assert not re.search(r"--(send|modify|delete|reply)", done.stdout)


def _code_strings(path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]


def test_FR_CON_04_live_smoke_code_cannot_send_by_construction_and_the_script_stays_thin():
    live_path = REPO_ROOT / "services" / "connectors" / "src" / "tilo_connectors" / "live.py"
    for path in (live_path, SCRIPT):
        for text in _code_strings(path):
            assert not re.search(r"gmail\.send|gmail\.modify|mail\.google\.com|messages/send|drafts/send", text), text
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 120, "the script is a thin CLI over tilo_connectors.live.run_smoke"
    assert "tilo_connectors" in "\n".join(lines) and "__main__" in "\n".join(lines)
