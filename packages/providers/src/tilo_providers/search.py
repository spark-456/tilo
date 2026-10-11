"""tilo_providers.search — the SearchProvider layer (LW-05, ADR-0029 decision 7; PRD 12.2). `search(query,
max_output_tokens=None)` returns a typed `SearchResult`: the answer, the cited sources, the queries the provider ran,
the search suggestions to show beside the answer, and usage with `search_queries` (the unit the price book charges).

Rules held here for every implementation: the secret redactor runs on the query before it is keyed, recorded or sent
(`prepare_search`); only `max_output_tokens` is accepted, so no caller can add a tool (the URL-context tool in
particular: a fetch goes through tilo-browser, LW-08); a source's grounding redirect URL is cleaned and kept as
`redirect_url`, and `resolved_url` stays None: nothing here fetches or resolves it. `FakeSearchProvider` is the dev
vendor; `SearchRecordReplayProvider` mirrors `speech.SpeechRecordReplayProvider` (EFF-01: replay by default, `LIVE=1`
live, `+TILO_RECORD=1` writes a redacted recording); `build_search_provider` resolves a role's profile."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tilo_providers.config import ProviderConfigError, ProvidersConfig, refuse_dev_only
from tilo_providers.errors import ProviderError, RequestError
from tilo_providers.google_adapter import _GOOGLE_SECRET_RE
from tilo_providers.interfaces import Capability, SearchProvider
from tilo_providers.replay import Redactor, ReplayMissError, _scrub_authorization_like, is_live_mode, redact_strings

MAX_QUERY_CHARS = 2000  # EFF-03: a search query is short; a longer one is refused, never cut
MAX_URL_CHARS = 2048
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_SHAPES = re.compile(
    r"\bsk-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|(?i:(?:password|passwd|pwd|secret|token|api[_-]?key|otp)\s{0,8}[=:]\s{0,8})[^\s&\"']+"
)


def redact_query(text: str) -> str:
    """The secret redactor for a query: Google tokens, Authorization/Bearer values, well-known API key shapes, JWTs and
    `password=`-style pairs become `[redacted]` (PRD 16.1 rule 4). Idempotent."""
    return _SECRET_SHAPES.sub("[redacted]", _scrub_authorization_like(_GOOGLE_SECRET_RE.sub("[redacted]", text)))


class SearchRequest(BaseModel):  # the validated, redacted call
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    max_output_tokens: int | None = Field(default=None, ge=1)


class SearchSource(BaseModel):  # one cited source
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    domain: str | None = None
    redirect_url: str  # the cleaned grounding redirect URL, exactly as the provider gave it (https only)
    resolved_url: str | None = None  # None here: LW-08 resolves the redirect through tilo-browser


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str  # the redacted query that was sent
    answer: str
    sources: list[SearchSource]
    queries: list[str]  # what the provider searched for (Gemini: grounding_metadata.web_search_queries)
    suggestions_html: str | None = None  # the provider's suggestion chips: untrusted HTML, shown sandboxed
    profile_id: str
    # input_tokens, output_tokens, total_tokens, cached_tokens when reported, and search_queries (the billing unit)
    # only when the provider reported its query list: left out means unknown, never 0 (the router charges the reserve).
    usage: dict[str, int] | None = None


def clean_source_url(raw: Any) -> str | None:
    """`https://host[:port]/path?query` with control characters, userinfo and fragment removed; None for anything that
    is not an https URL with a host, or is over 2,048 characters. Never fetched or resolved."""
    if not isinstance(raw, str):
        return None
    text = _CONTROL.sub("", raw).strip()
    if not text or len(text) > MAX_URL_CHARS:
        return None
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or not host:
        return None
    host = f"[{host}]" if ":" in host else host
    return urlunsplit(("https", f"{host}:{port}" if port else host, parts.path, parts.query, ""))


def refuse_other_tools(tools: Any) -> None:
    """ADR-0029 decision 7: the only tool a search call may carry is `google_search`. URL context (a fetch on Google's
    side, outside egress control, robots.txt and the raw archive) and every other tool are refused."""
    if tools != [{"google_search": {}}]:
        raise RequestError(
            "ADR-0029: the search adapter sends only the google_search tool; URL context and every other tool are "
            "refused (a fetch goes through tilo-browser, LW-08)"
        )


def prepare_search(query: Any, kwargs: dict[str, Any]) -> SearchRequest:
    """Validates one `search` call and runs the secret redactor on the query, before anything is keyed, recorded or
    sent. Only `max_output_tokens` is accepted: `tools=`, `url_context=` and every other option are refused."""
    if kwargs.keys() - {"max_output_tokens"}:
        raise RequestError(
            "ADR-0029: search takes a query and max_output_tokens only; no tool (URL context included) can be added"
        )
    if not isinstance(query, str) or not query.strip():
        raise RequestError("PRD 12.2: search needs a non-empty text query")
    if len(query) > MAX_QUERY_CHARS:
        raise RequestError(f"EFF-03: the query is over the search cap of {MAX_QUERY_CHARS} characters")
    try:
        return SearchRequest(query=redact_query(query.strip()), max_output_tokens=kwargs.get("max_output_tokens"))
    except ValidationError:
        raise RequestError("PRD 12.2: search max_output_tokens must be a whole number of at least 1") from None


class FakeSearchProvider(SearchProvider):
    """Deterministic, no network: the same query always gives the same result. Refused when `LIVE=1` or deployed (a
    fake answer must never reach a real task)."""

    def __init__(self, profile_id: str = "search-fake") -> None:
        refuse_dev_only(profile_id)
        self._profile_id = profile_id

    def search(self, query: str, **kwargs: Any) -> SearchResult:
        request = prepare_search(query, kwargs)
        digest = hashlib.sha256(request.query.encode("utf-8")).hexdigest()[:8]
        source = SearchSource(
            title="Fake source", domain="search-fake.test", redirect_url=f"https://search-fake.test/r/{digest}"
        )
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "search_queries": 1}
        return SearchResult(
            query=request.query,
            answer=f"[fake:{digest}] {request.query}",
            sources=[source],
            queries=[request.query],
            profile_id=self._profile_id,
            usage=usage,
        )


def search_recording_key(profile_id: str, query: str, max_output_tokens: int | None) -> str:
    """A stable hash of (profile, redacted query, cap): the recording's filename stem."""
    request = {"query": query, "max_output_tokens": max_output_tokens}
    normalised = json.dumps({"role": "search", "profile": profile_id, "search_request": request}, sort_keys=True)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


