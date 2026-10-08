"""PL-02 follow-up 3: the EXACT Director request of `just live-run`, captured offline, checked field by field.

Incident (7 Oct 2026, after #580 and #593): the user's live run still ends "rejected: the provider rejected a request
of the director role: Request contains an invalid argument." (HTTP 400, 0 credits; Model Armor passed the topic).
Here the brief request is built through the REAL code path: `live_topic.run_topic` -> the intake route ->
`tilo_planning.brief` -> the Router -> `GoogleModelProvider` -> the real `google.genai` SDK, with the network cut at
the one place the SDK sends from (`BaseApiClient.request`, a stub that records `request_dict` and raises). No
credentials (AnonymousCredentials), no network, no paid call; the live switch is set only in a patched environment.

The captured body is written REDACTED (prompt and task text replaced by a length marker) to
`evals/bank/live/adhoc/pl02-director-request.redacted.json` (git-ignored), and checked against Vertex AI's documented
rules in `SUSPECTS`: every fact in the table must hold on the captured request, and every field the docs do not
clearly allow has a `just vertex-probe-schema` variant that removes it, so one cheap live run pins the 400.

Sources (read 2026-10-07):
- Vertex `GenerationConfig.response_json_schema` (proto comments behind the REST reference):
  https://raw.githubusercontent.com/googleapis/googleapis/master/google/cloud/aiplatform/v1/content.proto
  "If set, `response_schema` must be omitted, but `response_mime_type` is required." Supported: `$id`, `$defs`, `$ref`,
  `$anchor`, `type`, `format`, `title`, `description`, `enum` (strings and numbers), `items`, `prefixItems`,
  `minItems`, `maxItems`, `minimum`, `maximum`, `anyOf`, `oneOf`, `properties`, `additionalProperties`, `required`,
  plus `propertyOrdering`. Silent on an untyped `{}` schema and on the values of `type` (no "null" named).
  `Content.role`: "Must be either 'user' or 'model'."
- Vertex structured output (https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output):
  a complex schema "can result in an InvalidArgument: 400 error": long property names, long array length limits, enums
  with many values, many optional properties. No numeric limit is published.
- Gemini API structured output (ai.google.dev, structured-output page): "null" is a supported type
  ("include "null" in the type array"); "Very large or deeply nested schemas may be rejected."
- Model (ai.google.dev, the Director model page): output limit 65,536 tokens; structured
  outputs and thinking supported; thinking level "minimal is not supported and returns an error".
- Thinking (ai.google.dev, thinking page): `max_output_tokens` includes thought tokens (a cap hit is
  MAX_TOKENS, not a 400); thinking is dynamic by default when no thinking config is sent.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import socket
from collections.abc import Callable, Iterator
from typing import Any

import _live_e2e_lib as lib
import pytest
from _live_e2e_lib import network_guard  # noqa: F401  (autouse fixture)
from google import genai
from google.auth.credentials import AnonymousCredentials
from google.genai import _api_client
from google.genai import errors as genai_errors
from tilo_evals import live_topic
from tilo_planning import brief
from tilo_providers import schema_probe
from tilo_providers.config import load_providers_config
from tilo_providers.google_adapter import GoogleModelProvider
from tilo_providers.safety import FakeSafetyProvider
from tilo_providers.schema_subset import complexity, to_gemini_schema

TOPIC = "Plan a two-day offsite for a team of twelve, with an agenda and a budget sheet."  # synthetic
DUMP = live_topic.ADHOC / "pl02-director-request.redacted.json"  # git-ignored (.gitignore: evals/bank/live/adhoc/)
MODEL_MAX_OUTPUT = 65_536  # the Director model output limit, ai.google.dev model page (read 2026-10-07)
ROLE_CAP = 16_384  # config/models.yaml director max_output_tokens


def _bad_request() -> Exception:
    """What Google answered the live run: HTTP 400, raised by the stub after it recorded the request."""
    message = {"error": {"code": 400, "message": "Request contains an invalid argument.", "status": "INVALID_ARGUMENT"}}
    return genai_errors.ClientError(400, message)


def _client() -> Any:
    return genai.Client(vertexai=True, project=lib.PROJECT, location="global", credentials=AnonymousCredentials())


@contextlib.contextmanager
def _cut(raise_: Callable[[], Exception]) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    """The SDK's transport replaced by a recorder; every other host refused (as `network_guard` does per test)."""
    sent: list[tuple[str, dict[str, Any]]] = []

    def stub(self: object, http_method: str, path: str, request_dict: dict[str, Any], *_a: Any, **_k: Any) -> None:
        sent.append((path, copy.deepcopy(request_dict)))
        raise raise_()

    real_connect = socket.socket.connect

    def connect(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):  # the event loop's own socket pair stays allowed
            raise RuntimeError(f"PL_02 capture must not connect to {host!r}")
        return real_connect(self, address)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(_api_client.BaseApiClient, "request", stub)
        patch.setattr(socket.socket, "connect", connect)
        yield sent


