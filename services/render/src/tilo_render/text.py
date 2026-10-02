"""Text helpers shared by the PPTX and PDF renderers (FR-CON-09, FR-CON-10). All deliverable text is untrusted."""

from pathlib import Path

from tilo_contracts import Manifest

PROVENANCE_HEADING = "Sources and provenance"


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


def provenance_lines(manifest: Manifest) -> list[str]:
    """Format a provenance manifest as plain sanitised lines (FR-CON-10; PRD 12.4, 13.3)."""
    prod = manifest.produced_by
    skill = f"{prod.skill.id} v{prod.skill.version}" if prod.skill else "none"
    sources = (
        [f"Source {s.id} ({s.kind}): {s.ref}" for s in manifest.sources] if manifest.sources else ["Sources: none"]
    )
    verified = sum(1 for c in manifest.claims if c.verified)
    status = "verified" if manifest.claims and verified == len(manifest.claims) else "unverified"
    approval = f"{manifest.authz.ref} ({manifest.authz.by}) at {manifest.authz.at}" if manifest.authz else "none"
    raw = [
        f"Agent: {prod.agent_id} ({prod.role})",
        f"Skill: {skill}",
        *sources,
        f"Verifier: {status} ({verified}/{len(manifest.claims)} claims verified)",
        f"Approval: {approval}",
    ]
    return [sanitize_text(item).replace("\n", " ") for item in raw]
