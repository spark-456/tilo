"""tilo_connectors.errors — the exceptions the outbox and the adapters raise (tests/API.md, API_FR_CON_04_05.md)."""

from __future__ import annotations

from dataclasses import dataclass


class OutboxRefused(Exception):
    """Enqueue/cancel refusals — tests/API.md "Errors"."""


class MissingGrant(Exception):
    """SEC-03: no valid Grant for this send — tests/API.md "Errors"."""


class AdapterError(Exception):
    """Base of the Gmail and Drive adapter errors (re-exported by tilo_connectors.adapters).
    Its message never holds a token, a body or a full file name."""

    status: int | None = None  # the HTTP status Google answered, when there was one


class SideEffectRefused(AdapterError):
    """Final: the side effect can never succeed as written. The outbox marks the entry failed."""


class PossiblySent(SideEffectRefused):
    """Final, but an earlier attempt may have acted and the provider cannot be asked: the outbox marks the entry
    failed and alerts a person, who checks by hand. It is never retried."""


class RateLimited(AdapterError):
    """429 still answered after the attempts, or a Retry-After over 60 s. The outbox waits it out across ticks."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"rate limited; retry after {retry_after_s} s")
        self.retry_after_s = retry_after_s


class ProviderUnavailable(AdapterError):
    """5xx or a TransportError, still after the attempts: ambiguous, the provider may have acted."""


class SyncTokenExpired(AdapterError):
    """Google answered 410 to a request that carried a sync token (FR-CAL-08): the next sync lists in full."""

    status = 410


class CalendarConfigError(ValueError):
    """config/personal.yaml or the google_calendar entry is refused whole (FR-CAL-08). Names a key, never a value."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:500])


class CalendarSyncRefused(ValueError):
    """register(): a bad id, or the person is registered already under another org or world."""


class BuildPartnerConfigError(ValueError):
    """config/build_partners.yaml is refused whole (FR-CON-16, API_FR_CON_16_17_20.md). Names a key, never a value."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:500])


class HandoffRefused(ValueError):
    """A build handoff or a data grant is refused (BH-01..BH-09, DG-01..DG-05). Names the rule and ids only: never
    requirement, framing, excerpt or prompt text, a URL, or anything the redactor would remove."""

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"{rule}: {detail}"[:500])
        self.rule = rule


@dataclass(frozen=True)
class RouteOffer:
    route: str  # "mcp"
    available: bool  # False until FR-CON-18 ships
    reason: str


class BriefTooLong(HandoffRefused):
    """BH-06: the prompt or its link is over a limit. Nothing is ever cut."""

    def __init__(self, *, prompt_chars: int, link_length: int, max_prompt_chars: int, max_url_length: int) -> None:
        self.message = (
            f"This brief is too long for a Lovable link: the prompt is {prompt_chars:,} characters "
            f"(at most {max_prompt_chars:,}) and the link would be {link_length:,} characters "
            f"(at most {max_url_length:,}). Nothing was cut and nothing was sent. "
            "Lovable's connected route can take longer briefs, but it is not available yet."
        )
        super().__init__("BH-06", self.message)
        self.prompt_chars = prompt_chars
        self.link_length = link_length
        self.max_prompt_chars = max_prompt_chars
        self.max_url_length = max_url_length
        self.truncated = False
        self.alternatives = (RouteOffer("mcp", False, "unavailable until FR-CON-18"),)


class MeetingHostConfigError(ValueError):
    """The meeting_host config or declaration is refused whole (FR-MTG-09). Names a key, never a value."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:500])


class MeetingHostRefused(ValueError):
    """A bot-hosted meeting is refused (MH-01..MH-07; MH-20, MH-21 for join_link). Names the rule and ids only:
    never a title, an address, a time, a URL or a token."""

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"{rule}: {detail}"[:500])
        self.rule = rule
