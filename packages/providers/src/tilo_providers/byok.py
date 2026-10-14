"""tilo_providers.byok: the org-key seam (ADR-0041, BYOK-2; variant P, the proxy).

An org may run its own live model calls on its own provider account. This module changes *whose credential and whose
meter* a call uses and nothing else. SECURITY PATH: it is credential handling, and it is INERT: `config/byok.yaml`
`enabled` is false in the shipped file, `load_byok_config` then returns a closed config with no bundle, and a Router
built with no `org=` is exactly what it was before.

What is here (and what is not):
* `ByokConfig` / `load_byok_config`: the flag, the ceiling and the bundles (an allow-list of role -> org profiles).
  An openai_compat org profile is a profile of `config/models*.yaml` with `credential: "org"` (providers.schema.json
  1.4.0, BK-12), a fixed https `base_url` and no `api_key_env` (an org call never reads the environment, BK-10); no
  Tilo role names it (`config.py` refuses that at load). The two Google kinds have no contract case yet (BQ-BYOKC-2):
  until BQ-BYOK-2 is answered they keep the interim marker, "named by a bundle and by no role" (BQ-BYOK-8).
* `OrgProviderSource` / `OrgBinding`: the seam the Router asks for a provider per org.
  Variant P: `ProxyOrgProviderSource` returns a `ProxyModelProvider` whose `generate` hands the call to
  tilo-connectors over a `ModelCallTransport`; no credential type exists in this process, so there is nothing here
  to leak (BK-21, BK-22). Variant L (the lease, a key in tilo-api memory) is not built: it needs the user's explicit
  yes (BQ-BYOK-7).
* `CredentialRefused`: a fixed code, never a provider's error text (some providers echo key fragments, BK-17).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from tilo_providers.config import ProviderConfigError, ProvidersConfig
from tilo_providers.diagnostics import log_caught
from tilo_providers.errors import MissingCapabilityError, NotConfigured, ProviderError, QuotaError, RetryableError
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CONFIG = _REPO_ROOT / "config" / "byok.yaml"
KINDS = ("openai_compat", "google_api_key", "google_vertex_iam")  # BQ-BYOK-2: both "Google" modes, BYOK-6
_PROVIDER_OF_KIND = {"openai_compat": "openai_compat", "google_api_key": "google", "google_vertex_iam": "google"}
_NEVER_ROLES = frozenset({"safety", "search", "speech", "embedding", "embed"})  # BK-13: Tilo's, always
# The fixed vocabulary of a refusal: what an owner or a Trace row may say about a credential problem (BK-17).
REFUSAL_CODES = frozenset(
    {
        "not_configured", "no_key", "invalid_key", "key_removed", "key_paused", "unverified", "cap_reached",
        "quota", "rate_limited", "unreachable",
    }
)  # fmt: skip
_BUNDLE_KEYS = frozenset({"label", "kind", "roles"})
# byok.schema.json 1.0.0 `bundle_id` and `bundle.label`, verbatim (tests pin them to the schema): every member sees
# the label, so a closed alphabet with no markup, link or address (BQ-BYOKC-5a).
_BUNDLE_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ().,'/_+-]{0,79}$")
_FILE_KEYS = frozenset(
    {"version", "example", "enabled", "day_cap_credits_max", "calls_per_org_per_minute", "consent_version", "bundles"}
)


class ByokConfigError(ProviderConfigError):
    """`config/byok.yaml` is unusable. A caller treats it as `not_configured`: nothing is Tilo-keyed by accident."""


class CredentialRefused(ProviderError):
    """The org's credential cannot be used for this call. A fixed `code` only, never raw error text; the Router turns
    it into a `RouterCredentialError` that blocks the unit with no fallback and no second profile (BK-17)."""

    def __init__(self, code: str) -> None:
        self.code = code if code in REFUSAL_CODES else "unreachable"
        super().__init__(f"BK-17: the organisation's model credential cannot be used ({self.code})")


class ProxyRefusal(Exception):
    """Raised by a `ModelCallTransport` for connectors' fixed refusal code. Carries nothing else."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# --- config ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OrgBundle:
    id: str
    label: str
    kind: str
    roles: Mapping[str, tuple[str, str | None]] = field(default_factory=dict)  # role -> (primary, fallback)

    @property
    def profile_ids(self) -> frozenset[str]:
        return frozenset(p for pair in self.roles.values() for p in pair if p)


