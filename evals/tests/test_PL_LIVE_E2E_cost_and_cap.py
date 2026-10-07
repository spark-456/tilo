"""PL-LIVE-E2E (issue #340): cost control of `just live-e2e`. PRD 6.4 PL-03 (the router refuses a call over the
budget), PL-06 (prices come from config/prices.yaml), 14.1 (1 credit = US$0.005, from the prices file), 9.4 HR-1
(nothing without its event: a stopped run is never shown as completed), EFF-01.

Criteria covered:
  (1) a dry run prints the estimate first and makes no call; a live run prints the estimate before its first call;
  (2) default cap 40 credits (US$0.20), hard maximum 200; a larger or non-positive `--max-credits` is rejected before
      any call, in every mode;
  (3) at the cap the run stops honestly: outcome class `stopped_at_cap` naming the cap, exit 3, nothing over the cap
      ever sent, no `world.completed`, no `artifact.delivered`;
  (4) credits come from config/prices.yaml (the price per token and the credit's dollar value), never hard-coded.

Fake numbers: every profile costs US$1 per million tokens and each fake reply uses 1000 input and 500 output tokens,
so one call costs 0.3 credits. A normal B-007 run is a handful of calls and fits far under 40.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _live_e2e_lib import (
    ESTIMATE_RE,
    PROJECT,
    REFUSED_RE,
    STOP_RE,
    cli_args,
    env,
    invoke_main,
    live_e2e,
    live_run,
    network_guard,  # noqa: F401  (autouse fixture)
    run_direct,
    world_for,
    write_prices,
)


def test_PL_LIVE_E2E_06_default_cap_is_40_credits_and_the_hard_maximum_is_200() -> None:
    module = live_e2e()
    assert module.DEFAULT_MAX_CREDITS == 40.0
    assert module.HARD_MAX_CREDITS == 200.0
    assert module.DEFAULT_MAX_CREDITS * 0.005 == pytest.approx(0.20)  # US$0.20 at 1 credit = US$0.005 (PRD 14.1)


@pytest.mark.parametrize("value", ["200.01", "1000", "0", "-5", "nan", "inf"])
@pytest.mark.parametrize("mode", ["live", "dry-run", "replay"])
def test_PL_LIVE_E2E_06_a_cap_above_the_hard_maximum_or_not_positive_is_refused_before_any_call(
    value: str, mode: str, tmp_path: Path
) -> None:
    world = world_for()
    argv = cli_args(tmp_path, mode=mode, extra=("--max-credits", value))
    environ = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT} if mode == "live" else {}
    with env(**environ):
        result = invoke_main(argv, environ=environ or None, world=world)
    assert result.code == 2
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == "cap_out_of_range"
    assert "200" in match["message"]  # says what the maximum is
    assert world.built == [] and world.calls == []
    assert not (tmp_path / "recordings-out").exists()


def test_PL_LIVE_E2E_06_the_hard_maximum_itself_is_accepted(tmp_path: Path) -> None:
    world = world_for()
    with env():
        result = invoke_main(cli_args(tmp_path, mode="dry-run", max_credits=200.0), world=world)
    assert result.code == 0, result.err
    first = ESTIMATE_RE.match(result.out_lines()[0])
    assert first and float(first["cap"]) == 200.0


def test_PL_LIVE_E2E_07_dry_run_prints_the_estimate_first_and_makes_no_call(tmp_path: Path) -> None:
    world = world_for()
    with env():
        result = invoke_main(cli_args(tmp_path, mode="dry-run"), world=world)
    assert result.code == 0, result.err
    lines = result.out_lines()
    first = ESTIMATE_RE.match(lines[0])
    assert first, f"the first line must be the estimate, got {lines[:1]}"
    low, high, cap = float(first["low"]), float(first["high"]), float(first["cap"])
    assert 0 < low <= high
    assert cap == 40.0  # the default cap, shown with the estimate
    assert world.built == [] and world.calls == []
    assert not (tmp_path / "recordings-out").exists()  # a dry run writes nothing


def test_PL_LIVE_E2E_07_a_live_run_prints_the_estimate_before_its_first_model_call(tmp_path: Path) -> None:
    result, world, _ = live_run(tmp_path)
    assert result.code == 0, result.err
    assert world.stdout_at_first_call is not None, "no model call was made"
    printed = [line for line in world.stdout_at_first_call.splitlines() if line.strip()]
    assert printed and ESTIMATE_RE.match(printed[0]), f"stdout at the first call was {printed[:2]}"


def test_PL_LIVE_E2E_07_the_report_without_a_cap_flag_says_40(tmp_path: Path) -> None:
    result, _, _ = live_run(tmp_path)
    assert result.code == 0, result.err
    total = result.total()
    assert total is not None and float(total["cap"]) == 40.0
    assert float(total["credits"]) <= 40.0


def test_PL_LIVE_E2E_08_at_the_cap_the_run_stops_honestly_and_never_fakes_a_completion(tmp_path: Path) -> None:
    cap = 4.0  # a few fake calls: far too few for a whole run (the Director's 16384-token cap quotes ~3.3 credits)
    report, world = run_direct(tmp_path, max_credits=cap)
    assert report.outcome_class == "stopped_at_cap"
    assert "stopped_at_cap" in live_e2e().OUTCOME_CLASSES
    assert report.total_credits <= cap
    assert world.spent <= cap  # nothing over the cap was ever sent to the model
    assert len(world.calls) >= 1
    types = {event["type"] for event in report.events}
    assert "world.completed" not in types and "artifact.delivered" not in types  # HR-1: no faked completion
    assert report.reason and "cap" in report.reason.lower()


def test_PL_LIVE_E2E_08_the_cap_stop_exits_3_and_names_the_cap_on_stderr(tmp_path: Path) -> None:
    result, world, _ = live_run(tmp_path, max_credits=1.0)
    assert result.code == 3
    outcome = result.outcome()
    assert outcome and outcome["outcome"] == "stopped_at_cap"
    lines = result.err_lines()
    assert len(lines) == 1
    match = STOP_RE.match(lines[0])
    assert match and match["outcome"] == "stopped_at_cap"
    assert "cap" in match["message"].lower() and "1.0000" in match["message"]
    total = result.total()
    assert total is not None and float(total["credits"]) <= 1.0 and float(total["cap"]) == 1.0
    assert world.spent <= 1.0


def test_PL_LIVE_E2E_08_a_cap_below_the_first_call_makes_no_model_call_at_all(tmp_path: Path) -> None:
    report, world = run_direct(tmp_path, max_credits=0.01)
    assert report.outcome_class == "stopped_at_cap"
    assert world.calls == []
    assert report.total_credits == 0.0
    assert "world.completed" not in {event["type"] for event in report.events}


def test_PL_LIVE_E2E_09_credits_follow_the_prices_file_for_both_the_token_price_and_the_credit_value(
    tmp_path: Path,
) -> None:
    def credits(sub: str, per_million: float, credit_usd: float) -> tuple[float, dict[tuple[str, str], float]]:
        folder = tmp_path / sub
        folder.mkdir()
        result, world, _ = live_run(folder, per_million=per_million, credit_usd=credit_usd)
        assert result.code == 0, result.err
        by_row = {(m["stage"], m["role"]): float(m["credits"]) for m in result.rows()}
        assert by_row, "the report lists no rows"
        # exact, from the fake's own token counts and the file's own numbers (no hard-coded rate in the code)
        for m in result.rows():
            expected = int(m["calls"]) * ((1000 + 500) * per_million / 1e6) / credit_usd
            assert float(m["credits"]) == pytest.approx(expected, abs=1e-3), (m["stage"], m["role"])
        return float(result.total()["credits"]), by_row  # type: ignore[index]

    base_total, base_rows = credits("base", 1.0, 0.005)
    tripled_total, tripled_rows = credits("tripled", 3.0, 0.005)  # a 3x token price
    doubled_total, _ = credits("doubled", 1.0, 0.0025)  # a credit worth half as many dollars buys half as much
    assert base_total > 0
    assert tripled_total == pytest.approx(3 * base_total, rel=1e-3)
    assert doubled_total == pytest.approx(2 * base_total, rel=1e-3)
    assert tripled_rows.keys() == base_rows.keys()


def test_PL_LIVE_E2E_09_the_estimate_follows_the_prices_file_too(tmp_path: Path) -> None:
    def estimate(sub: str, per_million: float) -> tuple[float, float]:
        folder = tmp_path / sub
        folder.mkdir()
        prices = write_prices(folder, per_million=per_million)
        with env():
            result = invoke_main(cli_args(folder, mode="dry-run", prices=prices), world=world_for())
        match = ESTIMATE_RE.match(result.out_lines()[0])
        assert match, result.out
        return float(match["low"]), float(match["high"])

    low1, high1 = estimate("one", 1.0)
    low3, high3 = estimate("three", 3.0)
    assert low3 == pytest.approx(3 * low1, rel=1e-2)
    assert high3 == pytest.approx(3 * high1, rel=1e-2)


def test_PL_LIVE_E2E_09_no_credit_rate_is_hard_coded_in_the_module() -> None:
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.find_spec("tilo_evals.live_e2e")
    assert spec and spec.origin, "tilo_evals.live_e2e does not exist"
    source = Path(spec.origin).read_text(encoding="utf-8")
    assert "0.005" not in source  # the credit's dollar value is read from config/prices.yaml (PL-06)
    assert not re.search(r"\b(?:0\.75|3\.75|1\.50|7\.50)\b", source)  # nor any of the file's token prices
