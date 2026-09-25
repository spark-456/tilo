"""tilo_providers.factory — role -> `ModelProvider` factory (EFF-01, PRD
6.6). `build_provider` resolves a role's primary profile via
`provider_for_role_profile`: `provider: fake` always returns
`FakeModelProvider` directly; every other profile returns a
`RecordReplayProvider`, whose real adapter is built lazily inside the
`live_factory` closure only when a call actually goes live (`LIVE=1`).
Nothing here imports an adapter module or builds a network client for a
plain replay hit. The router (P0-06) calls `provider_for_role_profile`
directly per candidate profile in a cascade or fallback."""

from __future__ import annotations

import os
from pathlib import Path

from tilo_contracts import ProvidersProfile

from tilo_providers.config import ProviderConfigError, ProvidersConfig
from tilo_providers.interfaces import Capability, ModelProvider


def provider_for_role_profile(
    role_id: str, profile_id: str, config: ProvidersConfig, *, fixtures_dir: Path | str
) -> ModelProvider:
    profile = config.profiles[profile_id]

    if profile.provider == "fake":
        from tilo_providers.fake import FakeModelProvider  # noqa: PLC0415

        return FakeModelProvider(profile_id=profile_id)

    def live_factory() -> ModelProvider:
        return _build_live_provider(profile, profile_id)

    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    return RecordReplayProvider(
        role=role_id,
        profile_id=profile_id,
        live_factory=live_factory,
        fixtures_dir=Path(fixtures_dir),
        capabilities={Capability(c) for c in profile.caps},
    )


def build_provider(role_id: str, config: ProvidersConfig, *, fixtures_dir: Path | str) -> ModelProvider:
    role = config.roles[role_id]
    return provider_for_role_profile(role_id, role.primary, config, fixtures_dir=fixtures_dir)


def _build_live_provider(profile: ProvidersProfile, profile_id: str) -> ModelProvider:
    if profile.provider == "google":
        from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_LOCATION", "global")  # PRD 6.5: Gemini through the global endpoint
        return GoogleModelProvider(profile=profile, profile_id=profile_id, project=project, location=location)

    if profile.provider == "openai_compat":
        from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

        if profile.base_url is None or profile.api_key_env is None:
            raise ProviderConfigError(
                f"PL-02: profile {profile_id!r} is provider 'openai_compat' but has no base_url/api_key_env "
                "(contracts/providers.schema.json $defs.profile)"
            )
        return OpenAICompatModelProvider(
            profile=profile, profile_id=profile_id, base_url=profile.base_url, api_key_env=profile.api_key_env
        )

    raise ValueError(f"PL-02: unknown provider {profile.provider!r} for profile {profile_id!r}")
