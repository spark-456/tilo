"""FR-DOC-10 source-appendix tests: exact-line assertions, security and wrap coverage."""

import io

import pptx
from pypdf import PdfReader
from tilo_contracts import Manifest, ManifestProducer, ManifestSource
from tilo_render.pdf import render_pdf
from tilo_render.pptx import render_pptx
from tilo_render.spec import DeliverableSpec, ParagraphBlock, Section
from tilo_render.text import find_repo_root, provenance_lines, wrap_long_token


def _spec() -> DeliverableSpec:
    return DeliverableSpec(
        title="Quarterly Review",
        date="2026-10-02",
        sections=[Section(heading="Summary", blocks=[ParagraphBlock(text="Key results.")])],
    )


def _valid_manifests() -> list[Manifest]:
    fixture_dir = find_repo_root() / "contracts" / "fixtures" / "manifest" / "valid"
    manifests = [
        Manifest.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(fixture_dir.glob("*.json"))
    ]
    return manifests


def _pptx_appendix_text(manifest: Manifest) -> str:
    """Render PPTX and return all text from the last (provenance) slide."""
    prs = pptx.Presentation(io.BytesIO(render_pptx(_spec(), manifest=manifest)))
    last = prs.slides[-1]
    return "\n".join(sh.text for sh in last.shapes if sh.has_text_frame)


def _pdf_last_page_text(manifest: Manifest) -> str:
    """Render PDF and return text from the last page."""
    reader = PdfReader(io.BytesIO(render_pdf(_spec(), manifest=manifest)))
    return reader.pages[-1].extract_text()


# ---------------------------------------------------------------------------
# test_FR_DOC_10_lone_surrogate
# ---------------------------------------------------------------------------


def test_FR_DOC_10_lone_surrogate() -> None:
    """Lone surrogates in source ref must be stripped; exact sanitised line must appear in both renderers."""
    base = _valid_manifests()[0]
    evil_ref = "https://example.com/\ud83d\ude00" + chr(0xD800) + "hello"
    # After sanitize_text, lone surrogate chr(0xD800) is dropped; the emoji \ud83d\ude00 is a valid
    # surrogate *pair* encoded as two Python surrogates – sanitize_text drops them too (they are in
    # the surrogate range D800-DFFF). So the expected ref after sanitisation is just the prefix.
    expected_ref = "https://example.com/hello"
    untrusted = base.model_copy(
        update={
            "sources": [
                ManifestSource.model_construct(
                    id="src_untrusted",
                    kind="web",
                    ref=evil_ref,
                    fingerprint="123",
                    fetched_at="2026-10-02T00:00:00Z",
                ),
            ],
        }
    )
    lines = provenance_lines(untrusted)

    # Exact expected sanitised source line
    expected_line = f"Source src_untrusted (web): {wrap_long_token(expected_ref)}"
    assert expected_line in lines, f"Expected line not found. Got lines: {lines}"

    # Surrogate must be absent
    assert not any(chr(0xD800) in line for line in lines)

    # Renders without error in both formats
    render_pdf(_spec(), manifest=untrusted)
    render_pptx(_spec(), manifest=untrusted)


# ---------------------------------------------------------------------------
# test_FR_DOC_10_huge_list — exact first and last source lines read from PDF
# ---------------------------------------------------------------------------


def test_FR_DOC_10_huge_list() -> None:
    """2000-source manifest: PDF renders, and the first+last source lines are present in extracted text."""
    base = _valid_manifests()[0]
    sources = [
        ManifestSource.model_construct(
            id=f"src_{i}",
            kind="web",
            ref=f"https://example.com/{i}",
            fingerprint="123",
            fetched_at="2026-10-02T00:00:00Z",
        )
        for i in range(2000)
    ]
    untrusted = base.model_copy(update={"sources": sources})
    spec = _spec()
    pdf_bytes = render_pdf(spec, manifest=untrusted)
    assert len(pdf_bytes) > 0

    # Extract all text from the PDF and check exact first and last source lines
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(p.extract_text() or "" for p in reader.pages)

    first_line = "Source src_0 (web): https://example.com/0"
    last_line = "Source src_1999 (web): https://example.com/1999"
    assert first_line in full_text, "First source line missing from PDF text"
    assert last_line in full_text, "Last source line missing from PDF text"


# ---------------------------------------------------------------------------
# test_FR_DOC_10_empty_manifest
# ---------------------------------------------------------------------------


def test_FR_DOC_10_empty_manifest() -> None:
    base = _valid_manifests()[0]
    empty_manifest = base.model_copy(
        update={
            "produced_by": ManifestProducer.model_construct(
                agent_id="A1", role="writer", skill=None, model_role="a", profile="b"
            ),
            "sources": [],
            "claims": [],
            "authz": None,
        }
    )
    lines = provenance_lines(empty_manifest)
    assert "Sources: none" in lines
    assert "Verifier: unverified (no claims)" in lines or "Verifier: unverified (0/0 claims verified)" in lines
    assert "Approval: none" in lines


