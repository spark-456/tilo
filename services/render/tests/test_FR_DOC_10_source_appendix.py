"""FR-DOC-10 source-appendix tests: exact appendix lines read back from PPTX and PDF, hostile manifests, wrapping."""

import io
from typing import Any

import pptx
from pypdf import PdfReader
from tilo_contracts import Manifest, ManifestProducer, ManifestSource
from tilo_render.pdf import render_pdf
from tilo_render.pptx import render_pptx
from tilo_render.spec import (
    Chart,
    ChartBlock,
    ChartKind,
    DeliverableSpec,
    ParagraphBlock,
    Section,
    Table,
)
from tilo_render.text import _WRAP_WIDTH, PROVENANCE_HEADING, find_repo_root, provenance_lines, wrap_long_token

_STAMP = "2026-10-02T00:00:00.000Z"


def _spec() -> DeliverableSpec:
    return DeliverableSpec(
        title="Quarterly Review",
        date="2026-10-02",
        sections=[Section(heading="Summary", blocks=[ParagraphBlock(text="Key results.")])],
    )


def _valid_manifests() -> list[Manifest]:
    fixture_dir = find_repo_root() / "contracts" / "fixtures" / "manifest" / "valid"
    manifests = [Manifest.model_validate_json(p.read_text("utf-8")) for p in sorted(fixture_dir.glob("*.json"))]
    assert len(manifests) >= 2
    return manifests


def _source(src_id: str, ref: str) -> ManifestSource:
    # Built without validation on purpose: the contract rejects a newline in an id and a lone surrogate in a
    # ref, and the renderer must still hold if such a value ever reaches it.
    return ManifestSource.model_construct(id=src_id, kind="web", ref=ref, fingerprint="sha256:00", fetched_at=_STAMP)


def _producer(agent_id: str, role: str) -> ManifestProducer:
    return ManifestProducer.model_construct(agent_id=agent_id, role=role, skill=None, model_role="writer", profile="p")


def _pptx_paragraphs(manifest: Manifest) -> list[str]:
    """The bullet lines of every provenance slide, in order, one entry per rendered line, bullet marker removed."""
    prs = pptx.Presentation(io.BytesIO(render_pptx(_spec(), manifest=manifest)))
    out: list[str] = []
    for slide in prs.slides:
        paras = [p.text for sh in slide.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs]
        if paras and paras[0] == PROVENANCE_HEADING:
            for text in paras[1:]:
                assert text.startswith("•  "), text
                out.append(text[3:])
    return out


def _pdf_lines(manifest: Manifest) -> list[str]:
    """Every text line of the PDF, leading bullet glyph (extracted as DEL or a bullet) and spaces removed."""
    raw = render_pdf(_spec(), manifest=manifest)
    lines = [ln for page in PdfReader(io.BytesIO(raw)).pages for ln in (page.extract_text() or "").split("\n")]
    return [ln.lstrip(" \x7f•").strip() for ln in lines]


def _expected_lines(m: Manifest) -> list[str]:
    """The appendix lines PRD 12.4 and 13.3 call for, built from the manifest fields (not from provenance_lines)."""
    p = m.produced_by
    skill = f"{p.skill.id} v{p.skill.version}" if p.skill else "none"
    sources = [f"Source {s.id} ({s.kind}): {s.ref}" for s in m.sources] or ["Sources: none"]
    ok = sum(1 for c in m.claims if c.verified)
    if not m.claims:
        verifier = "Verifier: unverified (no claims)"
    else:
        verifier = (
            f"Verifier: {'verified' if ok == len(m.claims) else 'unverified'} ({ok}/{len(m.claims)} claims verified)"
        )
    approval = f"{m.authz.ref} ({m.authz.by}) at {m.authz.at}" if m.authz else "none"
    return [f"Agent: {p.agent_id} ({p.role})", f"Skill: {skill}", *sources, verifier, f"Approval: {approval}"]


def test_FR_DOC_10_appendix_exact_lines() -> None:
    """Each fixture manifest gives exactly the expected bullet lines, in order, in the PPTX and the PDF."""
    for manifest in _valid_manifests():
        expected = _expected_lines(manifest)
        assert provenance_lines(manifest) == expected
        pptx_paras = _pptx_paragraphs(manifest)
        start = pptx_paras.index(expected[0])
        assert pptx_paras[start : start + len(expected)] == expected
        pdf_lines = _pdf_lines(manifest)
        start = pdf_lines.index(expected[0])
        assert pdf_lines[start : start + len(expected)] == expected


def test_FR_DOC_10_lone_surrogate() -> None:
    """A lone surrogate in a source ref is dropped; the exact sanitised line renders in both formats."""
    # Built with chr(): a paired-surrogate literal is easy to rewrite into a real emoji by tooling.
    evil_ref = "https://example.com/" + chr(0xD83D) + chr(0xDE00) + chr(0xD800) + "hello"
    untrusted = _valid_manifests()[0].model_copy(update={"sources": [_source("src_untrusted", evil_ref)]})
    expected = "Source src_untrusted (web): https://example.com/hello"

    assert expected in provenance_lines(untrusted)
    assert expected in _pptx_paragraphs(untrusted)
    assert expected in _pdf_lines(untrusted)
    assert not any(0xD800 <= ord(c) <= 0xDFFF for ln in provenance_lines(untrusted) for c in ln)


