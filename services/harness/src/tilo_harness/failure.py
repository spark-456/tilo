"""A unit whose runner raised still says why it stopped (RUN-FAIL-1).

`crash_reason` turns the error into a plain, code-written line for `UnitOutcome.reason` (and so the run's
`world.failed`, at most 140 characters); `error_trail` names the error classes and the Router's attempts for the
ERROR log line. Both read class names and profile ids only, never an error's text: that text can quote a prompt,
a tool result or a provider's message.
"""

from __future__ import annotations

from tilo_providers.router import (
    BudgetExceededError,
    RouterCredentialError,
    RouterError,
    RouterExhaustedError,
    RouterRequestError,
    RouterSafetyError,
    StreamInterruptedError,
    TokenCapExceededError,
)

REASON_CAP = 140  # world.failed data.reason maxLength
_REASONS: tuple[tuple[type[BaseException], str], ...] = (  # most specific first
    (BudgetExceededError, "a step's model call did not fit the credits left in the run's budget"),
    (TokenCapExceededError, "a step's input was over its model's input limit"),
    (RouterRequestError, "the model service refused a step's request"),
    (RouterSafetyError, "the model service blocked a step on safety grounds"),
    (RouterCredentialError, "the model service refused the credentials for a step"),
    (StreamInterruptedError, "a step's model reply broke off"),
    (RouterExhaustedError, "no model could answer a step"),
    (RouterError, "a step's model call failed"),
)
_MAX_CHAIN = 4


def crash_reason(error: BaseException) -> str:
    """The plain line for a unit whose work raised `error`."""
    for kind, reason in _REASONS:
        if isinstance(error, kind):
            return reason
    return f"a step stopped on an internal error ({type(error).__name__})"[:REASON_CAP]


def error_trail(error: BaseException) -> str:
    """`RouterRequestError <- RequestError; attempts: lite-31 RequestError`: class names and profile ids only."""
    names: list[str] = []
    seen: BaseException | None = error
    while seen is not None and len(names) < _MAX_CHAIN:
        names.append(type(seen).__name__)
        seen = seen.__cause__
    attempts = [
        f"{getattr(a, 'profile_id', '?')} {getattr(a, 'error_type', None) or getattr(a, 'outcome', '?')}"
        for a in (getattr(error, "attempts", None) or [])
    ]
    return " <- ".join(names) + (f"; attempts: {', '.join(attempts)}" if attempts else "")
