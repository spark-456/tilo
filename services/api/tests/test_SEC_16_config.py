"""SEC-16, the config half: "a lifetime spend cap of 1,000 INR per uid (config)" and a per-uid rate limit, "both from
config" (PRD supplement 4, SEC-16). FR-MTR-04: the caps come from config, never from code. All money is an integer in
minor units (paise), never a float (PRD 14.1).

`tilo_api.spend.load_spend_caps(path=None) -> SpendCaps` reads `config/spend_caps.yaml` (see API_SEC_16.md for the keys)
and refuses anything unusable; no literal cap lives in code. Written from the PRD text before any builder touches it:
tests/SEC-16-spend-caps.
"""

from __future__ import annotations

import io
import pathlib
import tokenize

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "config" / "spend_caps.yaml"
API_SRC = REPO_ROOT / "services" / "api" / "src" / "tilo_api"

GOOD = {
    "currency": "INR",
    "uid_lifetime_minor": 100_000,
    "run_minor": 20_000,
    "org_day_minor": None,
    "global_day_hard_minor": 2_000_000,
    "rate_limit_requests": 30,
    "rate_limit_window_s": 60,
}


def load(path):
    from tilo_api.spend import load_spend_caps

    return load_spend_caps(path)


def write(tmp_path, **changes):
    doc = {**GOOD, **changes}
    doc = {k: v for k, v in doc.items() if v is not ...}  # `...` removes a key
    path = tmp_path / "spend_caps.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def test_SEC_16_the_shipped_config_gives_each_uid_a_lifetime_cap_of_1000_inr_in_minor_units():
    assert CONFIG.is_file(), "config/spend_caps.yaml is missing: the caps must come from config"
    caps = load(None)  # the default path is the shipped file
    assert caps.uid_lifetime_minor == 100_000, "1,000 INR is 100,000 paise (PRD supplement SEC-16)"
    for name in ("run_minor", "global_day_hard_minor", "rate_limit_requests", "rate_limit_window_s"):
        value = getattr(caps, name)
        assert type(value) is int and value > 0, f"{name} must be a positive integer, got {value!r}"
    assert caps.org_day_minor is None or (type(caps.org_day_minor) is int and caps.org_day_minor > 0)
    assert caps.run_minor <= caps.uid_lifetime_minor, "one run may not cost more than a person's whole lifetime"
    assert caps.uid_lifetime_minor <= caps.global_day_hard_minor


def test_SEC_16_the_shipped_config_declares_inr_and_only_the_pinned_keys():
    doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert doc["currency"] == "INR"
    assert set(doc) == set(GOOD), f"unexpected or missing keys: {set(doc) ^ set(GOOD)}"


def test_SEC_16_a_good_file_loads_exactly_what_it_says(tmp_path):
    caps = load(write(tmp_path, uid_lifetime_minor=777, org_day_minor=9_999))
    assert (caps.uid_lifetime_minor, caps.org_day_minor) == (777, 9_999)
    assert (caps.rate_limit_requests, caps.rate_limit_window_s) == (30, 60)
    assert load(write(tmp_path)).org_day_minor is None, "only the per-org daily cap may be null (ADR-0002 decision 13)"


@pytest.mark.parametrize(
    "bad",
    [
        {"uid_lifetime_minor": None},  # the person's cap is never optional
        {"uid_lifetime_minor": 0},
        {"uid_lifetime_minor": -1},
        {"uid_lifetime_minor": 1000.0},  # money is an integer, a float is refused even when whole
        {"uid_lifetime_minor": 1000.5},
        {"uid_lifetime_minor": True},
        {"uid_lifetime_minor": "100000"},
        {"run_minor": None},
        {"run_minor": 0},
        {"global_day_hard_minor": None},
        {"global_day_hard_minor": 0},
        {"org_day_minor": 0},
        {"org_day_minor": -5},
        {"org_day_minor": 1.5},
        {"rate_limit_requests": 0},
        {"rate_limit_requests": 2.5},
        {"rate_limit_window_s": 0},
        {"rate_limit_window_s": -60},
        {"currency": "USD"},  # the cap is in INR (SEC-16); another currency needs its own decision
        {"currency": ...},
        {"uid_lifetime_minor": ...},
        {"rate_limit_requests": ...},
        {"unknown_key": 1},  # same strictness as the other config files: no unknown keys
    ],
)
def test_SEC_16_an_unusable_config_is_refused_not_defaulted(tmp_path, bad):
    path = write(tmp_path, **bad)
    with pytest.raises(ValueError):
        load(path)


@pytest.mark.parametrize("content", ["", "- a\n- b\n", "just text", "!!python/object/apply:os.system ['x']"])
def test_SEC_16_a_config_that_is_not_a_mapping_or_uses_tags_is_refused(tmp_path, content):
    path = tmp_path / "spend_caps.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load(path)


def test_SEC_16_a_missing_config_file_refuses_rather_than_uncapping(tmp_path):
    with pytest.raises((OSError, ValueError)):
        load(tmp_path / "nope.yaml")


def test_SEC_16_no_cap_number_is_written_in_code():
    """FR-MTR-04 / SEC-16: the caps are config. No source file of tilo-api may carry the 1,000 INR cap as a literal
    (100000 paise, in any spelling), so raising a cap is a config edit and a reviewable one."""
    offenders = []
    for path in sorted(API_SRC.rglob("*.py")):
        tokens = tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
        for token in tokens:
            if token.type == tokenize.NUMBER:
                try:
                    value = float(token.string.replace("_", ""))
                except ValueError:
                    continue
                if value == 100_000:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{token.start[0]}: {token.string}")
    assert offenders == [], f"a cap literal in code: {offenders}"