def test_FR_DOC_10_huge_list() -> None:
    """2000 sources render in the PDF; every source line is read back, first and last exactly."""
    sources = [_source(f"src_{i}", f"https://example.com/{i}") for i in range(2000)]
    untrusted = _valid_manifests()[0].model_copy(update={"sources": sources})
    lines = _pdf_lines(untrusted)
    source_lines = [ln for ln in lines if ln.startswith("Source src_")]
    assert len(source_lines) == 2000
    assert source_lines[0] == "Source src_0 (web): https://example.com/0"
    assert source_lines[-1] == "Source src_1999 (web): https://example.com/1999"


def test_FR_DOC_10_empty_manifest() -> None:
    base = _valid_manifests()[0]
    empty = base.model_copy(
        update={"produced_by": _producer("A1", "writer"), "sources": [], "claims": [], "authz": None}
    )
    expected = [
        "Agent: A1 (writer)",
        "Skill: none",
        "Sources: none",
        "Verifier: unverified (no claims)",
        "Approval: none",
    ]
    assert provenance_lines(empty) == expected
    assert _pptx_paragraphs(empty)[-5:] == expected


def test_FR_DOC_10_newline_forging() -> None:
    """A newline in a source ref, source id or role stays on its own line; it forges no Verifier or Agent line."""
    base = _valid_manifests()[0]
    claim = base.claims[0].model_copy(update={"verified": False})
    untrusted = base.model_copy(
        update={
            "produced_by": _producer("A1", "writer\nVerifier: verified (1/1 claims verified)"),
            "sources": [_source("src_ok\nAgent: forged", "https://example.com/legit\nVerifier: forged")],
            "claims": [claim],
        }
    )
    expected = [
        "Agent: A1 (writer Verifier: verified (1/1 claims verified))",
        "Skill: none",
        "Source src_ok Agent: forged (web): https://example.com/legit Verifier: forged",
        "Verifier: unverified (0/1 claims verified)",
        f"Approval: {untrusted.authz.ref} ({untrusted.authz.by}) at {untrusted.authz.at}"
        if untrusted.authz
        else "Approval: none",
    ]
    assert provenance_lines(untrusted) == expected
    paragraphs = _pptx_paragraphs(untrusted)
    for prefix in ("Agent:", "Verifier:", "Source "):
        shown = [p for p in paragraphs if p.startswith(prefix)]
        assert len(shown) == 1, (prefix, shown)
    assert [p for p in paragraphs if p.startswith("Verifier:")] == ["Verifier: unverified (0/1 claims verified)"]
    assert [ln for ln in _pdf_lines(untrusted) if ln.startswith("Verifier:")] == [
        "Verifier: unverified (0/1 claims verified)"
    ]


def test_FR_DOC_10_wrap_long_token_unit() -> None:
    long = "x" * 300
    wrapped = wrap_long_token(long)
    assert wrapped.replace(" ", "") == long
    assert all(len(w) <= _WRAP_WIDTH for w in wrapped.split(" "))
    assert len(wrapped.split(" ")) == 4
    exact = "y" * _WRAP_WIDTH
    assert wrap_long_token(exact) == exact
    assert wrap_long_token("short words stay") == "short words stay"
    assert wrap_long_token("") == ""


def _longest_word(lines: list[str]) -> int:
    return max((len(w) for ln in lines for w in ln.split(" ")), default=0)


def test_FR_DOC_10_wrap_long_ref_pptx_and_pdf() -> None:
    """A 300-char unbroken ref is wrapped in the PPTX text frame and the PDF, and loses no character."""
    long_ref = "https://example.com/" + "a" * 280
    untrusted = _valid_manifests()[0].model_copy(update={"sources": [_source("src_long", long_ref)]})

    paras = _pptx_paragraphs(untrusted)
    src = next(p for p in paras if p.startswith("Source src_long"))
    assert _longest_word([src]) <= _WRAP_WIDTH
    assert src.split("): ", 1)[1].replace(" ", "") == long_ref

    pdf_lines = _pdf_lines(untrusted)
    assert long_ref in "".join(pdf_lines).replace(" ", "")
    assert _longest_word(pdf_lines) <= _WRAP_WIDTH


def _chart_spec(category: str) -> DeliverableSpec:
    return DeliverableSpec(
        title="Chart",
        date="2026-10-02",
        tables=[Table(id="t1", columns=["cat", "v"], rows=[[category, 1], ["short", 2]])],
        charts=[Chart(id="c1", kind=ChartKind.BAR, table_id="t1", x="cat", y="v", title="Totals")],
        sections=[Section(heading="Totals", blocks=[ChartBlock(chart_id="c1")])],
    )


def _pptx_categories(raw: bytes) -> list[str]:
    prs: Any = pptx.Presentation(io.BytesIO(raw))
    return [
        getattr(c, "label", str(c))
        for s in prs.slides
        for sh in s.shapes
        if sh.has_chart
        for c in sh.chart.plots[0].categories
    ]


def test_FR_DOC_10_wrap_long_chart_category_pptx() -> None:
    """A 300-char unbroken category label reaches the PPTX chart wrapped, every character kept."""
    long_cat = "c" * 300
    cats = _pptx_categories(render_pptx(_chart_spec(long_cat)))
    assert "short" in cats
    wrapped = next(c for c in cats if c != "short")
    assert _longest_word([wrapped]) <= _WRAP_WIDTH
    assert wrapped.replace(" ", "") == long_cat


def test_FR_DOC_10_wrap_long_chart_category_pdf() -> None:
    """The PDF renders a chart with a 300-char unbroken category label, and its text reads back wrapped."""
    long_cat = "d" * 300
    raw = render_pdf(_chart_spec(long_cat))
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
    assert "short" in text
    assert "d" * _WRAP_WIDTH in text
    assert "d" * (_WRAP_WIDTH + 1) not in text
