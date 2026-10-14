"""BQ-M2-4, ADR-0042 decision 9 (MV-09, MV-15): the meter's numbers come from `config/` and nowhere else. The shipped
config gives a ceiling of max(8 x 256, 4 x 400) = 2048 tokens and a hold TTL of 3 x 20 s; the Live profile has no price
row yet (BQ-M2-8), so a reply books the whole unit. No network, no paid call."""

from __future__ import annotations

import math
import shutil
from pathlib import Path

import pytest
from _mv_lib import UNIT, cost_usd

ROOT = Path(__file__).resolve().parents[3]


def _priced(tokens_in: int, tokens_out: int) -> int:
    """The expected minor units, from the one rate the API prices with (never a literal)."""
    from tilo_api.spend_units import INR_MINOR_PER_USD

    return max(1, math.ceil(cost_usd(tokens_in, tokens_out) * INR_MINOR_PER_USD))


def test_BQ_M2_4_MV_15_the_shipped_config_gives_the_documented_ceiling_ttl_cap_and_unit():
    from tilo_api import meeting_voice_meter as meter

    cfg = meter.load_meter_config()
    assert (cfg.ceiling, cfg.hold_ttl_s, cfg.max_reserves) == (2048, 60.0, 400)
    assert cfg.caps.unit_reserve_minor == 1000  # config/spend_caps.yaml, untouched
    assert meter._ceiling_fits(cfg)


def test_BQ_M2_4_MV_09_the_live_profile_has_no_price_row_so_any_usage_books_the_whole_unit():
    from tilo_api import meeting_voice_meter as meter

    cfg = meter.load_meter_config()
    usage = {"prompt_token_count": 10, "response_token_count": 10}
    assert meter.bounded_minor(cfg, usage, 1000) is None  # None is the whole unit in `LiveVoiceSpend.settle`


@pytest.mark.parametrize(
    "tokens,chars,ceiling", [(256, 400, 2048), (512, 400, 4096), (64, 2000, 8000), (2048, 400, 16384)]
)
def test_BQ_M2_4_MV_15_the_ceiling_follows_max_output_tokens_and_max_chars(tmp_path, tokens, chars, ceiling):
    from tilo_api import meeting_voice_meter as meter

    for name in ("models.yaml", "spend_caps.yaml", "meeting.yaml"):
        shutil.copy(ROOT / "config" / name, tmp_path / name)
    text = (ROOT / "config" / "voice.yaml").read_text(encoding="utf-8")
    text = text.replace("max_output_tokens: 256", f"max_output_tokens: {tokens}").replace(
        "max_chars: 400", f"max_chars: {chars}"
    )
    (tmp_path / "voice.yaml").write_text(text, encoding="utf-8")
    assert meter.load_meter_config(tmp_path).ceiling == ceiling


def test_BQ_M2_4_MV_17_the_hold_ttl_is_three_times_the_live_timeout(tmp_path):
    from tilo_api import meeting_voice_meter as meter

    for name in ("models.yaml", "spend_caps.yaml", "meeting.yaml"):
        shutil.copy(ROOT / "config" / name, tmp_path / name)
    text = (ROOT / "config" / "voice.yaml").read_text(encoding="utf-8")
    (tmp_path / "voice.yaml").write_text(text.replace("timeout_s: 20", "timeout_s: 60"), encoding="utf-8")
    assert meter.load_meter_config(tmp_path).hold_ttl_s == 180.0  # the loader's maximum timeout: 3 x 60 s


def test_BQ_M2_4_MV_15_a_priced_live_profile_is_priced_up_and_capped_at_the_unit():
    from tilo_api import meeting_voice_meter as meter
    from tilo_api.spend import SpendCaps

    caps = SpendCaps(
        uid_lifetime_minor=1000, run_minor=1000, org_day_minor=None, global_day_hard_minor=5000,
        unit_reserve_minor=UNIT, rate_limit_requests=10, rate_limit_window_s=60,
    )  # fmt: skip
    cfg = meter.MeterConfig(caps=caps, ceiling=2048, hold_ttl_s=60.0, max_reserves=400, cost_usd=cost_usd)
    assert meter.bounded_minor(cfg, {"prompt_token_count": 100, "response_token_count": 100}, UNIT) == _priced(100, 100)
    assert meter.bounded_minor(cfg, {"prompt_token_count": 2048, "response_token_count": 2048}, UNIT) == _priced(
        2048, 2048
    )
    assert meter.bounded_minor(cfg, {"prompt_token_count": 2049}, UNIT) is None
    assert meter.bounded_minor(cfg, {}, UNIT) is None