@dataclass(frozen=True)
class ByokConfig:
    """The default is the off state: every route answers `not_configured`, no Router takes a bundle."""

    enabled: bool = False
    day_cap_credits_max: int = 0
    calls_per_org_per_minute: int = 0
    consent_version: int = 1
    bundles: Mapping[str, OrgBundle] = field(default_factory=dict)


def _positive(doc: Mapping[str, Any], name: str) -> int:
    value = doc.get(name)
    if type(value) is not int or value < 1:
        raise ByokConfigError(f"BK-16: byok.yaml {name} must be a whole number of at least 1")
    return value


def load_byok_config(path: Path | str | None = None, *, providers: ProvidersConfig | None = None) -> ByokConfig:
    """Absent file or `enabled: false` is the off config and nothing else is checked. Enabled: the closed shape and
    every bundle rule (BK-12, BK-13) against `providers`, which is then required. Raises `ByokConfigError`."""
    target = Path(path) if path is not None else _CONFIG
    if not target.is_file():
        return ByokConfig()
    try:
        doc = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as caught_error:
        log_caught(caught_error, __name__, locals())
        raise ByokConfigError("byok.yaml is not readable plain YAML") from None
    if not isinstance(doc, dict) or not set(doc) <= _FILE_KEYS or type(doc.get("enabled")) is not bool:
        raise ByokConfigError(f"byok.yaml must be a mapping of {sorted(_FILE_KEYS)} with a boolean `enabled`")
    if doc["enabled"] is not True:
        return ByokConfig()
    if providers is None:
        raise ByokConfigError("BK-12: an enabled byok.yaml is only checked against a loaded providers config")
    bundles = doc.get("bundles")
    if not isinstance(bundles, dict) or not bundles:
        raise ByokConfigError("BK-13: an enabled byok.yaml needs at least one bundle")
    return ByokConfig(
        enabled=True,
        day_cap_credits_max=_positive(doc, "day_cap_credits_max"),
        calls_per_org_per_minute=_positive(doc, "calls_per_org_per_minute"),
        consent_version=_positive(doc, "consent_version"),
        bundles={str(i): _bundle(str(i), b, providers) for i, b in bundles.items()},
    )


def _bundle(bundle_id: str, raw: Any, providers: ProvidersConfig) -> OrgBundle:
    where = f"BK-13: bundle {bundle_id!r}"
    if _BUNDLE_ID.fullmatch(bundle_id) is None:
        raise ByokConfigError(f"BK-13: bundle id {bundle_id!r} is not lower-case words joined by hyphens")
    if not isinstance(raw, dict) or set(raw) != _BUNDLE_KEYS or raw["kind"] not in KINDS:
        raise ByokConfigError(f"{where} must have exactly label, kind (one of {KINDS}) and roles")
    if not isinstance(raw["label"], str) or _LABEL.fullmatch(raw["label"]) is None:
        raise ByokConfigError(f"{where} label must be 1 to 80 plain characters (BK-20: every member sees it)")
    if not isinstance(raw["roles"], dict):
        raise ByokConfigError(f"{where} needs a roles mapping")
    roles: dict[str, tuple[str, str | None]] = {}
    for role, pair in raw["roles"].items():
        if role in _NEVER_ROLES or role not in providers.roles:
            raise ByokConfigError(
                f"{where} names role {role!r}: only a generating role of config/models.yaml, "
                f"never {sorted(_NEVER_ROLES)}"
            )
        if not isinstance(pair, dict) or set(pair) != {"primary", "fallback"}:
            raise ByokConfigError(f"{where} role {role!r} needs a primary and a fallback of its own (NFR-25)")
        roles[role] = (str(pair["primary"]), None if pair["fallback"] is None else str(pair["fallback"]))
        if roles[role][1] is None:
            raise ByokConfigError(f"{where} role {role!r} has no fallback profile (NFR-25)")
    bundle = OrgBundle(bundle_id, raw["label"].strip(), raw["kind"], roles)
    named_by_roles = {p for r in providers.roles.values() for p in (r.primary, r.fallback, *(r.cascade or ())) if p}
    for profile_id in sorted(bundle.profile_ids):
        profile = providers.profiles.get(profile_id)
        if profile is None:
            raise ByokConfigError(f"{where} names unknown profile {profile_id!r}")
        if profile.provider != _PROVIDER_OF_KIND[bundle.kind]:
            raise ByokConfigError(f"{where}: profile {profile_id!r} is not a {_PROVIDER_OF_KIND[bundle.kind]} profile")
        if bundle.kind == "openai_compat":
            if profile.credential != "org":  # providers.schema.json 1.4.0: the contract's marker (BQ-BYOK-8 interim)
                raise ByokConfigError(f"BK-12: {where}: profile {profile_id!r} is not an org profile (credential: org)")
            if profile.base_url is None or profile.api_key_env is not None:
                raise ByokConfigError(f"{where}: {profile_id!r} must have a fixed base_url and no api_key_env (BK-10)")
        if profile_id in named_by_roles:
            raise ByokConfigError(f"BK-12: a Tilo role names org profile {profile_id!r}; an org profile is org-only")
        if providers.prices.status != "set" or profile_id not in providers.prices.profiles:
            raise ByokConfigError(f"PL-06: org profile {profile_id!r} is unpriced; no price, so no metering, no call")
    return bundle


