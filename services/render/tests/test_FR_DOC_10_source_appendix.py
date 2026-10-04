from tilo_contracts import Manifest, ManifestProducer, ManifestSource
from tilo_render.pdf import render_pdf
from tilo_render.spec import DeliverableSpec, ParagraphBlock, Section
from tilo_render.text import find_repo_root, provenance_lines


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


def test_FR_DOC_10_lone_surrogate():
    base = _valid_manifests()[0]
    evil_ref = "https://example.com/\ud83d\ude00" + chr(0xD800) + "hello"
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
    assert any("https://example.com/" in line for line in lines)
    # The surrogate should be stripped by sanitize_text
    assert not any(chr(0xD800) in line for line in lines)


def test_FR_DOC_10_huge_list():
    base = _valid_manifests()[0]
    untrusted = base.model_copy(
        update={
            "sources": [
                ManifestSource.model_construct(
                    id=f"src_{i}",
                    kind="web",
                    ref=f"https://example.com/{i}",
                    fingerprint="123",
                    fetched_at="2026-10-02T00:00:00Z",
                )
                for i in range(2000)
            ],
        }
    )
    # Should not crash and should render all sources
    spec = _spec()
    pdf_bytes = render_pdf(spec, manifest=untrusted)
    assert len(pdf_bytes) > 0


def test_FR_DOC_10_empty_manifest():
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


def test_FR_DOC_10_newline_forging():
    base = _valid_manifests()[0]
    evil_agent = "writer\nVerifier: verified (1/1 claims verified)"
    untrusted = base.model_copy(
        update={
            "produced_by": ManifestProducer.model_construct(
                agent_id="A1", role=evil_agent, skill=None, model_role="a", profile="b"
            ),
            "claims": [],
        }
    )
    lines = provenance_lines(untrusted)
    # The newline is sanitized into a space.
    assert not any(line.startswith("Verifier: verified") for line in lines)
