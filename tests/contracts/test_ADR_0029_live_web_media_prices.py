"""ADR-0029 (Proposed, 2026-10-08): live web search, fetch, media input and prices. providers 1.3.0 (unit_price,
cached_input, valid_until, region, reserve_units, media_tokens, video and documents), artifact 1.1.0 (the fetch
origin), common 1.6.0 (the app deliverable format) and appspec 1.0.0 (the quiz kind). All additive: every shipped
config file and every older fixture stays valid."""

from __future__ import annotations

import pytest
import yaml
from _lib import errors_for, load_json, load_schema

FIXTURES = "contracts/fixtures"
INVALID = {
    "providers": (
        *("unit_price_unknown_unit", "unit_price_negative_per_1k", "unit_price_without_per_1k"),
        *("prices_set_with_null_per_1k", "prices_set_with_null_cached_input", "negative_cached_input"),
        *("valid_until_not_a_date", "valid_until_null", "region_not_a_location", "region_with_trailing_newline"),
        *("reserve_units_zero", "media_tokens_without_video", "media_tokens_zero_image", "capability_url_context"),
    ),
    "artifact": (
        *("fetch_origin_with_markdown", "fetch_without_source", "fetch_with_two_sources"),
        *("fetch_origin_without_agent", "fetch_origin_without_unit", "fetch_key_without_f_marker"),
        *("fetch_without_idempotency_key", "fetch_key_eleventh_file", "unit_output_with_fetch_key"),
        "render_output_with_fetch_key",
    ),
    "appspec": (
        *("v_not_1_0", "kind_not_quiz", "no_questions", "timer_under_a_minute", "stem_empty"),
        *("answer_not_an_option", "answer_upper_case", "options_skip_a_letter", "option_id_g", "one_option"),
        *("question_without_source", "source_with_url", "page_zero", "question_id_zero", "script_field"),
    ),
    "common": ("deliverable_format_html",),
}
VALID = {
    "providers": ("search_role_unit_price_region_and_media", "prices_unset_with_null_cached_input_and_per_1k"),
    "artifact": ("fetch_pdf_from_the_web",),
    "appspec": ("quiz_three_questions", "true_false_one_question"),
    "common": ("deliverable_format_app",),
}


def _version(schema):
    return tuple(int(p) for p in schema["x-version"].split("."))