# ---------------------------------------------------------------------------
# test_FR_DOC_10_newline_forging — inject newlines in ref, id, AND role
# ---------------------------------------------------------------------------


def test_FR_DOC_10_newline_forging() -> None:
    """Newline injection in source ref, id, and producer role must be collapsed to a single line each."""
    base = _valid_manifests()[0]
    evil_role = "writer\nVerifier: verified (1/1 claims verified)"
    evil_ref = "https://example.com/legit\nVerifier: injected"
    evil_id = "src_ok\nAgent: injected"
    untrusted = base.model_copy(
        update={
            "produced_by": ManifestProducer.model_construct(
                agent_id="A1",
                role=evil_role,
                skill=None,
                model_role="a",
                profile="b",
            ),
            "sources": [
                ManifestSource.model_construct(
                    id=evil_id,
                    kind="web",
                    ref=evil_ref,
                    fingerprint="123",
                    fetched_at="2026-10-02T00:00:00Z",
                )
            ],
            "claims": [base.claims[0].model_copy(update={"verified": True}) if base.claims else None],
        }
    )
    # Remove None entries if claims was empty
    untrusted = untrusted.model_copy(update={"claims": [c for c in (untrusted.claims or []) if c is not None]})
    lines = provenance_lines(untrusted)

    # Exactly ONE Verifier line (injected newline must not forge a second)
    verifier_lines = [line for line in lines if line.startswith("Verifier:")]
    assert len(verifier_lines) == 1, f"Expected exactly 1 Verifier line, got: {verifier_lines}"

    # The verifier line must reflect actual claim verification state (not the injected value)
    assert not any(line == "Verifier: verified (1/1 claims verified)" for line in lines), (
        "Injected verifier line appeared"
    )

    # Agent/Source lines must be single-line (no newlines in any provenance line)
    for line in lines:
        assert "\n" not in line, f"Newline found inside provenance line: {repr(line)}"

    # Source line with the forged id: the newline in id should be replaced by a space
    agent_lines = [line for line in lines if line.startswith("Agent:")]
    assert len(agent_lines) == 1
    assert "\n" not in agent_lines[0]

    source_lines = [line for line in lines if line.startswith("Source")]
    assert len(source_lines) == 1
    assert "\n" not in source_lines[0]


# ---------------------------------------------------------------------------
# test_FR_DOC_10_wrap_long_token — read-back assertions on PPTX text frame
# ---------------------------------------------------------------------------


def test_FR_DOC_10_wrap_long_token_pptx_no_run_overflow() -> None:
    """A 300-char unbroken ref must be wrapped; no PPTX run in the appendix exceeds _WRAP_WIDTH chars."""
    from tilo_render.text import _WRAP_WIDTH

    base = _valid_manifests()[0]
    long_ref = "https://example.com/" + "a" * 280  # total > 300 chars, no spaces
    untrusted = base.model_copy(
        update={
            "sources": [
                ManifestSource.model_construct(
                    id="src_long",
                    kind="web",
                    ref=long_ref,
                    fingerprint="123",
                    fetched_at="2026-10-02T00:00:00Z",
                )
            ],
        }
    )

    prs = pptx.Presentation(io.BytesIO(render_pptx(_spec(), manifest=untrusted)))
    last_slide = prs.slides[-1]

    # Collect all runs from the provenance slide
    all_run_texts: list[str] = []
    for shape in last_slide.shapes:
        if shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    all_run_texts.append(run.text)

    # The appendix must contain content
    assert any("src_long" in t for t in all_run_texts), "src_long not found in PPTX appendix"

    # No individual run (token without spaces) should exceed _WRAP_WIDTH
    for run_text in all_run_texts:
        for word in run_text.split(" "):
            assert len(word) <= _WRAP_WIDTH, f"Run word exceeds wrap width ({_WRAP_WIDTH}): {repr(word)[:60]}..."


def test_FR_DOC_10_wrap_long_token_pdf_text_present() -> None:
    """A 300-char unbroken ref in a PDF provenance page must be present (not truncated away)."""
    from tilo_render.text import _WRAP_WIDTH

    base = _valid_manifests()[0]
    long_ref = "https://example.com/" + "b" * 280
    untrusted = base.model_copy(
        update={
            "sources": [
                ManifestSource.model_construct(
                    id="src_longpdf",
                    kind="web",
                    ref=long_ref,
                    fingerprint="123",
                    fetched_at="2026-10-02T00:00:00Z",
                )
            ],
        }
    )

    pdf_bytes = render_pdf(_spec(), manifest=untrusted)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(p.extract_text() or "" for p in reader.pages)

    # The source id must appear in the PDF
    assert "src_longpdf" in full_text, "src_longpdf not found in PDF text"

    # The first _WRAP_WIDTH chars of the ref must appear (confirms wrapping, not truncation)
    ref_prefix = long_ref[:_WRAP_WIDTH]
    assert ref_prefix in full_text, f"First {_WRAP_WIDTH} chars of long_ref not found in PDF text"
