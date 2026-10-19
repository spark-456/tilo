"""Read-only, deterministic browser proposals for the local demo profile."""

from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse

_WIKIPEDIA_SEARCH = re.compile(
    r"Search\s+https://en\.wikipedia\.org(?:/\S*)?\s+for\s+(.+?)\s+and\s+summari[sz]e\b", re.I
)
_HISTORY = re.compile(r"Completed browser actions:[ \t]*([^\n]*)", re.I)


class FakeBrowserProvider(FakeModelProvider):
    """A fixed Wikipedia search path and a generic read path; no click, submit or typing."""

    def __init__(self, profile_id: str = "computer-fake") -> None:
        super().__init__(profile_id=profile_id, caps={Capability.JSON, Capability.VISION, Capability.COMPUTER_USE})

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        prompt = request.prompt
        recorded = _HISTORY.search(prompt)
        history = (recorded.group(1) if recorded else "").strip().lower()
        if "extract" in history:
            action = {"kind": "done"}
        elif "navigate" in history:
            action = {"kind": "extract"}
        elif match := _WIKIPEDIA_SEARCH.search(prompt):
            action = {
                "kind": "navigate",
                "url": "https://en.wikipedia.org/wiki/Special:Search?search=" + quote_plus(match.group(1).strip()),
            }
        else:
            action = {"kind": "extract"}
        return GenerateResponse(text=json.dumps(action), profile_id=self._profile_id, usage=None)
