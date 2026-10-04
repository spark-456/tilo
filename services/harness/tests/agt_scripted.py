"""Scripted, offline model providers for the FR-AGT-05 / FR-AGT-12 acceptance tests (CP3-T3).

Not a test module (no `test_` prefix). Record-and-replay in spirit (EFF-01, PRD 6.6): every reply
is fixed data in the test, keyed by text that appears in the prompt, so the same prompt always
yields the same answer, no network is touched and nothing is paid for. A prompt that matches no
script is NOT answered silently: it is recorded in `misses`, and each test asserts `misses == []`
so a harness that sends something unexpected cannot pass by accident.

`ScriptedProvider` is a real `ModelProvider` (a `FakeModelProvider` subclass), so anything that
checks `isinstance(x, ModelProvider)` still holds. Replies are looked up by the longest script key
that is a substring of the request prompt.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse


class ScriptedProvider(FakeModelProvider):
    """`replies`: prompt substring -> reply text, or an Exception instance to raise instead (a
    provider outage or timeout). `default`: reply for prompts matching no key; None records a miss
    and replies with an empty string (which no parser accepts as a valid answer)."""

    def __init__(
        self,
        replies: Mapping[str, str | Exception] | None = None,
        *,
        default: str | None = None,
        profile_id: str = "scripted",
    ) -> None:
        super().__init__(profile_id=profile_id)
        self._replies = dict(replies or {})
        self._default = default
        self.prompts: list[str] = []
        self.requests: list[GenerateRequest] = []
        self.misses: list[str] = []

    @property
    def call_count(self) -> int:
        return len(self.prompts)

    def _lookup(self, request: GenerateRequest) -> str | Exception:
        haystack = f"{request.system or ''}\n{request.prompt}"
        keys = [key for key in self._replies if key in haystack]
        if keys:
            return self._replies[max(keys, key=len)]
        if self._default is not None:
            return self._default
        self.misses.append(request.prompt)
        return ""

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.prompts.append(f"{request.system or ''}\n{request.prompt}")
        self.requests.append(request)
        reply = self._lookup(request)
        if isinstance(reply, Exception):
            raise reply
        return GenerateResponse(text=reply, profile_id=self._profile_id)


def all_prompt_text(*providers: ScriptedProvider) -> str:
    """Every system + user prompt the given providers received, joined (for 'never contains' checks)."""
    return "\n".join(prompt for provider in providers for prompt in provider.prompts)


def role_providers(**scripted: Any) -> dict[str, Any]:
    """A `Mapping[str, ModelProvider]` keyed by role (the shape `DefaultUnitRunner` already takes),
    with a fresh unscripted `ScriptedProvider` for every role not given. An unscripted role that is
    ever called records a miss, so a test can assert a role was never used."""
    roles = ("director", "lead", "specialist", "verifier", "writer", "narrator")
    return {role: scripted.get(role) or ScriptedProvider(profile_id=f"scripted-{role}") for role in roles}
