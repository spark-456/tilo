"""tilo_providers.factory — role -> `ModelProvider` factory (EFF-01, PRD
6.6). `build_provider` resolves a role's primary profile and decides which
kind of `ModelProvider` business code gets:

- `provider: fake` profiles always return `tilo_providers.fake.
  FakeModelProvider` directly, whatever `LIVE` is set to — fixture/UI work
  never needs a recording.
- every other profile returns `tilo_providers.replay.RecordReplayProvider`,
  which replays unless `LIVE=1`. The real adapter (`google_adapter` /
  `openai_compat_adapter`) is only ever built lazily, inside the
  `live_factory` closure the replay provider calls — and only when a call
  actually records (`LIVE=1` *and* `TILO_RECORD=1`). Nothing here imports an
  adapter module or builds a network client at import time or for a plain
  replay hit."""

from __future__ import annotations

import os
from pathlib import Path

from tilo_contracts import ProvidersProfile

from tilo_providers.config import ProvidersConfig
from tilo_providers.interfaces import ModelProvider


def build_provider(role_id: str, config: ProvidersConfig, *, fixtures_dir: Path | str) -> ModelProvider:
    role = config.roles[role_id]
    profile_id = role.primary
    profile = config.profiles[profile_id]

    if profile.provider == "fake":
        from tilo_providers.fake import FakeModelProvider  # noqa: PLC0415

        return FakeModelProvider(profile_id=profile_id)

    def live_factory() -> ModelProvider:
        return _build_live_provider(profile, profile_id)

    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    return RecordReplayProvider(
        role=role_id, profile_id=profile_id, live_factory=live_factory, fixtures_dir=Path(fixtures_dir)
    )


def _build_live_provider(profile: ProvidersProfile, profile_id: str) -> ModelProvider:
    if profile.provider == "google":
        from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_LOCATION", "global")  # PRD 6.5: Gemini through the global endpoint
        return GoogleModelProvider(profile=profile, profile_id=profile_id, project=project, location=location)

    if profile.provider == "openai_compat":
        # base_url/api_key_env are not yet fields on ProvidersProfile
        # (needs contract change: contracts/providers.schema.json
        # $defs.profile — see config/models.nim.yaml's header comment).
        # Until they land, build tilo_providers.openai_compat_adapter.
        # OpenAICompatModelProvider directly with the values from your own
        # config, rather than through this factory.
        raise NotImplementedError(
            "PL-02: live routing for provider 'openai_compat' needs base_url/api_key_env on the profile "
            "(needs contract change: contracts/providers.schema.json $defs.profile) — not wired into the "
            "factory yet"
        )

    raise ValueError(f"PL-02: unknown provider {profile.provider!r} for profile {profile_id!r}")
