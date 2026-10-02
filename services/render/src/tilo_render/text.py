"""Text helpers shared by the PPTX and PDF renderers (FR-CON-09). All deliverable text is untrusted."""

from pathlib import Path


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
