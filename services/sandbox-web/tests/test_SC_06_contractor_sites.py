"""SC-06 kitchen-renovation contractors (PRD 4.3 SC-06, 6.2): quote arithmetic is generic; nothing is stored."""

from __future__ import annotations

import re

import pytest
from _sandbox_web_testlib import SC06_SLUGS, all_scalars, load_seed, visible_text


@pytest.mark.parametrize("slug", SC06_SLUGS)
def test_SC_06_profile_shows_the_seeds_own_details(client, slug):
    seed = load_seed(slug)
    resp = client.get(f"/s/{slug}/profile")
    assert resp.status_code == 200
    text = visible_text(resp.text)
    for scalar in all_scalars(seed["pages"]["profile"]):
        assert scalar in text, f"{slug}/profile is missing seed value {scalar!r}"


@pytest.mark.parametrize("slug", SC06_SLUGS)
@pytest.mark.parametrize("sqft,cabinets", [(200, 10), (0, 0), (1500, 40)])
def test_SC_06_quote_is_deterministic_generic_arithmetic(client, slug, sqft, cabinets):
    rate_card = load_seed(slug)["rate_card"]
    expected = rate_card["base_fee"] + rate_card["per_sqft"] * sqft + rate_card["per_cabinet"] * cabinets
    body = {"sqft": sqft, "cabinets": cabinets}

    first = client.post(f"/s/{slug}/quote", json=body)
    second = client.post(f"/s/{slug}/quote", json=body)

    assert first.status_code == 200
    assert first.json()["quote"] == pytest.approx(expected)
    assert second.json() == first.json()
    assert set(first.json()) == {"quote"}, "no submitted-data id or timestamp is ever echoed back"


_BAD_QUOTE_BODIES = ['{"sqft": -5, "cabinets": 2}', '{"cabinets": 2}', "{}", '{"sqft": NaN, "cabinets": 1}']
_BAD_QUOTE_BODIES += ['{"sqft": Infinity, "cabinets": 1}', '{"sqft": 1e308, "cabinets": 1e308}']
_BAD_QUOTE_BODIES += [f'{{"sqft": 1{"0" * 400}, "cabinets": 1}}']  # 400-digit int


@pytest.mark.parametrize("slug", SC06_SLUGS)
@pytest.mark.parametrize("raw", _BAD_QUOTE_BODIES)
def test_SC_06_quote_rejects_invalid_and_non_finite_input(client, slug, raw):
    resp = client.post(f"/s/{slug}/quote", content=raw, headers={"content-type": "application/json"})
    assert resp.status_code == 422


@pytest.mark.parametrize("slug", SC06_SLUGS)
def test_SC_06_rendered_quote_form_submits_as_form_data(client, slug):
    rc = load_seed(slug)["rate_card"]
    assert re.findall(r'<input name="([^"]+)"', client.get(f"/s/{slug}/quote").text) == ["sqft", "cabinets"]
    resp = client.post(f"/s/{slug}/quote", data={"sqft": "10", "cabinets": "2"})
    assert resp.status_code == 200
    assert resp.json()["quote"] == pytest.approx(rc["base_fee"] + 10 * rc["per_sqft"] + 2 * rc["per_cabinet"])
    assert client.post(f"/s/{slug}/quote", data={"sqft": "ten", "cabinets": "2"}).status_code == 422
