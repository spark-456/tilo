"""FR-INT-11 security review fixes (SN-02, SN-04, ADR-0014): the loader refuses a value that ends in a line break
(ECMA `$`), YAML anchors, aliases and tags, and a seed file outside a `seed` directory or at a hidden path."""

from __future__ import annotations

import pathlib
import shutil
import time

import pytest
import yaml
from tilo_planning import scenarios

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = {
    "id": "TS-91",
    "title": "Fictional vendor comparison",
    "skills": ["vendor-research"],
    "connectors": ["google_drive"],
    "seed_data": ["seed/vendors.yaml"],
    "theme": "metropolis",
}


def make_repo(root: pathlib.Path, text: str | None = None, **changes) -> pathlib.Path:
    (root / "config" / "scenarios").mkdir(parents=True)
    for name in ("connectors.yaml", "autonomy.yaml"):
        shutil.copy(REPO_ROOT / "config" / name, root / "config" / name)
    (root / "seed").mkdir()
    (root / "seed" / "vendors.yaml").write_text("vendors: []\n", encoding="utf-8")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "seed").mkdir()
    (root / ".hidden" / "seed" / "x.yaml").write_text("a: 1\n", encoding="utf-8")
    body = text if text is not None else yaml.safe_dump({**BASE, **changes})
    (root / "config" / "scenarios" / "TS-91.yaml").write_text(body, encoding="utf-8")
    return root


def load(root: pathlib.Path):
    return scenarios.load_scenario("TS-91", repo_root=root)


def test_FR_INT_11_an_action_type_ending_in_a_line_break_is_refused(tmp_path):
    entry = {"action_type": "save_file\n", "level": "L1", "connectors": ["google_drive"]}
    root = make_repo(tmp_path / "r", autonomy=[entry])

    with pytest.raises(scenarios.ScenarioError):
        load(root)


@pytest.mark.parametrize(
    "text",
    [
        "title: &a Fictional\nid: TS-91\nskills: [vendor-research]\nconnectors: []\nseed_data: []\ntheme: metropolis\n",
        "id: TS-91\ntitle: !!str 123\nskills: [vendor-research]\nconnectors: []\nseed_data: []\ntheme: metropolis\n",
        "id: TS-91\ntitle: x\nskills: &s [vendor-research]\nconnectors: []\nseed_data: []\ntheme: metropolis\nx: *s\n",
    ],
    ids=["anchor", "tag", "alias"],
)
def test_FR_INT_11_yaml_anchors_aliases_and_tags_are_refused(tmp_path, text):
    root = make_repo(tmp_path / "r", text=text)

    with pytest.raises(scenarios.ScenarioError):
        load(root)


def test_FR_INT_11_an_alias_bomb_is_refused_quickly_not_expanded(tmp_path):
    levels = ["a0: &a0 [x, x, x, x, x, x, x, x, x]"]
    levels += [f"a{i}: &a{i} [" + ", ".join([f"*a{i - 1}"] * 9) + "]" for i in range(1, 8)]
    text = "\n".join(levels) + "\nid: TS-91\n"
    root = make_repo(tmp_path / "r", text=text)

    started = time.perf_counter()
    with pytest.raises(scenarios.ScenarioError):
        load(root)

    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    "seed",
    ["config/autonomy.yaml", ".hidden/seed/x.yaml", "seed/vendors.yaml.", "seed/missing.yaml"],
    ids=["not under a seed dir", "hidden segment", "trailing dot alias", "missing"],
)
def test_FR_INT_11_a_seed_must_be_an_existing_file_under_a_seed_directory_without_hidden_segments(tmp_path, seed):
    root = make_repo(tmp_path / "r", seed_data=[seed])

    with pytest.raises(scenarios.ScenarioError):
        load(root)


def test_FR_INT_11_a_scenario_file_that_is_a_link_elsewhere_is_not_loaded(tmp_path):
    root = make_repo(tmp_path / "r")
    target = tmp_path / "elsewhere.yaml"
    target.write_text((root / "config" / "scenarios" / "TS-91.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    link = root / "config" / "scenarios" / "TS-92.yaml"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links cannot be created here")

    with pytest.raises(scenarios.ScenarioError):
        scenarios.load_scenario("TS-92", repo_root=root)


def test_FR_INT_11_the_smoke_test_applies_the_same_seed_rule(tmp_path):
    root = make_repo(tmp_path / "r")
    scenario = load(root)
    assert scenarios.smoke_test(scenario, repo_root=root) == []
    moved = scenarios.Scenario(
        scenario.id, scenario.title, scenario.skills, scenario.connectors,
        (root / "config" / "autonomy.yaml",), scenario.theme, scenario.autonomy,
    )  # fmt: skip

    assert any("autonomy.yaml" in p for p in scenarios.smoke_test(moved, repo_root=root))
