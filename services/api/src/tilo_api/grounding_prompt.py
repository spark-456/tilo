"""R2 / RT-04: the nearest passages as the two calls of MI-05 see them, and as an answer shows them (ADR-0049).

`prompt_block` is the `retrieval_chunk.prompt_block` data (at most 5, nearest first); `render` fences it as untrusted
data in the USER turn through a static template (EFF-04: the system prompts never change); `grounded_on` is what a
Quick answer lists (`grounding_ref`: source and label, never the text). With no passages `render` is the empty string,
so the prompt is byte-identical to before. `recall` never raises: a failed search is an ask without grounding (RT-06).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from tilo_memory.chunks import Hit, clean_label, clean_text
from tilo_providers.prompts import load_prompt, neutralise_marker

from tilo_api import deps

logger = logging.getLogger("tilo_api.grounding")
MARKER = "PASSAGES"
MAX_PASSAGES = 5
MAX_QUERY_CHARS = 2000
RECALL_TIMEOUT_S = 3.0  # retrieval never costs an ask more than this (it must not cause intake_deadline)
MAX_TEXT_CHARS = 1200  # a passage in a prompt is re-bounded here whatever the store handed over
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="recall")


def eligible(principal: deps.Principal) -> bool:
    """RT-04: only a signed-in person's own web or mobile-web ask, never a demo session or any other channel."""
    return deps.full_world_session(principal)


def prompt_block(hits: Sequence[Hit]) -> dict[str, Any]:
    chunks = [{"id": h.id, "source": h.source, "label": h.label, "text": h.text} for h in hits[:MAX_PASSAGES]]
    return {"v": "1.0", "chunks": chunks}


def grounded_on(hits: Sequence[Hit]) -> list[dict[str, Any]]:
    return [{"source": h.source, "label": h.label} for h in hits[:MAX_PASSAGES]]


def render(hits: Sequence[Hit], role: str, template: str) -> str:
    """The fenced block to append to a user turn, or "" with no passages. Each label and text is neutralised so a
    passage can never close the block; the numbers are what an answer can point back to."""
    block = [
        {**c, "label": clean_label(c["label"]), "text": clean_text(c["text"])[:MAX_TEXT_CHARS]}
        for c in prompt_block(hits)["chunks"]
    ]  # re-bounded and re-cleaned: nothing a store returns is trusted to be short or plain
    block = [c for c in block if c["text"]]
    if not block:
        return ""
    body = "\n\n".join(
        f"[{n}] (id {c['id']}) {neutralise_marker(c['label'], MARKER)}\n{neutralise_marker(c['text'], MARKER)}"
        for n, c in enumerate(block, 1)
    )
    return "\n\n" + load_prompt(role, template, {"passages": body})


def recall(opened: Any, uid: str, query: str) -> list[Hit]:
    """The caller's nearest readable passages for `query`; [] when grounding is off, none exist, or anything fails."""
    if opened is None:
        return []
    try:
        search = _POOL.submit(opened.store.search, deps.ORG_ID, uid, query[:MAX_QUERY_CHARS], k=MAX_PASSAGES)
        return list(search.result(timeout=RECALL_TIMEOUT_S))
    except FutureTimeout:
        logger.warning("retrieval skipped (timeout)")  # the thread finishes on its own; its result is dropped
        return []
    except Exception as exc:  # the ask goes on without grounding; the failure is named by type only
        logger.warning("retrieval skipped (%s)", type(exc).__name__)
        return []
