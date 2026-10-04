"""Text helpers shared by the PPTX and PDF renderers (FR-CON-09, FR-CON-10). All deliverable text is untrusted."""

from pathlib import Path

from tilo_contracts import Manifest

PROVENANCE_HEADING = "Sources and provenance"

# Maximum characters in one unbroken token before we insert a soft wrap opportunity.
# PPTX textboxes are ~11.3 in wide at body size, ≈90 chars at 14 pt Helvetica.
_WRAP_WIDTH = 80


def find_repo_root() -> Path:
    cur = Path(__file__).resolve()
    return next((p for p in [cur, *cur.parents] if (p / "design" / "tokens.json").exists()), Path.cwd())


def sanitize_text(text: str) -> str:
    """Normalise CR/CRLF to LF and drop XML-invalid characters (C0/C1 controls, surrogates, U+FFFE/U+FFFF)."""
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        c
        for c in norm
        if c in "\t\n"
        or (
            32 <= ord(c) != 127
            and not (0x80 <= ord(c) <= 0x9F)
            and not (0xD800 <= ord(c) <= 0xDFFF)
            and ord(c) not in (0xFFFE, 0xFFFF)
        )
    )


def lines(text: str) -> list[str]:
    """Sanitise (XML-invalid characters, CR normalisation) and split into one string per line."""
    return sanitize_text(text).split("\n")


def wrap_long_token(text: str, width: int = _WRAP_WIDTH) -> str:
    """Break any run of non-space characters longer than *width* with a space.

    Used to prevent very long unbroken refs (e.g. URLs) from overflowing PPTX
    text-boxes or PDF chart labels.  Only plain-text is produced — no markup.
    """
    result: list[str] = []
    for word in text.split(" "):
        if len(word) <= width:
            result.append(word)
        else:
            # Chunk the word at *width* boundaries.
            chunks = [word[i : i + width] for i in range(0, len(word), width)]
            result.append(" ".join(chunks))
    return " ".join(result)


def provenance_lines(manifest: Manifest) -> list[str]:
    """Format a provenance manifest as plain sanitised lines (FR-CON-10; PRD 12.4, 13.3)."""
    prod = manifest.produced_by
    skill = f"{prod.skill.id} v{prod.skill.version}" if prod.skill else "none"
    sources = (
        [f"Source {s.id} ({s.kind}): {wrap_long_token(s.ref)}" for s in manifest.sources]
        if manifest.sources
        else ["Sources: none"]
    )
    verified = sum(1 for c in manifest.claims if c.verified)
    n = len(manifest.claims)
    if not manifest.claims:
        verifier_line = "Verifier: unverified (no claims)"
    elif verified == n:
        verifier_line = f"Verifier: verified ({verified}/{n} claims verified)"
    else:
        verifier_line = f"Verifier: unverified ({verified}/{n} claims verified)"
    approval = f"{manifest.authz.ref} ({manifest.authz.by}) at {manifest.authz.at}" if manifest.authz else "none"
    raw = [
        f"Agent: {prod.agent_id} ({prod.role})",
        f"Skill: {skill}",
        *sources,
        verifier_line,
        f"Approval: {approval}",
    ]
    return [sanitize_text(item).replace("\n", " ") for item in raw]
