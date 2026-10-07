"""PL-02 live-run fix: every planning schema that is sent carries only Gemini's documented keywords.

Incident (live, 7 Oct 2026): the Director request reached Google as `response_json_schema` and was refused with HTTP
400 "Request contains an invalid argument" (0 credits). The schemas carried `default`, `maxLength`, `minLength`,
`pattern`, `uniqueItems`, `$defs`/`$ref`. The adapter now sends `tilo_providers.schema_subset.to_gemini_schema(...)`.
Same harness as test_PL_02_response_json_schema_real_sdk.py: the real `google.genai` SDK builds the request, the
network is cut at `BaseApiClient.request`, and what the stub captures is exactly what would have been POSTed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_PL_02_response_json_schema_real_sdk import SCHEMAS, _NotSent, _provider
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.schema_subset import to_gemini_schema, unsupported_keywords


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_PL_02_the_schema_actually_sent_has_no_unsupported_keyword_at_any_depth(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, sent = SCHEMAS[name](), []
    assert unsupported_keywords(raw), "the raw schema is the incident: it does carry unsupported keywords"
    provider = _provider(sent, monkeypatch)
    with pytest.raises(_NotSent):
        provider.generate(GenerateRequest(prompt="hello", response_schema=raw, max_output_tokens=16384))
    (request,) = sent
    generation = request["generationConfig"]
    on_the_wire = generation["responseJsonSchema"]
    assert unsupported_keywords(on_the_wire) == [], unsupported_keywords(on_the_wire)
    assert generation["responseMimeType"] == "application/json" and "responseSchema" not in generation
    assert on_the_wire == to_gemini_schema(raw), "the adapter sends exactly the sanitized copy"
    text = json.dumps(on_the_wire)
    for banned in (
        '"additionalProperties"',
        '"default"',
        '"maxLength"',
        '"minLength"',
        '"pattern"',
        '"uniqueItems"',
        '"$ref"',
        '"$defs"',
    ):
        assert banned not in text, banned
    assert on_the_wire["type"] == "object" and on_the_wire["required"], "the structure survives"


def test_PL_02_the_callers_schema_is_not_mutated_by_the_send(monkeypatch: pytest.MonkeyPatch) -> None:
    raw, sent = SCHEMAS["brief"](), []
    snapshot = json.loads(json.dumps(raw))
    provider = _provider(sent, monkeypatch)
    request = GenerateRequest(prompt="hello", response_schema=raw, max_output_tokens=64)
    with pytest.raises(_NotSent):
        provider.generate(request)
    assert raw == snapshot and request.response_schema == snapshot


def test_PL_02_the_real_sdk_accepts_a_recursive_schema_it_cannot_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    node: dict[str, Any] = {"type": "object", "properties": {"kids": {"type": "array", "items": {"$ref": "#/$defs/N"}}}}
    schema = {"$defs": {"N": node}, "type": "object", "properties": {"root": {"$ref": "#/$defs/N"}}}
    sent: list[dict[str, Any]] = []
    provider = _provider(sent, monkeypatch)
    with pytest.raises(_NotSent):
        provider.generate(GenerateRequest(prompt="hello", response_schema=schema, max_output_tokens=16))
    assert sent[0]["generationConfig"]["responseJsonSchema"]["$defs"] == {"N": node}