def _wire(body: dict[str, Any]) -> dict[str, Any]:
    """The body as sent: the SDK's routing keys (`_url`, `_query`) are path parts, not body fields."""
    return {k: v for k, v in body.items() if not k.startswith("_")}


def redacted(body: dict[str, Any]) -> dict[str, Any]:
    """Prompt and task text replaced by a length marker; the schema and config (Tilo's own code) are kept."""
    out = _wire(copy.deepcopy(body))
    for content in [out.get("systemInstruction"), *out.get("contents", [])]:
        for part in (content or {}).get("parts", []):
            if "text" in part:
                part["text"] = f"<redacted: {len(part['text'])} chars>"
    return out


@pytest.fixture(scope="module")
def captured() -> dict[str, Any]:
    """The first generateContent body of a `just live-run` on TOPIC, through the real pipeline and the real SDK."""
    config = load_providers_config(lib.REAL_MODELS, lib.REAL_PRICES)

    def factory(_role: str, profile_id: str) -> GoogleModelProvider:
        return GoogleModelProvider(config.profiles[profile_id], profile_id, lib.PROJECT, "global", client=_client())

    def closed(_prompt: str) -> str:
        raise EOFError

    person = live_topic.TerminalPerson(auto_answer=True, read=closed, write=lambda _t: None, tty=lambda: False)
    with _cut(_bad_request) as sent, lib.env(LIVE="1", GOOGLE_CLOUD_PROJECT=lib.PROJECT):
        with contextlib.redirect_stdout(io.StringIO()):
            live_topic.run_topic(
                TOPIC, prices_path=lib.REAL_PRICES, live_provider_factory=factory, safety=FakeSafetyProvider(),
                person=person,
            )  # fmt: skip
    calls = [(path, body) for path, body in sent if path.endswith(":generateContent")]
    # The incident as the user saw it: the first Director call is rejected (no fallback after a 400) and nothing else
    # is sent, so the captured body is exactly the request that failed.
    assert len(calls) == 1, f"expected the one rejected Director call, saw {len(calls)}"
    body = calls[0][1]
    DUMP.parent.mkdir(parents=True, exist_ok=True)
    DUMP.write_text(json.dumps(redacted(body), indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return body


# --- schema facts (after the adapter's sanitizer: what Vertex sees) -----------------------------------------------


def _nodes(schema: Any, path: str = "$", depth: int = 1) -> Iterator[tuple[str, dict[str, Any], int]]:
    if not isinstance(schema, dict):
        return
    yield path, schema, depth
    for name, sub in (schema.get("properties") or {}).items():
        yield from _nodes(sub, f"{path}.{name}", depth + 1)
    for index, sub in enumerate(schema.get("anyOf") or []):
        yield from _nodes(sub, f"{path}.anyOf[{index}]", depth + 1)
    if "items" in schema:
        yield from _nodes(schema["items"], f"{path}[]", depth + 1)


def _schema(body: dict[str, Any]) -> dict[str, Any]:
    return body["generationConfig"]["responseJsonSchema"]  # type: ignore[no-any-return]


def _where(body: dict[str, Any], test: Callable[[dict[str, Any]], bool]) -> list[str]:
    return [path for path, node, _depth in _nodes(_schema(body)) if test(node)]


def _null_anyof(node: dict[str, Any]) -> bool:
    return {"type": "null"} in (node.get("anyOf") or [])


PROPERTY_SCHEMA_KEYS = frozenset(
    {"type", "properties", "required", "items", "enum", "anyOf", "description", "nullable"}
)


# (id, fact that must hold on the captured request, evidence, outcome: "ok" | "fixed" | "probe:<variant>")
SUSPECTS: list[tuple[str, Callable[[dict[str, Any]], bool], str, str]] = [
    (
        "max_output_tokens_is_the_role_cap_under_the_model_limit",
        lambda b: b["generationConfig"]["maxOutputTokens"] == ROLE_CAP <= MODEL_MAX_OUTPUT,
        "model page: output limit 65,536; thinking page: thought tokens count against it (MAX_TOKENS, not a 400)",
        "probe:director_exact_real_cap",
    ),
    (
        "an_untyped_empty_property_schema_out_of_scope",
        lambda b: not _where(b, lambda n: n == {}) and _schema(b)["properties"]["out_of_scope"]["type"] == "array",
        "FIXED (probe 8 Oct 2026: schema_no_empty passed): out_of_scope is sent as a typed list of {category, part}",
        "probe:director_schema_no_empty",
    ),
    (
        "type_null_branches_in_anyof",
        lambda b: (
            not _where(b, _null_anyof)
            and sorted(_where(b, lambda n: n.get("nullable") is True))
            == ["$.deadline", "$.out_of_policy", "$.sources[].label"]
        ),
        "FIXED (probe 8 Oct 2026: schema_no_null_anyof passed): anyOf [X, null] is sent as X with nullable",
        "probe:director_schema_no_null_anyof",
    ),
    (
        "titles_and_descriptions_present",
        lambda b: not _where(b, lambda n: "title" in n) and len(_schema(b).get("description", "")) < 300,
        "titles are not sent (probe: schema_no_titles alone still failed); descriptions stay",
        "probe:director_schema_no_titles",
    ),
    (
        "array_bounds_maxitems_10_20_50",
        lambda b: not any({"minItems", "maxItems", "minimum", "maximum"} & set(n) for _p, n, _d in _nodes(_schema(b))),
        "FIXED (probe 8 Oct 2026: schema_no_item_bounds passed): no bounds are sent; the caller validates them",
        "probe:director_schema_no_item_bounds",
    ),
    (
        "system_instruction_one_text_part_role_user",
        lambda b: b["systemInstruction"]["role"] == "user" and len(b["systemInstruction"]["parts"]) == 1,
        "content.proto Content.role: 'Must be either user or model'; prediction_service.proto: only text parts",
        "probe:director_system_no_role",
    ),
    (
        "system_instruction_present",
        lambda b: set(b["systemInstruction"]["parts"][0]) == {"text"},
        "nothing forbids it; removed once so the probe can clear or blame the system prompt",
        "probe:director_no_system",
    ),
    (
        "the_whole_schema",
        lambda b: "responseJsonSchema" in b["generationConfig"],
        "structured output page: a complex schema can be refused with InvalidArgument; no numeric limit published",
        "probe:director_no_schema",
    ),
    (
        "json_schema_with_json_mime_and_no_response_schema",
        lambda b: (
            b["generationConfig"]["responseMimeType"] == "application/json"
            and "responseSchema" not in b["generationConfig"]
        ),
        "content.proto: 'If set, response_schema must be omitted, but response_mime_type is required.'",
        "ok",
    ),
    (
        "no_thinking_config_sent",
        lambda b: "thinkingConfig" not in b["generationConfig"],
        "thinking page: dynamic thinking by default; the brief request names no level (the role's 'high' is unused)",
        "ok",
    ),
    (
        "only_documented_keywords",
        lambda b: all(set(n) <= PROPERTY_SCHEMA_KEYS for _p, n, _d in _nodes(_schema(b))),
        "content.proto response_json_schema keyword list",
        "ok",
    ),
    (
        "nullable_is_a_true_flag_and_no_format_ref_or_property_ordering",
        lambda b: (
            not _where(b, lambda n: bool({"format", "$ref", "$defs", "propertyOrdering"} & set(n)))
            and all(n["nullable"] is True for _p, n, _d in _nodes(_schema(b)) if "nullable" in n)
        ),
        "Vertex lists nullable; tracked in the follow-up issue (not a response_json_schema keyword in the proto)",
        "ok",
    ),
    (
        "no_single_branch_anyof_and_no_anyof_beside_type",
        lambda b: not _where(b, lambda n: "anyOf" in n and (len(n["anyOf"]) < 2 or "type" in n)),
        "content.proto lists anyOf; every anyOf here has two branches and no sibling type",
        "ok",
    ),
    (
        "every_required_list_is_non_empty_and_names_real_properties",
        lambda b: all(
            n["required"] and set(n["required"]) <= set(n.get("properties", {}))
            for _p, n, _d in _nodes(_schema(b))
            if "required" in n
        ),
        "content.proto lists required",
        "ok",
    ),
    (
        "enums_are_short_string_lists",
        lambda b: (
            max(len(n["enum"]) for _p, n, _d in _nodes(_schema(b)) if "enum" in n) == 11
            and all(n.get("type") == "string" for _p, n, _d in _nodes(_schema(b)) if "enum" in n)
        ),
        "content.proto: enum for strings and numbers; structured output page: 'enums with many values' (11 is few)",
        "ok",
    ),
    (
        "schema_is_small_and_shallow",
        lambda b: (
            max(d for _p, _n, d in _nodes(_schema(b))) <= 5
            and complexity(_schema(b)) <= 80  # the refused Director schema scored 117
            and len(json.dumps(_schema(b))) < 2048
        ),
        "Gemini API page: 'Very large or deeply nested schemas may be rejected' (15 properties, depth 5, under 2 KB)",
        "ok",
    ),
    (
        "no_tools_no_safety_settings_no_cached_content",
        lambda b: set(_wire(b)) == {"contents", "systemInstruction", "generationConfig"},
        "only contents, systemInstruction and generationConfig are sent",
        "ok",
    ),
]


@pytest.mark.parametrize(("name", "fact", "evidence", "outcome"), SUSPECTS, ids=[row[0] for row in SUSPECTS])
def test_PL_02_director_exact_request_suspect_table_holds(
    captured: dict[str, Any], name: str, fact: Callable[[dict[str, Any]], bool], evidence: str, outcome: str
) -> None:
    assert fact(captured), f"{name}: the captured request no longer matches the table ({evidence})"
    if outcome.startswith("probe:"):
        assert outcome.removeprefix("probe:") in schema_probe.DIRECTOR_VARIANT_NAMES, outcome
    else:
        assert outcome in ("ok", "fixed"), outcome


def test_PL_02_every_director_probe_variant_answers_a_suspect() -> None:
    probed = {outcome.removeprefix("probe:") for *_rest, outcome in SUSPECTS if outcome.startswith("probe:")}
    assert probed == set(schema_probe.DIRECTOR_VARIANT_NAMES) - {"director_exact"}


def test_PL_02_director_exact_request_is_the_brief_request_through_the_router_and_adapter(
    captured: dict[str, Any],
) -> None:
    request = brief.brief_request(TOPIC)
    body = _wire(captured)
    assert body["systemInstruction"] == {"parts": [{"text": request.system}], "role": "user"}
    assert body["contents"] == [{"parts": [{"text": request.prompt}], "role": "user"}]
    assert body["generationConfig"] == {
        "maxOutputTokens": ROLE_CAP,  # the Router's role cap (config/models.yaml), the request names none
        "responseMimeType": "application/json",
        "responseJsonSchema": json.loads(json.dumps(to_gemini_schema(brief.output_schema()))),
    }


def test_PL_02_director_exact_request_dump_is_redacted(captured: dict[str, Any]) -> None:
    dumped = json.loads(DUMP.read_text(encoding="utf-8"))
    text = json.dumps(dumped)
    assert TOPIC not in text and "You are the Director" not in text
    assert dumped["contents"][0]["parts"][0]["text"].startswith("<redacted: ")
    assert dumped["generationConfig"] == _wire(captured)["generationConfig"]
    assert lib.SECRET_RE.search(text) is None and lib.PROJECT not in text


def test_PL_02_the_probe_replays_the_captured_request_through_the_real_sdk(captured: dict[str, Any]) -> None:
    """`director_exact` differs from the live request only in the task text and the output cap; the removal
    variants each change exactly their field (Google's 400 is faked at the transport so every variant runs)."""

    short = "Plan a small team lunch."
    with _cut(_bad_request) as sent, lib.env():  # a clean environment: no stray API key or live switch
        schema_probe.run_schema_probe(
            brief.output_schema(), director=brief.brief_request(short), out=io.StringIO(), client=_client(),
            environ={"LIVE": "1", "GOOGLE_CLOUD_PROJECT": lib.PROJECT},
        )  # fmt: skip
    names = schema_probe.DIRECTOR_VARIANT_NAMES[:-1]  # the real-cap variant waits for an accepted exact replay
    bodies = dict(zip(names, (_wire(body) for _path, body in sent), strict=False))
    real, exact = _wire(captured), bodies["director_exact"]
    assert exact["systemInstruction"] == real["systemInstruction"]
    assert {**exact["generationConfig"], "maxOutputTokens": ROLE_CAP} == real["generationConfig"]
    assert exact["generationConfig"]["maxOutputTokens"] == 2 * schema_probe.DEFAULT_MAX_OUTPUT_TOKENS
    assert exact["contents"] == [{"parts": [{"text": brief.brief_request(short).prompt}], "role": "user"}]
    assert "systemInstruction" not in bodies["director_no_system"]
    assert "role" not in bodies["director_system_no_role"]["systemInstruction"]
    assert "responseJsonSchema" not in bodies["director_no_schema"]["generationConfig"]
    no_empty = bodies["director_schema_no_empty"]["generationConfig"]["responseJsonSchema"]
    assert "out_of_scope" not in no_empty["properties"]
    no_null = bodies["director_schema_no_null_anyof"]["generationConfig"]["responseJsonSchema"]
    assert no_null["properties"]["deadline"] == {"type": "string"}
    assert "maxItems" not in json.dumps(bodies["director_schema_no_item_bounds"]["generationConfig"])
