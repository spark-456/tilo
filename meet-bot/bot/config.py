"""Configuration from the environment and .env. Stdlib only, so the host CLI needs no installs."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IN_CONTAINER = os.environ.get("TILO_IN_CONTAINER") == "1"
SECRET_ENV_NAMES = ("GEMINI_API_KEY", "GEMINI_LIVE_API_KEY", "ELEVENLABS_API_KEY")
# Gemini Live models tried by `live-probe`, fastest-first by third-party measurements (Sep 2026). Override with LIVE_MODELS.
# Every model id lives here (or in .env), behind the provider interfaces.
DEFAULT_MODEL = "gemini-2.5-flash"  # the analysis loop, when the model list cannot be read; override with GEMINI_MODEL
DEFAULT_FAST_MODEL = "gemini-2.5-flash-lite"  # direct answers; override with FAST_MODEL
DEFAULT_TTS_MODEL = "eleven_flash_v2_5"  # ElevenLabs' low-latency model; override with ELEVENLABS_TTS_MODEL
STT_MODEL = "scribe_v2_realtime"  # ElevenLabs realtime speech to text
THINKING_LEVELS = ("off", "minimal", "low", "medium", "high")
DEFAULT_LIVE_MODELS = "gemini-3.1-flash-live-preview,gemini-3.8-live,gemini-2.5-flash-native-audio-preview-12-2025"


def parse_dotenv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_dotenv(path: Path | None = None) -> None:
    """Fill os.environ from .env without overriding real environment variables."""
    path = path or ROOT / ".env"
    if path.is_file():
        for k, v in parse_dotenv(path.read_text(encoding="utf-8")).items():
            os.environ.setdefault(k, v)


def _num(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        raise SystemExit(f"{name} must be a number, got {raw!r}") from None


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    raw = os.environ.get(name, "").strip().lower() or default
    if raw not in allowed:
        raise SystemExit(f"{name} must be one of {', '.join(allowed)}, got {raw!r}")
    return raw


def _names(raw: str) -> list[str]:
    return [n.strip() for n in raw.split(",") if n.strip()]


@dataclass(frozen=True)
class Config:
    bot_email: str
    bot_display_name: str
    gemini_model: str
    fast_model: str
    fast_thinking: str
    brain_interval_s: float
    window_minutes: float
    join_timeout_s: float
    ask_to_join_timeout_s: float
    alone_grace_s: float
    empty_timeout_s: float
    max_meeting_minutes: float
    meeting_minutes: float | None
    agenda_path: Path
    out_dir: Path
    debug_dir: Path
    profile_dir: Path
    save_caption_snapshots: bool
    auto_admit: bool
    admit_allowed: list[str]
    required: list[str]
    answer_mode: str
    record_audio: bool
    max_direct_replies: int
    direct_reply_gap_s: float
    hybrid: bool
    context_dir: Path
    context_urls: list[str]
    stt: str
    reply_mode: str
    voice_nudges: bool
    mic_policy: str
    live_models: list[str]
    live_voice: str
    live_api_version: str

    @classmethod
    def from_env(cls) -> Config:
        load_dotenv()
        e = os.environ.get
        mm = e("MEETING_MINUTES", "").strip()
        return cls(
            bot_email=e("BOT_GOOGLE_EMAIL", "").strip(),
            bot_display_name=e("BOT_DISPLAY_NAME", "").strip(),
            gemini_model=e("GEMINI_MODEL", "").strip(),
            fast_model=e("FAST_MODEL", "").strip() or DEFAULT_FAST_MODEL,
            fast_thinking=_choice("FAST_THINKING", "off", THINKING_LEVELS),
            brain_interval_s=max(10.0, _num("BRAIN_INTERVAL_SECONDS", 20)),
            window_minutes=_num("TRANSCRIPT_WINDOW_MINUTES", 5),
            join_timeout_s=_num("JOIN_TIMEOUT_SECONDS", 90),
            ask_to_join_timeout_s=_num("ASK_TO_JOIN_TIMEOUT_SECONDS", 300),
            alone_grace_s=_num("ALONE_GRACE_SECONDS", 60),
            empty_timeout_s=_num("EMPTY_TIMEOUT_SECONDS", 900),
            max_meeting_minutes=_num("MAX_MEETING_MINUTES", 120),
            meeting_minutes=float(mm) if mm else None,
            agenda_path=ROOT / e("AGENDA_PATH", "agenda.md"),
            out_dir=ROOT / e("OUT_DIR", "out"),
            debug_dir=ROOT / e("DEBUG_DIR", "debug"),
            profile_dir=Path(e("PROFILE_DIR", "/profile/chrome")),
            save_caption_snapshots=e("SAVE_CAPTION_SNAPSHOTS", "0") == "1",
            auto_admit=e("AUTO_ADMIT", "0") == "1",
            admit_allowed=_names(e("ADMIT_ALLOWED_NAMES", "")),
            required=_names(e("REQUIRED_PARTICIPANTS", "")),
            record_audio=e("RECORD_AUDIO", "0") == "1",
            max_direct_replies=int(_num("MAX_DIRECT_REPLIES", 12)),
            direct_reply_gap_s=_num("DIRECT_REPLY_GAP_SECONDS", 6),
            hybrid=e("HYBRID_TRANSCRIPT", "0") == "1",
            context_dir=ROOT / e("CONTEXT_DIR", "context"),
            context_urls=_names(e("CONTEXT_URLS", "")),
            reply_mode=(
                e("REPLY_MODE", "both").strip().lower()
                if e("REPLY_MODE", "both").strip().lower() in ("chat", "voice", "both")
                else "both"
            ),
            voice_nudges=e("VOICE_NUDGES", "0") == "1",
            mic_policy=_choice("MIC_POLICY", "open", ("open", "conversation")),
            live_models=_names(e("LIVE_MODELS", "") or DEFAULT_LIVE_MODELS),
            live_voice=e("LIVE_VOICE", "").strip(),
            live_api_version=e("LIVE_API_VERSION", "v1beta").strip() or "v1beta",
            stt=e("STT_PROVIDER", "").strip().lower()
            or ("gemini" if e("HYBRID_TRANSCRIPT", "0") == "1" else "captions"),
            answer_mode="addressed" if e("ANSWER_MODE", "questions") == "addressed" else "questions",
        )


class _Redactor(logging.Filter):
    """Belt and braces: never let a configured secret reach a log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for name in SECRET_ENV_NAMES:
            secret = os.environ.get(name)
            if secret and secret in msg:
                record.msg = msg.replace(secret, "[redacted]")
                record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    handler.addFilter(_Redactor())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
