"""tilo_providers.factory — role -> `ModelProvider` factory (EFF-01, PRD
6.6). `build_provider` resolves a role's primary profile: `provider: fake`
returns `FakeModelProvider` directly (the dev Director model, `DevDirectorProvider`); every other profile returns a
`RecordReplayProvider`, whose real adapter is built lazily inside the
`live_factory` closure only when a call actually goes live (`LIVE=1`).
Nothing here imports an adapter module or builds a network client for a
plain replay hit."""

from __future__ import annotations

import os
from pathlib import Path

from tilo_contracts import ProvidersProfile

from tilo_providers.config import DEV_DIRECTOR_MODEL, ProviderConfigError, ProvidersConfig
from tilo_providers.interfaces import Capability, ModelProvider


def build_provider(
    role_id: str,
    config: ProvidersConfig,
    *,
    fixtures_dir: Path | str,
    profile_id: str | None = None,
    live_permitted: bool = False,
) -> ModelProvider:
    profile_id = profile_id or config.roles[role_id].primary  # the router passes any cascade profile
    profile = config.profiles[profile_id]

    if profile.provider == "fake" and profile.model == DEV_DIRECTOR_MODEL:  # CL-INT-5: refused when deployed or live
        from tilo_providers.dev_director import DevDirectorProvider  # noqa: PLC0415

        return DevDirectorProvider(profile_id=profile_id)

    if profile.provider == "fake":
        from tilo_providers.fake import FakeModelProvider  # noqa: PLC0415

        return FakeModelProvider(profile_id=profile_id)

    def live_factory() -> ModelProvider:
        return _build_live_provider(profile, profile_id, live_permitted=live_permitted)

    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    return RecordReplayProvider(
        role=role_id,
        profile_id=profile_id,
        live_factory=live_factory,
        fixtures_dir=Path(fixtures_dir),
        capabilities={Capability(c) for c in profile.caps},
        live_permitted=live_permitted,
    )


def _build_live_provider(profile: ProvidersProfile, profile_id: str, *, live_permitted: bool = False) -> ModelProvider:
    if profile.provider == "google":
        from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_LOCATION", "global")  # PRD 6.5: Gemini through the global endpoint
        return GoogleModelProvider(
            profile=profile, profile_id=profile_id, project=project, location=location, live_permitted=live_permitted
        )

    if profile.provider == "openai_compat":
        from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

        if profile.base_url is None or profile.api_key_env is None:
            raise ProviderConfigError(
                f"PL-02: profile {profile_id!r} is provider 'openai_compat' but has no base_url/api_key_env "
                "(contracts/providers.schema.json $defs.profile)"
            )
        return OpenAICompatModelProvider(
            profile=profile,
            profile_id=profile_id,
            base_url=profile.base_url,
            api_key_env=profile.api_key_env,
            live_permitted=live_permitted,
        )

    raise ValueError(f"PL-02: unknown provider {profile.provider!r} for profile {profile_id!r}")