def _config(repo_root, name):
    return yaml.safe_load((repo_root / "config" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,minimum", [("providers", (1, 3, 0)), ("artifact", (1, 1, 0)), ("common", (1, 6, 0))])
def test_PL_06_FR_AGT_16_additive_bumps_stay_on_major_1(repo_root, name, minimum):
    version = _version(load_schema(repo_root, name))
    assert version >= minimum and version[0] == 1


@pytest.mark.parametrize("folder,name", [(f, n) for f, names in VALID.items() for n in names])
def test_PL_06_FR_AGT_16_valid_fixtures_pass(repo_root, registry, folder, name):
    doc = load_json(repo_root / f"{FIXTURES}/{folder}/valid/{name}.json")
    assert not errors_for(load_schema(repo_root, folder), doc, registry)


@pytest.mark.parametrize("folder,name", [(f, n) for f, names in INVALID.items() for n in names])
def test_PL_06_FR_AGT_16_each_rule_has_an_invalid_fixture_that_fails(repo_root, registry, folder, name):
    doc = load_json(repo_root / f"{FIXTURES}/{folder}/invalid/{name}.json")
    assert errors_for(load_schema(repo_root, folder), doc, registry), f"{folder}/invalid/{name}.json must fail"


def test_PL_06_a_price_gains_unit_price_cached_input_and_valid_until_and_stays_two_field(repo_root):
    schema = load_schema(repo_root, "providers")
    price = schema["$defs"]["price"]
    assert price["required"] == ["input", "output"], "every new field is optional"
    assert {"cached_input", "unit_price", "valid_until"} <= set(price["properties"])
    assert schema["$defs"]["unit_price"]["properties"]["unit"]["enum"] == ["query", "minute", "character", "image"]
    assert "reserve_units" in schema["$defs"]["role"]["properties"]
    assert "region" not in schema["$defs"]["prices"]["required"]
    assert {"video", "documents"} <= set(schema["$defs"]["capability"]["enum"])


def test_PL_06_the_price_draft_meters_regional_rates_with_dated_promotions(repo_root):
    prices = _config(repo_root, "prices.yaml")
    assert (prices["status"], prices["effective_date"], prices["region"]) == ("set", "2026-10-08", "asia-southeast1")
    profiles = prices["profiles"]
    for flash in ("flash-38", "flash-37", "search-google"):
        assert (profiles[flash]["input"], profiles[flash]["output"]) == (0.825, 4.125)
        assert (profiles[flash]["cached_input"], profiles[flash]["valid_until"]) == (0.0825, "2026-12-31")
    assert profiles["search-google"]["unit_price"] == {"unit": "query", "per_1k": 14}
    assert profiles["lite-31"] == {"input": 0.275, "output": 1.65, "cached_input": 0.0275, "audio_input": 0.55}
    assert "valid_until" not in profiles["lite-31"], "lite has no promotion"
    assert profiles["tts-flash"] == {"input": 0.50, "output": 9.00, "valid_until": "2026-12-31"}


def test_PL_03_PRD_12_2_the_search_role_is_grounded_reserved_and_never_falls_back_to_memory(repo_root):
    models, prices = _config(repo_root, "models.yaml"), _config(repo_root, "prices.yaml")["profiles"]
    search = models["roles"]["search"]
    assert search["reserve_units"] >= 1 and search["max_output_tokens"] > 1024
    for profile_id in {search["primary"], search["fallback"], *search.get("cascade", ())}:
        assert "grounding" in models["profiles"][profile_id]["caps"]
        assert prices[profile_id]["unit_price"]["unit"] == "query"
    for role_id, role in models["roles"].items():  # a unit fee needs a reservation (ADR-0029 decision 1)
        used = {role["primary"], role.get("fallback"), *role.get("cascade", ())} - {None}
        if any("unit_price" in prices.get(p, {}) for p in used):
            assert "reserve_units" in role, f"role {role_id!r} pays a unit fee but reserves none"


def test_FR_INT_02_every_google_model_profile_states_media_tokens_and_reads_documents(repo_root):
    profiles = _config(repo_root, "models.yaml")["profiles"]
    media = {"image": 1120, "pdf_page": 1120, "audio_per_second": 25, "video_per_second": 258}
    for profile_id in ("flash-38", "flash-37", "lite-31"):
        assert profiles[profile_id]["media_tokens"] == media
        assert {"vision", "audio", "video", "documents"} <= set(profiles[profile_id]["caps"])


def test_PRD_12_2_the_web_connector_reads_only_and_its_tiers_agree_with_the_table(repo_root, registry):
    connectors = {c["id"]: c for c in _config(repo_root, "connectors.yaml")}
    web = connectors["web"]
    assert not errors_for(load_schema(repo_root, "connector"), web, registry)
    assert (web["auth"], web["scopes"], web["data_class"]["returns"]) == ("none", {}, ["public"])
    actions = {a["id"]: a for a in web["actions"]}
    assert set(actions) == {"web_search", "fetch_url"}
    table = _config(repo_root, "autonomy.yaml")["actions"]
    for action_id, action in actions.items():
        assert (action["risk_tier"], action["gate_type"], action["irreversible"]) == ("T1", "none", False)
        assert table[action_id] == "T1", "listed, so a search never falls to the unlisted-is-T3 default"
    assert list(connectors)[-1] == "web", "after every gated connector (the dev Director picks the first gate)"


def test_FR_INT_01_a_fetched_file_is_a_file_with_one_source_from_its_own_run(repo_root, registry):
    record = load_json(repo_root / f"{FIXTURES}/artifact/valid/fetch_pdf_from_the_web.json")
    assert record["origin"]["kind"] == "fetch" and record["idempotency_key"].endswith(":f0")
    assert [s["archive_ref"].split("/")[0] for s in record["sources"]] == [record["run_id"]]
    schema = load_schema(repo_root, "artifact")
    for media in ("text/markdown", "application/json", "text/html", "image/svg+xml"):
        assert errors_for(schema, {**record, "media_type": media, "size_bytes": 1200}, registry), media


def test_FR_AGT_16_the_app_format_and_the_quiz_spec_carry_no_code_or_links(repo_root, registry):
    common = load_schema(repo_root, "common")
    assert "app" in common["$defs"]["deliverable_format"]["enum"]
    spec = load_schema(repo_root, "appspec")
    assert spec["title"] == "AppSpec" and spec["properties"]["kind"] == {"const": "quiz"}
    quiz = load_json(repo_root / f"{FIXTURES}/appspec/valid/quiz_three_questions.json")
    for field in ("html", "script", "url", "css"):
        assert errors_for(spec, {**quiz, field: "x"}, registry), field
    question = quiz["questions"][0]
    for answer in "abcdef":
        options = {k: f"option {k}" for k in "abcdef"[: max(2, "abcdef".index(answer) + 1)]}
        ok = {**quiz, "questions": [{**question, "options": options, "answer": answer}]}
        assert not errors_for(spec, ok, registry), answer
        if answer not in "ab":
            short = {k: v for k, v in options.items() if k != answer}
            bad = {**quiz, "questions": [{**question, "options": short, "answer": answer}]}
            assert errors_for(spec, bad, registry), f"answer {answer} names no option"
