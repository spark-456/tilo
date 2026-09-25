"""tilo_providers.prompts — prompt template loader (PL-04, PRD 6.4). Layout:
prompts/<role>/<template>.md, with an optional per-provider override
prompts/<role>/<template-stem>.<provider>.md taking precedence when given
and present. Substitution is stdlib string.Template's $name / ${name}
placeholders (simple, safe — no eval), filled in strictly: a variable the
template needs but the caller omitted raises, rather than shipping an
unfilled placeholder."""

from __future__ import annotations

import string
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# packages/providers/src/tilo_providers/prompts.py -> repo root is 4 parents up.
DEFAULT_PROMPTS_ROOT = Path(__file__).resolve().parents[4] / "prompts"


class PromptNotFoundError(FileNotFoundError):
    """No base template (or requested override) exists for a role/template/provider combination."""


def _override_filename(template: str, provider: str) -> str:
    path = Path(template)
    return f"{path.stem}.{provider}{path.suffix}"


def load_prompt(
    role: str,
    template: str,
    variables: Mapping[str, Any] | None = None,
    *,
    provider: str | None = None,
    prompts_root: Path | str | None = None,
) -> str:
    """Renders prompts/<role>/<template>, substituting variables; uses the
    per-provider override when provider is given and it exists."""
    root = Path(prompts_root) if prompts_root is not None else DEFAULT_PROMPTS_ROOT
    role_dir = root / role

    candidates = [role_dir / _override_filename(template, provider)] if provider else []
    candidates.append(role_dir / template)

    for candidate in candidates:
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8")
            return string.Template(text).substitute(**(variables or {}))

    raise PromptNotFoundError(
        f"no prompt template for role={role!r} template={template!r} provider={provider!r} under {root}"
    )
