"""VERTEX-EVAL-1, PR 1a (interface half): `EvalProvider`, its pydantic request/result types, the
deterministic `FakeEvalProvider`, `build_eval_provider`, and the dev/conformance config wiring.
Written before the implementation (docs/design/VERTEX-EVAL-1.md sections 2.1, 2.2, 5 tests 1-6 and 15;
docs/adr/0033-eval-provider-gen-ai-evaluation-service.md; PRD 6.3, 6.4 PL-01/PL-04/PL-06, 6.6 EFF-01).

Public interfaces under test (all lazily imported, so each test fails on its own while they are missing):
- `tilo_providers.interfaces`: `EvalItem`, `EvalRequest`, `EvalScore`, `EvalProvider` (design 2.1).
- `tilo_providers.evaluation`: `EVAL_ROLE`, `FakeEvalProvider`, `build_eval_provider(config, *, live_permitted=False)`.
- `config/models.dev.yaml`, `config/prices.yaml`, and `tilo_providers.conformance.main`.

Ambiguities resolved (listed in the report):
- Pairwise/pointwise disagreement is a `RequestError` (design 2.1). It may be raised when the request is built or
  when `evaluate()` is called, so the tests wrap both. Bad id/metric/kind/extra keys are pydantic
  `ValidationError`s (the design's `Field(pattern=...)` / `Literal` / `extra="forbid"`).
- The fake's pointwise score is 0.0 or 1.0 (design 1.1: the groundedness score is 0 or 1 and the runner treats
  anything else as an error row, so a fake that runs the whole pipeline must emit only those two).
- Which pairwise choice or score the fake derives from sha256(metric|id) is not pinned, only that it is
  deterministic, depends on nothing else, and varies across ids.
- The dev profile's model id is not pinned (design 2.2 names only `eval-fake`, provider `fake`, and the role).
"""

from __future__ import annotations

import math
from typing import Any

import pytest
import yaml
from conftest import REPO_ROOT, build_providers_config, prices_config_for
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from tilo_providers.config import ProviderConfigError, load_providers_config
from tilo_providers.errors import RequestError

