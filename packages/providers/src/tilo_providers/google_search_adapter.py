"""tilo_providers.google_search_adapter — the live SearchProvider: Gemini grounding on Agent Platform (LW-05, ADR-0029
decision 7). One `generate_content` call whose only tool is `google_search`; the URL-context tool is refused (a fetch
goes through tilo-browser, LW-08). The reply maps onto `SearchResult`: the answer, the cited sources (redirect URLs
cleaned, never fetched or resolved here), the queries run, the search-suggestion HTML, and `usage.search_queries` from
`grounding_metadata.web_search_queries` (left out when the reply carries no list: unknown, never 0). Client building,
the `LIVE=1` gate, settings checks, safety and truncation mapping and token usage are `GoogleModelProvider`'s; tests
inject `client=` and never reach the network."""

from __future__ import annotations

from typing import Any

from tilo_contracts import ProvidersProfile

from tilo_providers.config import ProviderConfigError
from tilo_providers.diagnostics import log_caught
from tilo_providers.google_adapter import GoogleModelProvider
from tilo_providers.interfaces import Capability, SearchProvider
from tilo_providers.prompts import load_prompt
from tilo_providers.search import (
    MAX_CITATION_TEXT,
    MAX_CITATIONS,
    SearchCitation,
    SearchResult,
    SearchSource,
    clean_source_url,
    prepare_search,
    redact_query,
    refuse_other_tools,
)


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class GoogleSearchProvider(SearchProvider):
    def __init__(
        self,
        profile: ProvidersProfile,
        profile_id: str,
        project: str,
        location: str,
        client: Any | None = None,
        live_permitted: bool = False,
    ) -> None:
        if Capability.GROUNDING.value not in profile.caps:
            raise ProviderConfigError(f"LW-05: search profile {profile_id!r} does not declare the grounding capability")
        self._profile_id, self._model_id = profile_id, profile.model
        self._google = GoogleModelProvider(
            profile=profile,
            profile_id=profile_id,
            project=project,
            location=location,
            client=client,
            live_permitted=live_permitted,
        )

    def redact(self, text: str) -> str:
        return redact_query(text)  # a superset of the Google token scrub

    def search(self, query: str, **kwargs: Any) -> SearchResult:
        request = prepare_search(query, kwargs)
        config: dict[str, Any] = {
            "tools": [{"google_search": {}}],
            "system_instruction": load_prompt("search", "ground.md"),
        }
        if request.max_output_tokens is not None:
            config["max_output_tokens"] = request.max_output_tokens
        refuse_other_tools(config["tools"])
        try:
            response = self._google._client.models.generate_content(
                model=self._model_id, contents=request.query, config=config
            )
        except Exception as error:
            log_caught(error, __name__, locals())
            failure = self._google._failure(error)
        else:
            return self._result(request.query, response)
        raise failure

    def _result(self, query: str, response: Any) -> SearchResult:
        reply = self._google._map_response(response)  # SafetyError, OutputTruncatedError, usage and cached tokens
        candidates = getattr(response, "candidates", None) or []
        metadata = getattr(candidates[0], "grounding_metadata", None) if candidates else None
        usage = reply.usage
        queries = getattr(metadata, "web_search_queries", None)
        if isinstance(queries, list):  # the billing unit: one per entry, as Gemini reports them
            usage = {**(usage or {}), "search_queries": len(queries)}
        sources: dict[str, SearchSource] = {}
        position: dict[int, int] = {}  # the provider's chunk index -> index in `sources` (a refused chunk has none)
        for index, chunk in enumerate(getattr(metadata, "grounding_chunks", None) or []):
            web = getattr(chunk, "web", None)
            url = clean_source_url(getattr(web, "uri", None))
            if url is None:
                continue
            if url not in sources:
                sources[url] = SearchSource(
                    title=_text_or_none(getattr(web, "title", None)),
                    domain=_text_or_none(getattr(web, "domain", None)),
                    redirect_url=url,
                )
            position[index] = list(sources).index(url)
        entry_point = getattr(metadata, "search_entry_point", None)
        return SearchResult(
            query=query,
            answer=reply.text or "",
            sources=list(sources.values()),
            citations=self._citations(metadata, position),
            queries=[q for q in queries if isinstance(q, str)] if isinstance(queries, list) else [],
            suggestions_html=_text_or_none(getattr(entry_point, "rendered_content", None)),
            profile_id=self._profile_id,
            usage=usage,
        )

    @staticmethod
    def _citations(metadata: Any, position: dict[int, int]) -> list[SearchCitation]:
        """GOOGLE-MAX: `grounding_supports` as claim-to-source links. A support whose chunks are all unusable is left
        out; an index points into the returned `sources`, never into the provider's raw chunk list."""
        citations: list[SearchCitation] = []
        for support in getattr(metadata, "grounding_supports", None) or []:
            segment = getattr(support, "segment", None)
            start, end = getattr(segment, "start_index", None) or 0, getattr(segment, "end_index", None)
            chunks = getattr(support, "grounding_chunk_indices", None) or []
            linked = sorted({position[i] for i in chunks if isinstance(i, int) and i in position})
            if not linked or not isinstance(end, int) or end < start:
                continue
            text = (_text_or_none(getattr(segment, "text", None)) or "")[:MAX_CITATION_TEXT]
            citations.append(SearchCitation(start=start, end=end, text=text, sources=linked))
            if len(citations) == MAX_CITATIONS:
                break
        return citations
