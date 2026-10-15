"""FR-CON-07 (run half): a page the person typed or attached as a link is fetchable; nothing else is added.

Before, `fetch_url` could only reach hosts that had appeared in search results, so a task that said "summarise
https://example.org/report" could not read its own page. The hosts now also come from the https URLs in the brief and
the person's answers, found by code (no model), and every fetch still goes through the egress policy, DNS pinning,
robots.txt and the SSRF guards: a typed URL to localhost, a private address, an internal name or plain http adds
nothing.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_RUN_FAIL_1_tool_unit_after_answer as rig
from tilo_api import deps
from tilo_api.web_tools import FetchTool, RunArchiveBridge, fetch_service, typed_hosts
from tilo_archive import LocalDirStore, RunArchive

HOST = "docs.example.org"
PAGE = b"<!doctype html><html><body><p>Hello from the typed page</p></body></html>"


def test_FR_CON_07_hosts_come_from_https_urls_in_text() -> None:
    texts = [
        "Summarise https://docs.example.org/report?x=1, then compare with (https://Other.Example.com/a/b).",
        "see HTTPS://UPPER.example.net/x.",
    ]
    assert typed_hosts(texts) == {"docs.example.org", "other.example.com", "upper.example.net"}


@pytest.mark.parametrize(
    "text",
    [
        "http://plain.example.org/a",  # https only
        "https://user:secret@creds.example.org/a",  # no userinfo
        "https://localhost/admin",
        "https://127.0.0.1/",
        "https://10.0.0.5/x",
        "https://[::1]/x",
        "https://metadata.google.internal/computeMetadata",
        "https://intranet/wiki",  # a bare name is not a public host
        "ftp://files.example.org/a",
        "javascript:alert(1) https://",
        "no urls here, only example.org",
    ],
)
def test_FR_CON_07_unsafe_or_non_https_urls_add_no_host(text: str) -> None:
    assert typed_hosts([text]) == set()


def test_FR_CON_07_the_number_of_typed_hosts_is_bounded() -> None:
    text = " ".join(f"https://h{n}.example.org/" for n in range(500))
    assert len(typed_hosts([text])) <= 20


def _recordings(root: Path) -> None:
    """The recorded DNS answer, robots.txt and page for one host, in the shape ReplayTransport reads."""
    dns, http = root / "dns", root / "http"
    dns.mkdir(parents=True)
    http.mkdir()
    address = "93.184.216.34"
    (dns / f"{hashlib.sha256(f'{HOST}:443'.encode()).hexdigest()}.json").write_text(
        json.dumps({"host": HOST, "port": 443, "addresses": [address]})
    )
    for path, status, body, kind in (("/robots.txt", 404, b"", "text/plain"), ("/report", 200, PAGE, "text/html")):
        url = f"https://{HOST}:443{path}"
        (http / f"{hashlib.sha256(url.encode()).hexdigest()}.json").write_text(
            json.dumps(
                {
                    "url": url,
                    "pinned_ip": address,
                    "status": status,
                    "headers": {"content-type": kind},
                    "body": base64.b64encode(body).decode(),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
        )


def _fetch_tool(tmp_path: Path, hosts: set[str]) -> FetchTool:
    _recordings(tmp_path / "fetch-recordings")
    run = SimpleNamespace(org_id=deps.ORG_ID, run_id=rig.RUN, scope=None, seams=None)
    archive = RunArchive(LocalDirStore(tmp_path / "archive"), org_id=deps.ORG_ID, run_id=rig.RUN, redactor=lambda v: v)
    service = fetch_service("replay", RunArchiveBridge(run, archive), tmp_path)
    unit = {"id": "U1", "district": "D1"}
    return FetchTool(run, service, hosts, unit, SimpleNamespace(agent_id="A_s0"), {})


def test_FR_CON_07_a_typed_host_is_fetched_and_an_unlisted_one_is_still_refused(tmp_path: Path) -> None:
    typed = typed_hosts([f"Summarise https://{HOST}/report"])
    allowed = _fetch_tool(tmp_path, typed)
    assert "Hello from the typed page" in allowed.run({"url": f"https://{HOST}/report"}).content

    refused = _fetch_tool(tmp_path / "again", set())  # a host nobody typed or searched
    with pytest.raises(Exception, match="(?i)allow|block|egress|refus"):
        refused.run({"url": f"https://{HOST}/report"})


def test_FR_CON_07_the_run_starts_with_the_hosts_of_the_brief_and_the_answers(tmp_path, monkeypatch) -> None:
    run, _state, _asking, _models = rig._run(tmp_path, monkeypatch, cap=40)
    run.brief = {
        **run.brief,
        "goal": "Plan the trip using https://www.karnataka-tourism.example.org/gokarna as a base",
        "sources": [{"kind": "url", "ref": "https://maps.example.net/route/1"}, {"kind": "web", "ref": "beaches"}],
    }
    run.intake_answers = (("Which map?", "The one at https://trips.example.com/plan"),)
    archive = run.seams.open_archive(org_id=deps.ORG_ID, run_id=rig.RUN)

    bound = run.seams.runner.bind_run(run, archive)

    assert bound.hosts == {"www.karnataka-tourism.example.org", "maps.example.net", "trips.example.com"}