FAKE_EXPLANATION = "fake judgement (dev stand-in)"
CHOICES = {"candidate", "baseline", "tie"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(name, raising=False)


# --- helpers ------------------------------------------------------------------------------------


def _item(**overrides: Any):
    from tilo_providers.interfaces import EvalItem  # noqa: PLC0415

    fields: dict[str, Any] = {"id": "case-1", "prompt": "Plan the launch", "context": "", "response": "plan A"}
    fields.update(overrides)
    return EvalItem(**fields)


def _request(kind: str = "pointwise", *, metric: str | None = None, item: Any = None, **item_overrides: Any):
    from tilo_providers.interfaces import EvalRequest  # noqa: PLC0415

    if item is None:
        if kind == "pairwise" and "baseline_response" not in item_overrides:
            item_overrides["baseline_response"] = "plan B"
        item = _item(**item_overrides)
    return EvalRequest(
        metric=metric if metric is not None else ("plan_pairwise" if kind == "pairwise" else "plan_groundedness"),
        kind=kind,
        template="Judge the response. Rubric text, sent as is.",
        item=item,
    )


def _evaluate(provider: Any, kind: str = "pointwise", **overrides: Any):
    return provider.evaluate(_request(kind, **overrides))


def _eval_config(*, primary_provider: str = "fake", fallback_provider: str | None = None, with_role: bool = True):
    """In-memory providers config with an `eval_judge` role. The fallback (if different) is another profile."""
    profiles: dict[str, Any] = {
        "judge-primary": {"provider": primary_provider, "model": "fake-judge-1", "context": 1_000_000, "caps": []},
    }
    fallback = "judge-primary"
    if fallback_provider is not None:
        profiles["judge-fallback"] = {
            "provider": fallback_provider,
            "model": "fake-judge-2",
            "context": 1_000_000,
            "caps": [],
        }
        fallback = "judge-fallback"
    # without the eval role the config still needs some role: give it an unrelated one
    role_id = "eval_judge" if with_role else "narrator"
    models = {
        "example": True,
        "profiles": profiles,
        "roles": {role_id: {"primary": "judge-primary", "fallback": fallback}},
        "rules": {"deny": []},
    }
    return build_providers_config(models, prices_config_for({pid: (0.0, 0.0) for pid in profiles}))


def _build(config: Any, **kwargs: Any):
    from tilo_providers.evaluation import build_eval_provider  # noqa: PLC0415

    return build_eval_provider(config, **kwargs)


def _fake():
    from tilo_providers.evaluation import FakeEvalProvider  # noqa: PLC0415

    return FakeEvalProvider()


# --- (1) request validation ---------------------------------------------------------------------


def test_VERTEX_EVAL_1_request_kind_and_fields_must_agree():
    """Design 2.1: a request whose kind and fields disagree is a RequestError (fails closed, nothing sent)."""
    provider = _fake()
    with pytest.raises(RequestError):  # pairwise without a baseline
        _evaluate(provider, "pairwise", baseline_response=None)
    with pytest.raises(RequestError):  # pointwise with a baseline
        _evaluate(provider, "pointwise", baseline_response="plan B")

    # the matching shapes are accepted
    assert _evaluate(provider, "pairwise", baseline_response="plan B").choice in CHOICES
    assert _evaluate(provider, "pointwise").score is not None


@pytest.mark.parametrize("bad_id", ["", "a b", "x" * 65, "a/b", "id\n", "café", "../x", "a.b"])
def test_VERTEX_EVAL_1_item_id_pattern_is_enforced(bad_id):
    with pytest.raises(ValidationError):
        _item(id=bad_id)


@pytest.mark.parametrize("good_id", ["a", "Case_1-x", "x" * 64, "G-001"])
def test_VERTEX_EVAL_1_item_id_pattern_accepts_valid_ids(good_id):
    assert _item(id=good_id).id == good_id


@pytest.mark.parametrize("bad_metric", ["", "Plan", "1abc", "a-b", "a" * 42, "plan pairwise", "plan\n", "_x"])
def test_VERTEX_EVAL_1_metric_pattern_is_enforced(bad_metric):
    with pytest.raises(ValidationError):
        _request("pointwise", metric=bad_metric)


@pytest.mark.parametrize("good_metric", ["a", "plan_pairwise", "a" * 41, "p9_x"])
def test_VERTEX_EVAL_1_metric_pattern_accepts_valid_metrics(good_metric):
    assert _request("pointwise", metric=good_metric).metric == good_metric


def test_VERTEX_EVAL_1_types_are_closed_pydantic_models():
    from tilo_providers.interfaces import EvalRequest, EvalScore  # noqa: PLC0415

    with pytest.raises(ValidationError):
        _item(surprise="x")
    with pytest.raises(ValidationError):
        EvalRequest(metric="m", kind="pointwise", template="t", item=_item(), surprise="x")
    with pytest.raises(ValidationError):
        EvalRequest(metric="m", kind="listwise", template="t", item=_item())
    with pytest.raises(ValidationError):
        EvalScore(choice="candidate", surprise="x")


# --- (2) result shape ---------------------------------------------------------------------------


def test_VERTEX_EVAL_1_score_shape_must_match_kind():
    """Design 2.1: a choice only for pairwise, a finite score only for pointwise."""
    from tilo_providers.interfaces import EvalScore  # noqa: PLC0415

    provider = _fake()
    pairwise = _evaluate(provider, "pairwise")
    assert pairwise.choice in CHOICES
    assert pairwise.score is None

    pointwise = _evaluate(provider, "pointwise")
    assert pointwise.choice is None
    assert isinstance(pointwise.score, float)
    assert math.isfinite(pointwise.score)
    assert pointwise.score in (0.0, 1.0)  # design 1.1: groundedness is scored 0 or 1

    with pytest.raises(ValidationError):  # the choice is one of three fixed words
        EvalScore(choice="winner")
    assert EvalScore(choice="tie").explanation == ""  # explanation is optional


# --- (3) the fake -------------------------------------------------------------------------------


def test_VERTEX_EVAL_1_fake_is_deterministic_and_labelled():
    from tilo_providers.interfaces import EvalProvider, ModelProvider  # noqa: PLC0415

    first, second = _fake(), _fake()
    assert isinstance(first, EvalProvider)
    assert not isinstance(first, ModelProvider)  # a sibling interface, not a model (ADR-0033)

    for kind in ("pairwise", "pointwise"):
        a = _evaluate(first, kind)
        assert a == _evaluate(first, kind), "same request, same instance"
        assert a == _evaluate(second, kind), "same request, new instance"
        assert a.explanation == FAKE_EXPLANATION, "visibly fake: the fixed stand-in text"

    # the verdict comes from sha256(metric|id) only: the texts do not move it
    base = _evaluate(first, "pairwise", id="case-7")
    changed = _evaluate(
        first, "pairwise", id="case-7", prompt="other", context="ctx", response="other", baseline_response="other"
    )
    assert changed == base

    # ... and it does vary with the id and the metric (not a constant)
    choices = {_evaluate(first, "pairwise", id=f"case-{n}").choice for n in range(40)}
    scores = {_evaluate(first, "pointwise", id=f"case-{n}").score for n in range(40)}
    assert len(choices) >= 2
    assert scores == {0.0, 1.0}
    by_metric = {first.evaluate(_request("pointwise", metric=f"metric_{n}", id="case-1")).score for n in range(40)}
    assert len(by_metric) == 2

    assert first.redact("nothing to scrub") == "nothing to scrub"  # the base-class no-op


@settings(max_examples=60, deadline=None)
@given(
    item_id=st.from_regex(r"[A-Za-z0-9_-]{1,64}", fullmatch=True),
    metric=st.from_regex(r"[a-z][a-z0-9_]{0,40}", fullmatch=True),
    kind=st.sampled_from(["pairwise", "pointwise"]),
    text=st.text(max_size=80),
)
def test_VERTEX_EVAL_1_fake_is_a_pure_function_of_metric_and_id(item_id, metric, kind, text):
    """Invariant: any valid request gets a well-shaped, repeatable, text-independent result."""
    extra = {"baseline_response": "b" + text} if kind == "pairwise" else {}
    a = _fake().evaluate(_request(kind, metric=metric, id=item_id, response=text, **extra))
    b = _fake().evaluate(_request(kind, metric=metric, id=item_id, response="different", **extra))
    assert a == b
    assert a.explanation == FAKE_EXPLANATION
    if kind == "pairwise":
        assert a.choice in CHOICES and a.score is None
    else:
        assert a.choice is None and a.score in (0.0, 1.0)


# --- (4)-(6) the builder ------------------------------------------------------------------------


def test_VERTEX_EVAL_1_eval_role_is_eval_judge():
    from tilo_providers.evaluation import EVAL_ROLE  # noqa: PLC0415

    assert EVAL_ROLE == "eval_judge"


def test_VERTEX_EVAL_1_build_gives_the_fake_for_a_fake_primary():
    from tilo_providers.evaluation import FakeEvalProvider  # noqa: PLC0415

    provider = _build(_eval_config())
    assert isinstance(provider, FakeEvalProvider)
    assert _evaluate(provider, "pointwise").explanation == FAKE_EXPLANATION


def test_VERTEX_EVAL_1_build_refuses_fake_when_live_or_deployed(monkeypatch):
    """EFF-01 / design 2.2: the fake is refused when the live switch is on, or when K_SERVICE or CLOUD_RUN_JOB is
    present at all (even empty: Cloud Run can set a variable to an empty string)."""
    config = _eval_config()
    assert _build(config) is not None  # control: builds with a clean environment

    monkeypatch.setenv("LIVE", "1")
    with pytest.raises(ProviderConfigError):
        _build(config)
    monkeypatch.delenv("LIVE")

    for name in ("K_SERVICE", "CLOUD_RUN_JOB"):
        for value in ("", "svc"):
            monkeypatch.setenv(name, value)
            with pytest.raises(ProviderConfigError):
                _build(config)
            monkeypatch.delenv(name)


def test_VERTEX_EVAL_1_build_reads_primary_only():
    """Like `safety` (BQ-68): the fallback profile is never built, so a bad one is not even looked at, and a
    failing primary is never covered for by a fallback."""
    from tilo_providers.evaluation import FakeEvalProvider  # noqa: PLC0415

    # a fallback that could not be built does not matter: only the primary is read
    provider = _build(_eval_config(primary_provider="fake", fallback_provider="no_such_kind"))
    assert isinstance(provider, FakeEvalProvider)

    # a primary that cannot be built (a live adapter without the live switch) is an error, not a quiet fake
    with pytest.raises(ProviderConfigError):
        _build(_eval_config(primary_provider="vertex_eval", fallback_provider="fake"))


def test_VERTEX_EVAL_1_build_refuses_unknown_provider_or_missing_role():
    for kind in ("no_such_kind", "model_armor", "openai_compat", "google"):
        with pytest.raises(ProviderConfigError):
            _build(_eval_config(primary_provider=kind))
    with pytest.raises(ProviderConfigError):
        _build(_eval_config(with_role=False))


# --- (15) dev config and conformance ------------------------------------------------------------


def _yaml(relative: str) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8"))


def test_VERTEX_EVAL_1_dev_models_file_has_priced_fake_judge_and_conformance_skips_it(monkeypatch, tmp_path, capsys):
    from tilo_providers import config as config_module  # noqa: PLC0415
    from tilo_providers import conformance, factory  # noqa: PLC0415
    from tilo_providers.evaluation import FakeEvalProvider  # noqa: PLC0415

    # dev models file: a fake `eval-fake` profile under the `eval_judge` role, primary and fallback the same (NFR-25)
    dev = _yaml("config/models.dev.yaml")
    assert dev["profiles"]["eval-fake"]["provider"] == "fake"
    assert dev["roles"]["eval_judge"]["primary"] == "eval-fake"
    assert dev["roles"]["eval_judge"]["fallback"] == "eval-fake"

    # priced at zero ("makes no paid call"), and the whole dev config loads and builds the fake
    entry = _yaml("config/prices.yaml")["profiles"]["eval-fake"]
    assert entry["input"] == 0 and entry["output"] == 0
    loaded = load_providers_config(REPO_ROOT / "config" / "models.dev.yaml", REPO_ROOT / "config" / "prices.yaml")
    assert isinstance(_build(loaded), FakeEvalProvider)

    # `just conformance` (PL-05 is for ModelProviders only): `vertex_eval` and `model_armor` profiles are skipped,
    # a model profile is still run
    models = {
        "example": True,
        "profiles": {
            "large": {"provider": "fake", "model": "fake-large-1", "context": 1_000_000, "caps": ["json"]},
            "vertex-eval": {"provider": "vertex_eval", "model": "fake-judge-1", "context": 1_000_000, "caps": []},
            "armor-default": {"provider": "model_armor", "model": "tilo-default", "context": 1_000_000, "caps": []},
        },
        "roles": {
            "director": {"primary": "large", "fallback": "large"},
            "eval_judge": {"primary": "vertex-eval", "fallback": "vertex-eval"},
            "safety": {"primary": "armor-default", "fallback": "armor-default"},
        },
        "rules": {"deny": []},
    }
    config = build_providers_config(
        models, prices_config_for({"large": (1.0, 2.0), "vertex-eval": (1.0, 2.0), "armor-default": (0.1, 0.0)})
    )
    built: list[str] = []
    written: list[str] = []
    monkeypatch.setattr(config_module, "load_providers_config", lambda *args, **kwargs: config)

    def spy_build(role_id: str, cfg: Any, *, fixtures_dir: Any, profile_id: str) -> object:
        built.append(profile_id)
        return object()

    monkeypatch.setattr(factory, "build_provider", spy_build)
    monkeypatch.setattr(
        conformance,
        "run_conformance_suite",
        lambda profile_id, provider, **kwargs: {"profile_id": profile_id, "result": "pass"},
    )
    monkeypatch.setattr(
        conformance,
        "write_conformance_result",
        lambda result, directory: written.append(result["profile_id"]) or tmp_path / "unused.json",
    )

    assert conformance.main() == 0

    assert built == ["large"], "only the ModelProvider profile is built for the conformance suite"
    assert written == ["large"]
    output = capsys.readouterr().out
    assert "vertex-eval" in output and "armor-default" in output and "skipped" in output
