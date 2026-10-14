"""FR-SKL-01 SKILLS-4 fix pass: a capture draft is not a listed skill, and the dev models file has the capture role.

  * A capture draft (status "draft") is the owner's working copy for the version flow. It never appears in
    GET /v1/skills or GET /v1/learn (not for the owner, not for a team), GET /v1/skills/{id} gives it to its owner
    only, and anyone else gets the same 404 as for an absent skill (TS-01).
  * `config/models.dev.yaml` defines the `specialist` role (the capture role) on a fake profile that has a price of 0
    in `config/prices.yaml`, so the dev API does not answer 503 not_configured; the loader accepts the file.

No network, no paid call, no live switch.
"""

from __future__ import annotations

import yaml
from _skills4_lib import CLEAR, ORG, PRIYA, SAM

SKILLS = "/v1/skills"


def _ids(response):
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()["skills"]]


def test_FR_SKL_01_SKILLS_4_a_draft_is_never_in_the_skill_list_or_learn(skills4):
    capture_id = skills4.made(CLEAR)
    assert skills4.store.get(ORG, capture_id)["status"] == "draft"
    skills4.rig.as_user(PRIYA)
    assert capture_id not in _ids(skills4.rig.get(SKILLS))
    learn = skills4.rig.get("/v1/learn")
    assert learn.status_code == 200 and capture_id not in [row["id"] for row in learn.json()["learning"]]
    skills4.version(capture_id)  # Tilo's version fills the plan; still a draft, still unlisted
    skills4.rig.as_user(PRIYA)
    assert capture_id not in _ids(skills4.rig.get(SKILLS))


def test_FR_SKL_01_SKILLS_4_the_owner_reads_the_draft_by_id_and_another_user_gets_404(skills4):
    capture_id = skills4.made(CLEAR)
    skills4.rig.as_user(PRIYA)
    own = skills4.rig.get(f"{SKILLS}/{capture_id}")
    assert own.status_code == 200 and own.json()["id"] == capture_id and own.json()["status"] == "draft"
    skills4.rig.as_user(SAM)
    other = skills4.rig.get(f"{SKILLS}/{capture_id}")
    assert other.status_code == 404 and other.json() == {"detail": "not_found"}
    assert capture_id not in _ids(skills4.rig.get(SKILLS))


def test_FR_SKL_01_SKILLS_4_a_draft_marked_for_a_team_is_still_only_its_owners(skills4):
    capture_id = skills4.made(CLEAR)
    row = skills4.store.get(ORG, capture_id)
    row["scope"] = {"kind": "team", "team": "team_x"}
    skills4.store.put(row)
    skills4.rig.as_user(SAM)
    assert skills4.rig.get(f"{SKILLS}/{capture_id}").status_code == 404
    assert capture_id not in _ids(skills4.rig.get(SKILLS))


def test_FR_SKL_01_SKILLS_4_the_dev_models_file_defines_specialist_with_a_price(repo_root):
    from tilo_providers.config import load_providers_config  # noqa: PLC0415

    models = yaml.safe_load((repo_root / "config" / "models.dev.yaml").read_text(encoding="utf-8"))
    prices = yaml.safe_load((repo_root / "config" / "prices.yaml").read_text(encoding="utf-8"))
    role = models["roles"]["specialist"]
    for profile_id in (role["primary"], role["fallback"]):
        assert models["profiles"][profile_id]["provider"] == "fake"
        assert prices["profiles"][profile_id] == {"input": 0, "output": 0}
    loaded = load_providers_config(repo_root / "config" / "models.dev.yaml", repo_root / "config" / "prices.yaml")
    assert "specialist" in loaded.models.roles
