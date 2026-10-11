"""FR-MTG-16: one synthetic native-audio turn, explicitly recorded or replayed.

This probe is separate from the bot: it never accepts meeting audio or opens a Meet.
Replay is unconditional by default, including on a machine with LIVE set.
"""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tilo_providers.errors import NotConfigured, ProviderError
from tilo_providers.google_adapter import validate_google_settings
from tilo_providers.replay import redact_strings


class TrialConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=400)
    timeout_s: float = Field(gt=0, le=20)
    max_audio_bytes: int = Field(gt=0, le=1_440_000)
    max_output_tokens: int = Field(gt=0, le=512)


class TrialResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal["1.0"] = "1.0"
    key: str = Field(pattern=r"^[a-f0-9]{16}$")
    sample_rate: Literal[24000] = 24000
    audio_pcm_b64: str
    text: str = Field(max_length=4000)
    first_audio_ms: float = Field(ge=0)
    total_ms: float = Field(ge=0)
    turn_complete: Literal[True]
    usage: dict[str, int] | None


def load_trial_config(path: Path, models_path: Path) -> TrialConfig:
    config = TrialConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    rules = yaml.safe_load(models_path.read_text(encoding="utf-8"))["rules"]["deny"]
    if any(fnmatch.fnmatchcase(config.model, pattern) for pattern in rules):
        raise NotConfigured("PL-07: trial model is denied")
    return config


@asynccontextmanager
async def _google_session(config: TrialConfig):
    if os.environ.get("LIVE") != "1":
        raise NotConfigured("The synthetic trial requires the user's LIVE switch")
    project, location = os.environ.get("GOOGLE_CLOUD_PROJECT", ""), os.environ.get("GOOGLE_LOCATION", "")
    validate_google_settings(project, location)
    from google import genai  # dev replay never imports or constructs the SDK client
    from google.genai import types

    client = genai.Client(vertexai=True, project=project, location=location, http_options={"api_version": "v1beta1"})
    try:
        async with client.aio.live.connect(
            model=config.model,
            config=types.LiveConnectConfig(
                response_modalities=[types.Modality.AUDIO],
                output_audio_transcription=types.AudioTranscriptionConfig(),
                max_output_tokens=config.max_output_tokens,
                system_instruction="This is a synthetic audio latency probe. Give one short spoken answer.",
            ),
        ) as session:
            yield session
    finally:
        await client.aio.aclose()


def _checked(result: TrialResult, key: str, cap: int) -> dict[str, Any]:
    audio = base64.b64decode(result.audio_pcm_b64, validate=True)
    if result.key != key or not audio or len(audio) % 2 or len(audio) > cap:
        raise ValueError("Invalid trial audio")
    if result.usage is not None and any(type(n) is not int or n < 0 for n in result.usage.values()):
        raise ValueError("Invalid usage")
    return result.model_dump(mode="json")


async def run_trial(
    config: TrialConfig,
    recordings: Path,
    *,
    record: bool = False,
    session_factory: Callable | None = None,
) -> dict[str, Any]:
    key = hashlib.sha256(config.model_dump_json().encode()).hexdigest()[:16]
    path = recordings / f"{key}.json"
    if not record:
        try:
            return _checked(TrialResult.model_validate_json(path.read_bytes()), key, config.max_audio_bytes)
        except (OSError, ValueError, ValidationError):
            raise ProviderError("FR-MTG-16: trial recording unavailable or invalid") from None
    if session_factory is None and os.environ.get("LIVE") != "1":
        raise NotConfigured("FR-MTG-16: recording requires the user's LIVE switch")
    audio, texts, first, complete = bytearray(), [], None, False
    usage: dict[str, int] | None = None
    start = time.monotonic()
    try:
        async with asyncio.timeout(config.timeout_s):
            async with (session_factory or _google_session)(config) as session:
                await session.send_client_content(
                    turns={"role": "user", "parts": [{"text": config.prompt}]},
                    turn_complete=True,
                )
                async for message in session.receive():
                    content = getattr(message, "server_content", None)
                    if content is not None:
                        if getattr(content, "interrupted", False):
                            raise ProviderError("FR-MTG-16: trial interrupted")
                        turn = getattr(content, "model_turn", None)
                        for part in getattr(turn, "parts", None) or []:
                            inline = getattr(part, "inline_data", None)
                            data = getattr(inline, "data", None)
                            mime = getattr(inline, "mime_type", "")
                            if isinstance(data, bytes) and data:
                                if mime != "audio/pcm;rate=24000" or len(data) % 2:
                                    raise ProviderError("FR-MTG-16: invalid PCM format")
                                if len(audio) + len(data) > config.max_audio_bytes:
                                    raise ProviderError("FR-MTG-16: audio cap exceeded")
                                first = first if first is not None else (time.monotonic() - start) * 1000
                                audio.extend(data)
                        text = getattr(getattr(content, "output_transcription", None), "text", None)
                        if isinstance(text, str):
                            texts.append(text)
                            if sum(map(len, texts)) > 4000:
                                raise ProviderError("FR-MTG-16: transcription cap exceeded")
                        complete = complete or bool(getattr(content, "turn_complete", False))
                    metadata = getattr(message, "usage_metadata", None)
                    if metadata is not None:
                        usage = {}
                        for name in ("prompt_token_count", "response_token_count", "total_token_count"):
                            count = getattr(metadata, name, None)
                            if type(count) is int and count >= 0:
                                usage[name] = count
                        usage = usage or None
    except TimeoutError:
        raise ProviderError("FR-MTG-16: trial timed out") from None
    except (ProviderError, NotConfigured):
        raise
    except Exception:
        raise ProviderError("FR-MTG-16: trial failed") from None
    if not complete or first is None:
        raise ProviderError("FR-MTG-16: incomplete or silent trial")
    text = re.sub(r"(?i)(?:https?://)?meet\.google\.com/[^\s<>\"']+", "[Meet link removed]", "".join(texts))
    result = TrialResult(
        key=key,
        audio_pcm_b64=base64.b64encode(audio).decode(),
        text=redact_strings(text, None),
        first_audio_ms=first,
        total_ms=(time.monotonic() - start) * 1000,
        turn_complete=True,
        usage=usage,
    )
    checked = _checked(result, key, config.max_audio_bytes)
    recordings.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(checked, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return checked


def main() -> None:
    import argparse
    import wave

    parser = argparse.ArgumentParser(description="One synthetic native-audio turn; default is offline replay")
    parser.add_argument("--config", type=Path, default=Path("config/meeting-live-trial.yaml"))
    parser.add_argument("--models", type=Path, default=Path("config/models.yaml"))
    parser.add_argument("--recordings", type=Path, required=True)
    parser.add_argument("--record-synthetic", action="store_true")
    parser.add_argument("--wav", type=Path)
    args = parser.parse_args()
    config = load_trial_config(args.config, args.models)
    result = asyncio.run(run_trial(config, args.recordings, record=args.record_synthetic))
    if args.wav is not None:
        args.wav.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(args.wav), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(result["sample_rate"])
            output.writeframes(base64.b64decode(result["audio_pcm_b64"]))
    print(json.dumps({key: value for key, value in result.items() if key not in ("audio_pcm_b64", "text")}))


if __name__ == "__main__":
    main()
