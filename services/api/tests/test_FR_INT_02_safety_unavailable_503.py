"""FR-INT-02: a live safety screen that cannot run (no GOOGLE_CLOUD_PROJECT, a bad location, a replay miss, a
provider error) closes the screened routes with 503, never 500. The live Model Armor factory is lazy, so its
`ProviderConfigError` surfaces from `check()`, inside the route."""

from __future__ import annotations

import pytest
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.replay import ReplayMissError


class _Unavailable(SafetyProvider):
    def __init__(self, error: Exception) -> None:
        self._error = error

    def _check(self, text, *, content, mime_type):
        raise self._error


_ERRORS = [
    ProviderConfigError("FR-INT-02: GOOGLE_CLOUD_PROJECT is not set"),
    ReplayMissError("no recording"),
    ProviderError("unavailable"),
]


@pytest.mark.parametrize("error", _ERRORS, ids=lambda e: type(e).__name__)
def test_FR_INT_02_intake_answers_503_when_the_safety_screen_cannot_run(client, error):
    from tilo_api.intake import get_safety

    client.app.dependency_overrides[get_safety] = lambda: _Unavailable(error)

    response = client.post("/intake", data={"text": "Plan the onboarding."})

    assert response.status_code == 503, response.text


@pytest.mark.parametrize("error", _ERRORS, ids=lambda e: type(e).__name__)
def test_FR_INT_02_task_edit_screen_answers_503_when_the_safety_screen_cannot_run(error):
    from fastapi import HTTPException
    from tilo_api.tasks import _screen

    with pytest.raises(HTTPException) as excinfo:
        _screen(_Unavailable(error), ["a new line for the brief"])

    assert excinfo.value.status_code == 503
