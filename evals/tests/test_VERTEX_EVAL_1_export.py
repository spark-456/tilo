"""VERTEX-EVAL-1 (PR 1b; design 3.2 `export`, 4.1 redaction before export; PRD 16.1 rule 4, 19.3):
`python -m tilo_evals vertex-eval export --candidate DIR [--baseline DIR] ...` is free, pairs two bank-format folders
by case id, writes a local pairs file, and redacts every string before it caps it.

Criteria covered (design section 5 numbers): 22 pairing by id and identical inputs, skip reasons; 23 order by id, the
case cap, labels, no folder paths written; 24 secrets and personal data never reach the bytes; 25 redact before cap;
26 control and format characters stripped, oversize fields refused; 27 deterministic, LF; 40 (export part) no ADC and
no provider.
Ambiguities resolved (design silent): a "null Director reply" is a director whose brief, approaches and plan are all
null (reason `no_output`); one-sided cases are skipped with a non-empty reason that differs per side (the exact words
are not pinned); the pairs file keys are listed in `_vertex_eval_lib.py`; the case cap applies after skipping, but these
tests keep every skipped case outside the first `max_cases` so either reading passes.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from unittest import mock

import pytest
import yaml
from _vertex_eval_lib import (
    CORES,
    NO_OUTPUT,
    TRUNCATED,
    assert_refused,
    compact,
    director_of,
    export_argv,
    ids_of,
    invoke,
    leaks,
    load_pairs,
    network_guard,  # noqa: F401  (autouse fixture)
    planted,
    write_case,
    write_settings,
    write_side,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SECRET_FOLDERS = ("secret-baseline-folder-9", "secret-candidate-folder-9")


def _folders(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / SECRET_FOLDERS[0], tmp_path / SECRET_FOLDERS[1]


def _export(tmp_path: Path, candidate: Path, baseline: Path | None = None, **kw):
    result = invoke(export_argv(tmp_path, candidate, baseline, **kw))
    return result, tmp_path / "pairs.local.yaml"


# --- 22: pairing -----------------------------------------------------------------------------------------------------


def test_VERTEX_EVAL_1_export_pairs_by_id_and_identical_inputs(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    write_side(base, "BASE", ["B-001", "B-002", "B-003", "B-005"])
    write_side(cand, "CAND", ["B-001", "B-002", "B-003", "B-004"])
    # B-001: identical inputs, different Director output: paired. B-002: the candidate's brief differs: inputs_differ.
    write_case(cand, "B-002", brief="A different brief altogether.", director=director_of("CAND", "B-002"))
    # B-003: the candidate has no Director output: no_output. B-004 is only in the candidate, B-005 only in the base.
    write_case(cand, "B-003", brief="Brief for B-003: plan a small neighbourhood event.", director=NO_OUTPUT)
    # same files and answers on both sides, in a different mapping order: still the same inputs
    files = [{"name": "sales.csv", "text": "a,b\n1,2\n"}]
    answers = {"q1": "yes", "q2": "no"}
    write_case(base, "B-006", brief="Six", director=director_of("BASE", "B-006"), files=files, answers=answers)
    write_case(
        cand,
        "B-006",
        brief="Six",
        director=director_of("CAND", "B-006"),
        files=files,
        answers=dict(reversed(answers.items())),
    )
    # B-007: only the answers differ: inputs_differ
    write_case(base, "B-007", brief="Seven", director=director_of("BASE", "B-007"), answers={"q1": "yes"})
    write_case(cand, "B-007", brief="Seven", director=director_of("CAND", "B-007"), answers={"q1": "no"})

    result, out = _export(tmp_path, cand, base, extra=("--max-cases", "20"))
    assert result.code == 0, result.err
    doc = load_pairs(out)
    assert [p["id"] for p in doc["pairs"]] == ["B-001", "B-006"]
    by_id = {p["id"]: p for p in doc["pairs"]}
    assert by_id["B-001"]["candidate_response"] == compact(director_of("CAND", "B-001"))
    assert by_id["B-001"]["baseline_response"] == compact(director_of("BASE", "B-001"))
    skipped = {s["id"]: s["reason"] for s in doc["skipped"]}
    assert skipped["B-002"] == "inputs_differ"
    assert skipped["B-007"] == "inputs_differ"
    assert skipped["B-003"] == "no_output"
    assert skipped["B-004"] and skipped["B-005"] and skipped["B-004"] != skipped["B-005"]  # one-sided, per side
    assert set(skipped) == {"B-002", "B-003", "B-004", "B-005", "B-007"}
    assert not ({p["id"] for p in doc["pairs"]} & set(skipped))


def test_VERTEX_EVAL_1_export_fields_are_prompt_context_and_response(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    files = [
        {"name": "sales.csv", "text": "region,total\nnorth,10\n"},
        {"name": "costs.csv", "text": "item,cost\nrent,5\n"},
    ]
    answers = {"audience": "the board", "deadline": None}
    for folder, side in ((base, "BASE"), (cand, "CAND")):
        write_case(
            folder,
            "B-001",
            brief="Plan the autumn fair.",
            director=director_of(side, "B-001"),
            files=files,
            answers=answers,
        )
    result, out = _export(tmp_path, cand, base)
    assert result.code == 0, result.err
    (row,) = load_pairs(out)["pairs"]
    assert "Plan the autumn fair." in row["prompt"] and "the board" in row["prompt"]  # the brief plus the answers
    for name, text in (("sales.csv", "region,total\nnorth,10\n"), ("costs.csv", "item,cost\nrent,5\n")):
        assert name in row["context"] and text.strip() in row["context"]  # the files' text, each under its name
    assert row["context"].index("sales.csv") < row["context"].index("costs.csv")
    assert row["candidate_response"] == compact(director_of("CAND", "B-001"))  # sort_keys, compact JSON
    assert row["baseline_response"] == compact(director_of("BASE", "B-001"))
    assert set(row) == {"id", "prompt", "context", "candidate_response", "baseline_response"}


def test_VERTEX_EVAL_1_export_without_baseline_writes_groundedness_rows_only(tmp_path: Path) -> None:
    _, cand = _folders(tmp_path)
    write_side(cand, "CAND", ids_of(3))
    result, out = _export(tmp_path, cand)
    assert result.code == 0, result.err
    doc = load_pairs(out)
    assert [p["id"] for p in doc["pairs"]] == ids_of(3)
    assert all(not p.get("baseline_response") for p in doc["pairs"])
    assert doc["baseline_label"] is None and doc["candidate_label"] == "candidate"


def test_VERTEX_EVAL_1_export_default_labels_and_given_labels(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    write_side(base, "BASE", ids_of(2))
    write_side(cand, "CAND", ids_of(2))
    _, out = _export(tmp_path, cand, base)
    doc = load_pairs(out)
    assert (doc["baseline_label"], doc["candidate_label"]) == ("baseline", "candidate")
    result, out = _export(
        tmp_path, cand, base, extra=("--candidate-label", "After fix 1.2", "--baseline-label", "scripted_bank-v2")
    )
    assert result.code == 0, result.err
    doc = load_pairs(out)
    assert (doc["baseline_label"], doc["candidate_label"]) == ("scripted_bank-v2", "After fix 1.2")


@pytest.mark.parametrize(
    "label", ["", "x" * 41, "a/b", "a\\b", "bad;label", "tab\there", "line\nbreak", "ünï", "<script>"]
)
@pytest.mark.parametrize("flag", ["--candidate-label", "--baseline-label"])
def test_VERTEX_EVAL_1_export_refuses_a_bad_label(flag: str, label: str, tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    write_side(base, "BASE", ids_of(1))
    write_side(cand, "CAND", ids_of(1))
    result, out = _export(tmp_path, cand, base, extra=(flag, label))
    assert_refused(result)
    assert not out.exists()


def test_VERTEX_EVAL_1_export_exit_2_for_bad_folder_no_pair_or_bad_arguments(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    write_side(base, "BASE", ["B-001"])
    write_side(cand, "CAND", ["B-002"])  # no id in common
    out = tmp_path / "pairs.local.yaml"
    empty = tmp_path / "empty"
    empty.mkdir()
    bad_case = tmp_path / "badbank"
    bad_case.mkdir()
    (bad_case / "B-001.yaml").write_bytes(b"id: B-001\nunknown_key: true\n")  # fails the bank schema
    attempts = {
        "no pair": export_argv(tmp_path, cand, base),
        "missing candidate folder": export_argv(tmp_path, tmp_path / "nope", base),
        "missing baseline folder": export_argv(tmp_path, cand, tmp_path / "nope"),
        "a candidate that is a file": export_argv(tmp_path, cand / "B-002.yaml", base),
        "an invalid case file": export_argv(tmp_path, bad_case, base),
        "max cases zero": export_argv(tmp_path, base, base, extra=("--max-cases", "0")),
        "max cases negative": export_argv(tmp_path, base, base, extra=("--max-cases", "-2")),
        "max cases text": export_argv(tmp_path, base, base, extra=("--max-cases", "many")),
        "an empty folder": export_argv(tmp_path, empty, base),
    }
    for label, argv in attempts.items():
        result = invoke(argv)
        assert_refused(result)
        assert not out.exists(), label


# --- 23: order, case cap, no paths ----------------------------------------------------------------------------------


def test_VERTEX_EVAL_1_export_orders_by_id_caps_cases_and_writes_no_paths(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    ids = ["G-001", "B-009", "B-002", "B-001", "B-005", "B-004", "G-002", "B-003"]
    write_side(base, "BASE", ids)
    write_side(cand, "CAND", ids)
    for explicit in (("--max-cases", "3"), ()):
        result, out = _export(tmp_path, cand, base, extra=explicit, settings=write_settings(tmp_path, max_cases=5))
        assert result.code == 0, result.err
        got = [p["id"] for p in load_pairs(out)["pairs"]]
        assert got == sorted(ids)[: int(explicit[1]) if explicit else 5]  # the flag, else the settings' max_cases
    text = out.read_bytes().decode("utf-8")
    for needle in (*SECRET_FOLDERS, str(tmp_path), tmp_path.as_posix(), str(tmp_path).replace("\\", "\\\\")):
        assert needle not in text, f"a path was written: {needle}"
    assert Path.home().as_posix() not in text.replace("\\", "/")


def test_VERTEX_EVAL_1_export_default_max_cases_is_the_settings_value(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    ids = ids_of(6)
    write_side(base, "BASE", ids)
    write_side(cand, "CAND", ids)
    _, out = _export(tmp_path, cand, base, settings=write_settings(tmp_path, max_cases=4))
    assert [p["id"] for p in load_pairs(out)["pairs"]] == ids[:4]


# --- 24-26: redaction ------------------------------------------------------------------------------------------------


def _loaded_with_secrets(tmp_path: Path) -> tuple[Path, Path]:
    secrets = planted()
    base, cand = _folders(tmp_path)
    brief = (
        f"Mail {secrets['email']} or call {secrets['phone']}. Token {secrets['oauth']} and key {secrets['apikey']}. "
        f"Also {secrets['sk']} then {secrets['bearer']} and {secrets['labelled']}. Project {secrets['project']} "
        f"at {secrets['adc']}."
    )
    answers = {"contact": f"write to {secrets['email']}", "secret": secrets["labelled"]}
    files = [
        {"name": "notes.csv", "text": f"who,what\n{secrets['email']},{secrets['oauth']}\n{secrets['project']},x\n"}
    ]
    for folder, side in ((base, "BASE"), (cand, "CAND")):
        director = {"plan": {"note": f"{side} {brief}", "contact": secrets["email"], "path": secrets["adc"]}}
        write_case(folder, "B-001", brief=brief, director=director, files=files, answers=answers)
    return base, cand


def test_VERTEX_EVAL_1_export_redacts_secrets_and_personal_data(tmp_path: Path) -> None:
    base, cand = _loaded_with_secrets(tmp_path)
    secrets = planted()
    result = invoke(export_argv(tmp_path, cand, base), environ={"GOOGLE_CLOUD_PROJECT": secrets["project"]})
    assert result.code == 0, result.err
    data = (tmp_path / "pairs.local.yaml").read_bytes()
    text = data.decode("utf-8")
    assert leaks(text) == [], f"planted values survived in the bytes: {leaks(text)}"
    assert not any(core in text for core in CORES.values())
    (row,) = load_pairs(tmp_path / "pairs.local.yaml")["pairs"]
    assert "[redacted]" in row["prompt"] and "Mail " in row["prompt"]  # redacted, not dropped
    assert leaks(result.everything) == []  # nor in what the command printed


def test_VERTEX_EVAL_1_export_redacts_a_project_id_that_only_the_environment_knows(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    project = "tilo-private-lab-4421"  # not a shape any pattern knows
    for folder, side in ((base, "BASE"), (cand, "CAND")):
        write_case(
            folder, "B-001", brief=f"Deploy to {project} today.", director={"plan": {"where": project, "s": side}}
        )
    result = invoke(export_argv(tmp_path, cand, base), environ={"GOOGLE_CLOUD_PROJECT": project})
    assert result.code == 0, result.err
    assert project not in (tmp_path / "pairs.local.yaml").read_text(encoding="utf-8")


def test_VERTEX_EVAL_1_export_redacts_before_cap(tmp_path: Path) -> None:
    """A secret that straddles the field cap never leaves a piece of itself: scrub first, cut second (design 4.1)."""
    token = planted()["sk"]
    body = token[len("sk-proj-") :]
    cap = 120
    cand = tmp_path / "cand"
    cand.mkdir()
    pads = list(range(70, cap + 6))  # the token starts everywhere from well inside the cap to just past it
    for pad in pads:
        case_id = f"B-{pad:03d}"
        text = "w" * pad + token + " tail text after it"
        write_case(
            cand, case_id, brief=text, director={"plan": {"note": text}},
            files=[{"name": "n.csv", "text": text}],
        )  # fmt: skip
    settings_path = write_settings(
        tmp_path, field_chars={"prompt": cap, "context": cap, "response": cap}, max_cases=100
    )
    result = invoke(export_argv(tmp_path, cand, settings=settings_path, extra=("--max-cases", "100")))
    assert result.code == 0, result.err
    out = tmp_path / "pairs.local.yaml"
    text = out.read_text(encoding="utf-8")
    for size in range(6, len(body) + 1):  # no prefix of the secret's body survives, not even six characters
        assert body[:size] not in text, f"{size} characters of the secret leaked across the cap"
    rows = load_pairs(out)["pairs"]
    assert len(rows) == len(pads)
    for row in rows:
        for field in ("prompt", "context", "candidate_response"):
            value = row[field]
            if value.endswith(TRUNCATED):
                assert len(value) <= cap + len(TRUNCATED), (row["id"], field, len(value))
            else:
                assert len(value) <= cap, (row["id"], field, len(value))
    assert any(row["candidate_response"].endswith(TRUNCATED) for row in rows)  # the cap was really in play


def test_VERTEX_EVAL_1_export_caps_long_fields_and_marks_the_cut(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    for folder, side in ((base, "BASE"), (cand, "CAND")):
        write_case(
            folder, "B-001", brief="p" * 400, director={"plan": {"n": side + "r" * 400}},
            files=[{"name": "c.csv", "text": "c" * 400}],
        )  # fmt: skip
    caps = {"prompt": 100, "context": 150, "response": 90}
    result, out = _export(tmp_path, cand, base, settings=write_settings(tmp_path, field_chars=caps))
    assert result.code == 0, result.err
    (row,) = load_pairs(out)["pairs"]
    for field, cap in (("prompt", 100), ("context", 150), ("candidate_response", 90), ("baseline_response", 90)):
        assert row[field].endswith(TRUNCATED) and len(row[field]) <= cap + len(TRUNCATED), (field, len(row[field]))
    short = write_settings(tmp_path, name="roomy.yaml", field_chars={"prompt": 5000, "context": 5000, "response": 5000})
    result, out = _export(tmp_path, cand, base, settings=short)
    (row,) = load_pairs(out)["pairs"]
    assert not any(v.endswith(TRUNCATED) for v in (row["prompt"], row["context"], row["candidate_response"]))


def test_VERTEX_EVAL_1_export_strips_control_format_chars_and_refuses_oversize_fields(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    dirty = (
        "alpha"
        + chr(0)
        + chr(7)
        + "beta"
        + chr(0x200B)
        + "gamma"
        + chr(0x202E)
        + "delta"
        + chr(0xE000)
        + chr(0x2066)
        + chr(0xFEFF)
        + "omega"
        + chr(10)
        + chr(9)
        + "kept"
        + chr(13)
        + chr(10)
        + "line"
    )
    for folder, side in ((base, "BASE"), (cand, "CAND")):
        write_case(folder, "B-001", brief=dirty, director={"plan": {"note": dirty, "s": side}}, answers={"a": dirty})
        write_case(folder, "B-002", brief="fine", director={"plan": {"s": side}})
    huge = {"plan": {"note": "z" * 100_001}}  # over 100,000 characters once serialised
    write_case(cand, "B-003", brief="three", director=huge)
    write_case(base, "B-003", brief="three", director={"plan": {"s": "BASE"}})
    result, out = _export(tmp_path, cand, base)
    assert result.code == 0, result.err
    doc = load_pairs(out)
    text = out.read_bytes().decode("utf-8")
    assert b"\r" not in out.read_bytes() and "z" * 1000 not in text
    for row in doc["pairs"]:
        for field in ("prompt", "context", "candidate_response", "baseline_response"):
            bad = [c for c in row[field] if unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs") and c not in "\n\t"]
            assert bad == [], (row["id"], field, bad)
    first = next(p for p in doc["pairs"] if p["id"] == "B-001")
    assert "alphabetagammadeltaomega" in first["prompt"].replace("\n", "").replace("\t", "").replace(" ", "")
    assert "omega\n\tkept\nline" in first["prompt"]  # newline and tab stay, the carriage return goes
    assert [p["id"] for p in doc["pairs"]] == ["B-001", "B-002"]
    assert {s["id"]: s["reason"] for s in doc["skipped"]} == {"B-003": "input_too_large"}


# --- 27: deterministic, LF ------------------------------------------------------------------------------------------


def test_VERTEX_EVAL_1_export_is_deterministic_lf(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    write_side(base, "BASE", ids_of(4))
    write_side(cand, "CAND", ids_of(4))
    outs = []
    for i in range(3):
        out = tmp_path / f"run{i}" / "pairs.yaml"
        result = invoke(export_argv(tmp_path, cand, base, out=out))
        assert result.code == 0, result.err
        outs.append(out.read_bytes())
    assert outs[0] == outs[1] == outs[2]
    assert b"\r" not in outs[0] and outs[0].endswith(b"\n")


def test_VERTEX_EVAL_1_export_output_is_plain_yaml_with_the_pinned_keys(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    write_side(base, "BASE", ids_of(2))
    write_side(cand, "CAND", ids_of(2))
    _, out = _export(tmp_path, cand, base)
    doc = yaml.safe_load(out.read_bytes())
    assert set(doc) == {"candidate_label", "baseline_label", "pairs", "skipped"}
    assert doc["skipped"] == []
    assert all(isinstance(p[k], str) for p in doc["pairs"] for k in ("id", "prompt", "context", "candidate_response"))


# --- 40 (export part): free, no provider, no ADC ---------------------------------------------------------------------


def test_VERTEX_EVAL_1_export_builds_no_provider_and_needs_no_adc(tmp_path: Path) -> None:
    base, cand = _folders(tmp_path)
    write_side(base, "BASE", ids_of(2))
    write_side(cand, "CAND", ids_of(2))
    boom = mock.Mock(side_effect=AssertionError("export must not build a provider"))
    with (
        mock.patch("tilo_providers.evaluation.build_eval_provider", boom),
        mock.patch("tilo_evals.vertex_eval.build_eval_provider", boom, create=True),
        mock.patch("google.auth.default", side_effect=AssertionError("no ADC on export")),
    ):
        result = invoke(export_argv(tmp_path, cand, base))
    assert result.code == 0, result.err
    assert boom.call_count == 0


# --- property: no planted value survives wherever it sits and whatever surrounds it ----------------------------------


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    before=st.text(alphabet="abcdef .\n", max_size=150),
    after=st.text(alphabet="abcdef .\n", max_size=150),
    which=st.sampled_from(["email", "oauth", "sk", "bearer", "labelled", "apikey"]),
    cap=st.integers(min_value=40, max_value=200),
)
def test_VERTEX_EVAL_1_property_export_never_writes_a_planted_value(
    tmp_path_factory: pytest.TempPathFactory, before: str, after: str, which: str, cap: int
) -> None:
    tmp_path = tmp_path_factory.mktemp("prop")
    secret = planted()[which]
    text = (before + " " + secret + " " + after).strip() or secret
    cand = tmp_path / "cand"
    write_case(cand, "B-001", brief=text, director={"plan": {"note": text}}, files=[{"name": "n.csv", "text": text}])
    caps = {"prompt": cap, "context": cap, "response": cap}
    result = invoke(export_argv(tmp_path, cand, settings=write_settings(tmp_path, field_chars=caps)))
    assert result.code == 0, result.err
    written = (tmp_path / "pairs.local.yaml").read_text(encoding="utf-8")
    assert CORES[which] not in written and secret not in written
    assert yaml.safe_load(written)["pairs"][0]["id"] == "B-001"