# --- the seam -------------------------------------------------------------------------------------------------------


class OrgProviderSource(Protocol):
    """BK-09: a provider for one org's profile, for one run. Raises `CredentialRefused` (a fixed code)."""

    def provider_for(self, org_id: str, slot: str, profile_id: str, run_id: str) -> ModelProvider: ...


@dataclass(frozen=True)
class OrgBinding:
    """What a Router is given for one unit of one org: who, which bundle, where providers come from."""

    org_id: str
    slot: str
    run_id: str
    bundle: OrgBundle
    source: OrgProviderSource


class ModelCallTransport(Protocol):
    """tilo-api's side of connectors' `generate` route (variant P). Returns the closed answer (`text`, `tool_calls`,
    `usage`) or raises `ProxyRefusal(code)`. It has no key parameter and returns no key field (BK-22)."""

    def generate(
        self, *, org_id: str, slot: str, run_id: str, profile_id: str, request: GenerateRequest
    ) -> Mapping[str, Any]: ...


_REPLY_KEYS = frozenset({"text", "tool_calls", "usage"})
_USAGE_KEYS = frozenset({"input_tokens", "output_tokens", "total_tokens", "cached_tokens"})


def _conforms(reply: Mapping[str, Any]) -> bool:
    """model_call_rpc.generate_answer, which the pydantic types of the answer cannot say: `text` is present (a string
    or null), a tool call is exactly `{name, args}`, and a usage that is present has whole `input_tokens` and
    `output_tokens` and nothing beyond the four counts. Anything else is a bad reply (BK-17), never relayed."""
    if "text" not in reply:
        return False
    text, calls, usage = reply["text"], reply.get("tool_calls"), reply.get("usage")
    if not (text is None or (isinstance(text, str) and len(text) <= 400_000)):
        return False
    if calls is not None and not (
        isinstance(calls, list)
        and len(calls) <= 64
        and all(
            isinstance(c, dict)
            and set(c) == {"name", "args"}
            and isinstance(c["name"], str)
            and 1 <= len(c["name"]) <= 128
            and isinstance(c["args"], dict)
            for c in calls
        )
    ):
        return False
    if usage is None:
        return True
    counts = isinstance(usage, dict) and {"input_tokens", "output_tokens"} <= set(usage) <= _USAGE_KEYS
    return bool(counts and all(type(n) is int and n >= 0 for n in usage.values()))


