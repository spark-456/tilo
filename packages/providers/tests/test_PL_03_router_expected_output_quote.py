"""PL-03 / EFF-03, follow-up to the budget quote (8 Oct 2026): a call is reserved at its input plus the role's EXPECTED
output, not its full `max_output_tokens`, so a writer call (cap 16384, really ~1.6 credits) is not refused while the
budget could pay for it.

* Refused before sending only when (a) input + expected output does not fit the budget left, or (b) input + the full
  cap is over twice the budget left.
* Anything that passes both is sent; it may settle above its reserve, and the budget is clamped at 0, never negative
  (a returned call, a truncated call).
* The expected size comes from `config/expected_output.yaml` (contracts/providers.schema.json forbids a new role
  field), loaded next to the models file; a role without one expects min(cap, 1024).

Scripted providers only: no network, no live call. Prices: 2 USD per million tokens out, 1 in; 1 credit = US$0.005,
so the 16384-token cap is ~6.55 credits and 3000 expected tokens ~1.2.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml
from conftest import (
    REPO_ROOT,
    ScriptedCall,
    ScriptedModelProvider,
    models_config,
    prices_config,
    write_providers_config,
)
from tilo_providers.config import ProviderConfigError, load_providers_config, resolve_models_path
from tilo_providers.errors import OutputTruncatedError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import BudgetExceededError, Router, RouterError

_CAP, _EXPECTED = 16384, 3000


def _config(tmp_path: pathlib.Path, expected: dict | None = None, cap: int = _CAP):
    models, prices = models_config(), prices_config(set_=True)
    models["roles"]["writer"] = {"primary": "medium", "fallback": "medium", "max_output_tokens": cap}
    prices["profiles"]["medium"] = {"input": 1.0, "output": 2.0}
    models_path, prices_path = write_providers_config(tmp_path, models, prices)
    if expected is not None:
        (models_path.parent / "expected_output.yaml").write_text(yaml.safe_dump({"roles": expected}), encoding="utf-8")
    return load_providers_config(models_path, prices_path)


def _credits(config, tokens_in: int, tokens_out: int) -> float:
    return config.credits((tokens_in * 1.0 + tokens_out * 2.0) / 1e6)


def _send(config, budget: float, *, usage=None, error=None):
    provider = ScriptedModelProvider(
        "medium", [ScriptedCall(text="ok", usage=usage, error=error, outcome="ok" if error is None else "error")]
    )
    router = Router(config, provider_for_profile={"medium": provider, "small": provider}.__getitem__)
    return provider, lambda: router.generate("writer", GenerateRequest(prompt="Write the note."), budget=budget)


def test_PL_03_a_writer_with_a_16384_cap_is_sent_when_its_expected_output_fits_five_credits(tmp_path):
    config = _config(tmp_path, {"writer": _EXPECTED})
    assert _credits(config, 3, _CAP) > 5.0 > _credits(config, 3, _EXPECTED), "the full cap would have been refused"
    provider, run = _send(config, 5.0, usage={"input_tokens": 3, "output_tokens": 1500})

    result = run()

    assert len(provider.calls) == 1 and provider.calls[0].max_output_tokens == _CAP, "the hard cap is still sent"
    assert result.budget == pytest.approx(5.0 - _credits(config, 3, 1500)), (
        "settled from the real usage, not the reserve"
    )


def test_PL_03_refused_before_sending_when_input_plus_expected_output_does_not_fit(tmp_path):
    config = _config(tmp_path, {"writer": _EXPECTED})
    provider, run = _send(config, _credits(config, 3, _EXPECTED) * 0.9)

    with pytest.raises(BudgetExceededError):
        run()

    assert provider.calls == []


def test_PL_03_refused_before_sending_when_the_cap_is_over_twice_the_budget_left(tmp_path):
    config = _config(tmp_path, {"writer": _EXPECTED})
    cap_cost = _credits(config, 3, _CAP)
    refused, run_refused = _send(config, cap_cost / 2 * 0.99)  # the expected output fits; the cap does not fit twice
    sent, run_sent = _send(config, cap_cost / 2 * 1.01, usage={"input_tokens": 3, "output_tokens": 10})

    with pytest.raises(BudgetExceededError):
        run_refused()
    run_sent()

    assert refused.calls == [] and len(sent.calls) == 1


def test_PL_03_the_budget_never_goes_negative_after_a_reply_dearer_than_its_reserve(tmp_path):
    config = _config(tmp_path, {"writer": _EXPECTED})
    _, run = _send(config, 3.4, usage={"input_tokens": 3, "output_tokens": _CAP})  # settles at ~6.5 credits

    result = run()

    assert result.budget == 0.0


def test_PL_03_the_budget_never_goes_negative_after_a_truncated_call(tmp_path):
    config = _config(tmp_path, {"writer": _EXPECTED})
    cut = OutputTruncatedError("PL-02: the reply hit its max_output_tokens cap", input_tokens=3, output_tokens=_CAP)
    _, run = _send(config, 3.4, error=cut)

    with pytest.raises(RouterError) as raised:
        run()

    assert raised.value.budget_left == 0.0


def test_PL_03_a_truncated_call_with_no_usage_is_charged_the_cap_it_burned_not_its_reserve(tmp_path):
    config = _config(tmp_path, {"writer": _EXPECTED})
    cut = OutputTruncatedError("PL-02: the reply hit its max_output_tokens cap")
    _, run = _send(config, 5.0, error=cut)

    with pytest.raises(RouterError) as raised:
        run()

    assert raised.value.budget_left == 0.0, "a cut reply used the whole cap (~6.5 credits), more than the 5 left"


def test_PL_03_a_role_without_an_expected_size_expects_min_of_its_cap_and_1024(tmp_path):
    config = _config(tmp_path)  # no expected_output.yaml at all
    assert config.expected_output == {}
    cap_cost, small_cost = _credits(config, 3, _CAP), _credits(config, 3, 1024)
    provider, run = _send(config, cap_cost / 2 * 1.01, usage={"input_tokens": 3, "output_tokens": 10})

    run()

    assert small_cost < cap_cost / 2, "1024 fits where the cap fits only within twice the headroom"
    assert len(provider.calls) == 1


def test_PL_03_an_expected_size_above_a_calls_own_lower_cap_is_clamped_to_that_cap(tmp_path):
    config = _config(tmp_path, {"writer": _EXPECTED})
    provider = ScriptedModelProvider("medium", [ScriptedCall(text="ok", usage={"input_tokens": 3, "output_tokens": 5})])
    router = Router(config, provider_for_profile={"medium": provider, "small": provider}.__getitem__)

    router.generate(
        "writer",
        GenerateRequest(prompt="Write the note.", max_output_tokens=100),
        budget=_credits(config, 3, 100) * 1.01,
    )

    assert len(provider.calls) == 1, "expected = min(3000, the request's own cap of 100)"


# --- the config file ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [{"writer": 0}, {"writer": "3000"}, {"writer": True}, {"writer": _CAP + 1}, {"writer": 2.5}],
    ids=["zero", "string", "bool", "over-the-cap", "float"],
)
def test_PL_03_expected_output_must_be_an_integer_from_1_up_to_the_roles_max_output_tokens(tmp_path, bad):
    with pytest.raises(ProviderConfigError, match="expected_output"):
        _config(tmp_path, bad)


def test_PL_03_expected_output_yaml_must_be_a_mapping_of_roles(tmp_path):
    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices_config(set_=True))
    (models_path.parent / "expected_output.yaml").write_text("- 1\n", encoding="utf-8")
    with pytest.raises(ProviderConfigError, match="expected_output"):
        load_providers_config(models_path, prices_path)


def test_PL_03_a_role_missing_from_the_models_file_is_ignored(tmp_path):
    config = _config(tmp_path, {"writer": _EXPECTED, "not_in_this_models_file": 50})
    assert config.expected_output["writer"] == _EXPECTED


def test_PL_03_the_repos_expected_output_names_real_roles_and_fits_their_caps():
    config = load_providers_config(resolve_models_path(REPO_ROOT, env={}), REPO_ROOT / "config" / "prices.yaml")
    assert config.expected_output["writer"] == _EXPECTED
    assert {"director", "lead", "specialist", "verifier", "writer", "narrator"} <= set(config.expected_output)
    raw = yaml.safe_load((REPO_ROOT / "config" / "expected_output.yaml").read_text(encoding="utf-8"))
    assert set(raw["roles"]) <= set(config.roles), "a typo'd role name would be ignored silently"
    for role_id, tokens in config.expected_output.items():
        cap = config.roles[role_id].max_output_tokens
        assert cap is None or tokens <= cap
