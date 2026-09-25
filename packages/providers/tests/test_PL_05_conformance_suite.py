"""PL-05 (PRD 6.4): "Conformance suite per profile: schema adherence, tool
calling, repair rate, latency, safety handling." Acceptance test: "Runs
nightly; a failing profile cannot be assigned to a role."

Ticket P0-06 item 4: a runner executes the fixed set of checks per profile
against recordings or the fake provider in CI (live only with `LIVE=1`);
results are written to `config/conformance/<profile>.json` with a date and
a build; the config loader refuses a role whose primary or fallback profile
has a *failing* result; a *missing* result is allowed in dev with a warning,
and refused when `TILO_REQUIRE_CONFORMANCE=1`.

Ambiguity (docs/open-questions.md BQ-55): `load_providers_config` gains an
optional `conformance_dir` keyword. When omitted (as every P0-04 test that
predates this ticket already calls it), the conformance gate is skipped
entirely, so this ticket adds no new failure mode for config the loader
already accepted -- the gate only activates when a caller opts in by
passing a `conformance_dir` (production wiring passes `config/conformance`,
out of this package's unit-test scope). Result-file shape (own invention,
not a frozen `contracts/` schema): `{profile_id, date, build, checks:
{<CONFORMANCE_CHECK_NAMES>: "pass"|"fail"}, result: "pass"|"fail"}`.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from conftest import (
    CONFORMANCE_CHECK_NAMES,
    models_config,
    prices_config,
    write_conformance_result_file,
    write_providers_config,
)
from tilo_providers.config import ProviderConfigError, load_providers_config
from tilo_providers.interfaces import Capability


def test_PL_05_conformance_suite_runs_checks_and_writes_result_file(tmp_path):
    from tilo_providers.conformance import run_conformance_suite, write_conformance_result  # noqa: PLC0415
    from tilo_providers.fake import FakeModelProvider  # noqa: PLC0415

    provider = FakeModelProvider(profile_id="small", caps={Capability.JSON, Capability.TOOLS})

    result = run_conformance_suite("small", provider, build="test-build-1", today=date(2026, 9, 25))

    assert result["profile_id"] == "small"
    assert result["build"] == "test-build-1"
    assert result["date"] == "2026-09-25"
    assert set(result["checks"]) == set(CONFORMANCE_CHECK_NAMES)
    assert all(status in {"pass", "fail"} for status in result["checks"].values())
    assert result["result"] in {"pass", "fail"}

    written_path = write_conformance_result(result, tmp_path / "conformance")

    assert written_path == tmp_path / "conformance" / "small.json"
    assert json.loads(written_path.read_text(encoding="utf-8")) == result


def test_PL_05_role_with_failing_primary_conformance_result_rejected_at_load(tmp_path, monkeypatch):
    monkeypatch.delenv("TILO_REQUIRE_CONFORMANCE", raising=False)
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices_config(set_=True))
    conformance_dir = tmp_path / "config" / "conformance"
    write_conformance_result_file(conformance_dir, "large", result="fail")  # director's primary profile

    with pytest.raises(ProviderConfigError) as excinfo:
        load_providers_config(models_path, prices_path, conformance_dir=conformance_dir)

    message = str(excinfo.value)
    assert "director" in message, f"error must name the role, got: {message!r}"
    assert "large" in message, f"error must name the failing profile, got: {message!r}"


def test_PL_05_role_with_failing_fallback_conformance_result_rejected_at_load(tmp_path, monkeypatch):
    monkeypatch.delenv("TILO_REQUIRE_CONFORMANCE", raising=False)
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices_config(set_=True))
    conformance_dir = tmp_path / "config" / "conformance"
    write_conformance_result_file(conformance_dir, "small", result="fail")  # specialist's fallback profile

    with pytest.raises(ProviderConfigError) as excinfo:
        load_providers_config(models_path, prices_path, conformance_dir=conformance_dir)

    message = str(excinfo.value)
    assert "specialist" in message, f"error must name the role, got: {message!r}"
    assert "small" in message, f"error must name the failing profile, got: {message!r}"


def test_PL_05_missing_conformance_result_allowed_in_dev_with_warning(tmp_path, monkeypatch):
    monkeypatch.delenv("TILO_REQUIRE_CONFORMANCE", raising=False)
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices_config(set_=True))
    conformance_dir = tmp_path / "config" / "conformance"  # deliberately empty: no profile has run yet

    with pytest.warns(UserWarning):
        config = load_providers_config(models_path, prices_path, conformance_dir=conformance_dir)

    assert config.roles["director"].primary == "large"


def test_PL_05_missing_conformance_result_refused_when_require_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("TILO_REQUIRE_CONFORMANCE", "1")
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices_config(set_=True))
    conformance_dir = tmp_path / "config" / "conformance"  # still empty

    with pytest.raises(ProviderConfigError):
        load_providers_config(models_path, prices_path, conformance_dir=conformance_dir)


def _probe_provider(error: Exception | None):
    """A fake that answers every prompt normally, except the safety probe, where it raises `error`
    (or, with `error=None`, answers the unsafe probe normally too)."""
    from tilo_providers.fake import FakeModelProvider  # noqa: PLC0415
    from tilo_providers.prompts import load_prompt  # noqa: PLC0415

    probe = load_prompt("conformance", "safety_probe.md")

    class ProbeProvider(FakeModelProvider):
        def generate(self, request):
            if error is not None and request.prompt == probe:
                raise error
            return super().generate(request)

    return ProbeProvider(profile_id="small", caps={Capability.JSON, Capability.TOOLS})


@pytest.mark.parametrize("error", [None, "request_error"], ids=["answers_unsafe_prompt", "raises_request_error"])
def test_PL_05_safety_handling_fails_unless_the_unsafe_prompt_is_blocked(error):
    from tilo_providers.conformance import run_conformance_suite  # noqa: PLC0415
    from tilo_providers.errors import RequestError  # noqa: PLC0415

    provider = _probe_provider(RequestError("400 bad request") if error else None)

    result = run_conformance_suite("small", provider, build="test-build-1", today=date(2026, 9, 25))

    assert result["checks"]["safety_handling"] == "fail"
    assert result["result"] == "fail"


def test_PL_05_safety_handling_passes_when_the_unsafe_prompt_raises_safety_error():
    from tilo_providers.conformance import run_conformance_suite  # noqa: PLC0415
    from tilo_providers.errors import SafetyError  # noqa: PLC0415

    provider = _probe_provider(SafetyError("blocked on safety grounds"))

    result = run_conformance_suite("small", provider, build="test-build-1", today=date(2026, 9, 25))

    assert result["checks"]["safety_handling"] == "pass"
