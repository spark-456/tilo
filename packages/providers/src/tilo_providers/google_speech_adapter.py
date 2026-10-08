"""tilo_providers.google_speech_adapter — the live SpeechProvider: Gemini audio on Agent Platform (FR-MTG-17,
FR-MTG-11; D-1 Google only). The recording goes inline in one `generate_content` call with a JSON schema and the
`prompts/speech/transcribe.md` template; the reply must be `{"segments": [...]}` or the call fails closed. The model
id is config (`config/speech.yaml`). Like `google_adapter`, building a real client needs `LIVE=1`; tests inject
`client=` (a fake) and never reach the network. Imports `google.genai` lazily, so replay never loads the SDK."""

from __future__ import annotations

import importlib
import json
import os
from typing import Any

from tilo_providers.errors import ProviderError, map_http_status, map_transport_error
from tilo_providers.google_adapter import _GOOGLE_SECRET_RE, validate_google_settings
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.prompts import load_prompt
from tilo_providers.speech import as_speech_result, check_request

_REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "start_ms": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["speaker", "start_ms", "text"],
            },
        }
    },
    "required": ["segments"],
}


class GoogleSpeechProvider(SpeechProvider):
    def __init__(self, model: str, project: str, location: str, client: Any | None = None) -> None:
        self._model = model
        if client is None:
            if os.environ.get("LIVE") != "1":  # EFF-01: reachable directly, not only through the replay wrapper
                raise ProviderError("EFF-01: refusing to build a real network client without LIVE=1 (inject client=)")
            validate_google_settings(project, location)  # before any client exists
            client = importlib.import_module("google.genai").Client(vertexai=True, project=project, location=location)
        self._client = client

    def redact(self, text: str) -> str:
        return _GOOGLE_SECRET_RE.sub("[redacted]", text)

    def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
        media_type, language = check_request(audio, kwargs, None)
        prompt = load_prompt("speech", "transcribe.md", {"language": language or "detect it"})
        contents = [
            {"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": media_type, "data": audio}}]}
        ]
        config = {"response_mime_type": "application/json", "response_json_schema": _REPLY_SCHEMA}
        try:
            response = self._client.models.generate_content(model=self._model, contents=contents, config=config)
        except Exception as error:
            failure = self._failure(error)
        else:
            return self._parse(getattr(response, "text", None))
        raise failure

    def _failure(self, error: Exception) -> ProviderError:
        """The mapped error, built outside the `except` so the raw SDK error (its message can echo a token) is
        neither the cause nor the context."""
        if isinstance(error, importlib.import_module("google.genai.errors").APIError):
            return map_http_status(int(getattr(error, "code", 500)), self.redact(str(getattr(error, "message", ""))))
        return map_transport_error(error) or ProviderError(f"PL-02: the speech call failed ({type(error).__name__})")

    @staticmethod
    def _parse(text: Any) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("FR-MTG-17: the speech model returned no text")
        try:
            data = json.loads(text)
        except ValueError:
            raise ProviderError("FR-MTG-17: the speech model's reply is not JSON") from None
        return as_speech_result(data)