class ProxyModelProvider(ModelProvider):
    """The org's model as tilo-api sees it: a handle that posts the call to connectors. Generate-only (BK-10): a
    stream is the whole reply as one chunk, embed is refused. It holds no credential, so no repr, log or error here
    can show one; a transport failure is mapped to a fixed outcome *outside* the `except`, so the new error has no
    `__cause__` or `__context__` that could still carry the provider's text."""

    def __init__(
        self,
        profile_id: str,
        *,
        caps: set[Capability],
        price: PriceQuote,
        transport: ModelCallTransport,
        org_id: str,
        slot: str,
        run_id: str,
    ) -> None:
        self._profile_id, self._caps, self._price, self._transport = profile_id, set(caps), price, transport
        self._org_id, self._slot, self._run_id = org_id, slot, run_id

    def __repr__(self) -> str:
        return f"ProxyModelProvider(profile={self._profile_id!r})"

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        if request.parts:  # model_call_rpc.request has no `parts`: v1 is text only (BK-10), refused before any send
            raise MissingCapabilityError("BK-10: an org-key profile takes text only; media stays on Tilo's profile")
        reply: Mapping[str, Any] | None = None
        refused: str | None = None
        try:
            got = self._transport.generate(
                org_id=self._org_id, slot=self._slot, run_id=self._run_id, profile_id=self._profile_id, request=request
            )
            if isinstance(got, Mapping) and set(got) <= _REPLY_KEYS and _conforms(got):  # closed: a stray field is bad
                reply = dict(got)
            else:
                refused = "unreachable"
        except ProxyRefusal as refusal:
            refused = refusal.code
        except Exception as caught_error:
            log_caught(caught_error, __name__, locals())
            refused = "unreachable"
        if reply is None:
            raise _error_for(refused or "unreachable")
        return GenerateResponse(
            text=reply["text"],
            profile_id=self._profile_id,
            tool_calls=reply.get("tool_calls"),
            usage=reply.get("usage"),
        )

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise NotConfigured("BK-13: an org-key profile is generate-only; embeddings stay on Tilo's profile")

    def count_tokens(self, text: str) -> int:
        return len(text.split())  # the whitespace estimate every non-Google adapter uses; the provider's usage governs

    def capabilities(self) -> set[Capability]:
        return set(self._caps)

    def price(self) -> PriceQuote:
        return self._price


def _error_for(code: str) -> ProviderError:
    if code in ("quota", "rate_limited"):
        return QuotaError(f"BK-17: the organisation's provider account answered {code}")  # a fallback inside the bundle
    if code == "unreachable":
        return RetryableError("BK-17: the organisation's model call could not be completed")
    return CredentialRefused(code)


class ProxyOrgProviderSource:
    """BK-09 variant P. `provider_for` never sees a key: it needs the profile's caps and price (PL-06) and a
    transport, and refuses an unknown or unpriced profile before any call."""

    def __init__(self, config: ProvidersConfig, transport: ModelCallTransport) -> None:
        self._config, self._transport = config, transport

    def provider_for(self, org_id: str, slot: str, profile_id: str, run_id: str) -> ModelProvider:
        profile = self._config.profiles.get(profile_id)
        if profile is None:
            raise CredentialRefused("not_configured")
        try:
            quote = self._config.price(profile_id)
        except ProviderConfigError:
            raise CredentialRefused("not_configured") from None
        return ProxyModelProvider(
            profile_id,
            caps={Capability(c) for c in profile.caps},
            price=PriceQuote(input=quote.input, output=quote.output),
            transport=self._transport,
            org_id=org_id,
            slot=slot,
            run_id=run_id,
        )


class FakeModelCallTransport:
    """Dev and CI (EFF-01): a deterministic reply from the prompt alone; no network, no key, no paid call. `refuse`
    maps a profile id to a refusal code."""

    def __init__(self, refuse: Mapping[str, str] | None = None) -> None:
        self._refuse = dict(refuse or {})

    def generate(
        self, *, org_id: str, slot: str, run_id: str, profile_id: str, request: GenerateRequest
    ) -> Mapping[str, Any]:
        if profile_id in self._refuse:
            raise ProxyRefusal(self._refuse[profile_id])
        digest = hashlib.sha256(request.prompt.encode("utf-8")).hexdigest()[:8]
        tokens_in = len(request.prompt.split())
        return {"text": f"[byok-fake:{digest}]", "usage": {"input_tokens": tokens_in, "output_tokens": 2}}


class FakeOrgProviderSource(ProxyOrgProviderSource):
    """BK-09: ships here for tests and dev."""

    def __init__(self, config: ProvidersConfig, *, refuse: Mapping[str, str] | None = None) -> None:
        super().__init__(config, FakeModelCallTransport(refuse))