class SearchRecordReplayProvider(SearchProvider):
    def __init__(
        self,
        profile_id: str,
        live_factory: Callable[[], SearchProvider],
        fixtures_dir: Path | str,
        live_permitted: bool = False,
    ) -> None:
        self._profile_id, self._live_factory, self._live_permitted = profile_id, live_factory, live_permitted
        self._live_provider: SearchProvider | None = None
        self._dir = Path(fixtures_dir) / "search-recordings"

    def search(self, query: str, **kwargs: Any) -> SearchResult:
        request = prepare_search(query, kwargs)  # before the lookup, replay or live
        key = search_recording_key(self._profile_id, request.query, request.max_output_tokens)
        path = self._dir / f"{key}.json"
        if self._live_permitted or is_live_mode():  # SEC-15: permission is injected, never read from the environment
            if self._live_provider is None:
                self._live_provider = self._live_factory()
            result = self._live_provider.search(request.query, **kwargs)
            if is_live_mode() and os.environ.get("TILO_RECORD") == "1":  # a permitted call never records
                self._write(path, key, result, self._live_provider)
            return result
        if path.is_file():
            return self._read(path)
        raise ReplayMissError(
            f"EFF-01: no search recording for profile={self._profile_id!r} key={key!r} at {path} "
            "- run with LIVE=1 TILO_RECORD=1 to record one"
        )

    @staticmethod
    def _read(path: Path) -> SearchResult:
        try:
            return SearchResult.model_validate(json.loads(path.read_text(encoding="utf-8"))["result"])
        except (OSError, ValueError, KeyError, TypeError):  # a corrupt or hand-edited recording fails closed
            raise ProviderError(f"LW-05: search recording {path.name} is unreadable or malformed") from None

    def _write(self, path: Path, key: str, result: SearchResult, live: SearchProvider) -> None:
        payload = {"role": "search", "profile": self._profile_id, "key": key, "result": result.model_dump()}
        # PRD 16.1 rule 4: the adapter's own redact(), then the Authorization/Bearer backstop, on every string.
        redacted = redact_strings(payload, cast(Redactor, live))
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{key}.", suffix=".tmp")
        try:  # atomic: a crash or a concurrent reader never sees a truncated recording
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(redacted, indent=2, sort_keys=True) + "\n")
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def build_search_provider(
    role_id: str,
    config: ProvidersConfig,
    *,
    fixtures_dir: Path | str,
    profile_id: str | None = None,
    live_permitted: bool = False,
) -> SearchProvider:
    """`fake` gives the fake; `google` gives record-and-replay whose live adapter (Gemini grounding) is built lazily,
    only when a call goes live; a profile without `grounding` or any other adapter is refused (a search answered from
    memory would be a silent downgrade)."""
    profile_id = profile_id or config.roles[role_id].primary
    profile = config.profiles[profile_id]
    if Capability.GROUNDING.value not in profile.caps:
        raise ProviderConfigError(f"LW-05: search profile {profile_id!r} does not declare the grounding capability")
    if profile.provider == "fake":
        return FakeSearchProvider(profile_id)
    if profile.provider != "google":
        raise ProviderConfigError(f"LW-05: no search adapter for provider {profile.provider!r} ({profile_id!r})")

    def live_factory() -> SearchProvider:
        from tilo_providers.google_search_adapter import GoogleSearchProvider  # noqa: PLC0415  (replay never loads it)

        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise ProviderConfigError("LW-05: GOOGLE_CLOUD_PROJECT is not set; cannot search live")
        location = os.environ.get("GOOGLE_LOCATION", "global")  # PRD 6.5; the price region is checked at load
        return GoogleSearchProvider(profile, profile_id, project, location, live_permitted=live_permitted)

    return SearchRecordReplayProvider(profile_id, live_factory, fixtures_dir, live_permitted=live_permitted)
