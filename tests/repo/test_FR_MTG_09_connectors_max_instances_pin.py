"""ADR-0032 T5 / CON-D9: the deploy files must not undo connectors' single instance.

`gcloud run services update --max-instances` sets the same revision maximum as Terraform's
`max_instance_count`, so the deploy value for tilo-connectors must equal the Terraform value (1 until ticket T7).
The wider P0_07a / P0_07f checks allow 1..3 for every service; this pin is narrower and does not replace them.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEPLOY_FILES = ("cloudbuild.yaml", ".github/workflows/deploy-dev.yml")


def _terraform_connectors_max() -> int:
    text = (ROOT / "infra/envs/dev/main.tf").read_text(encoding="utf-8")
    start = text.index('"connectors" = {')
    block = text[start : text.index("\n    }\n", start)]
    m = re.search(r"(?m)^\s*max_instance_count\s*=\s*(\d+)", block)
    assert m, "connectors has no max_instance_count in main.tf"
    return int(m.group(1))


def test_FR_MTG_09_terraform_connectors_is_single_instance() -> None:
    assert _terraform_connectors_max() == 1


def test_FR_MTG_09_deploy_files_pin_connectors_to_the_terraform_max() -> None:
    expected = _terraform_connectors_max()
    for name in DEPLOY_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        found = re.findall(r"(?m)^\s*update connectors --max-instances (\d+)\s*$", text)
        assert found == [str(expected)], f"{name}: connectors deploy max {found} != Terraform {expected}"


def test_FR_MTG_09_deploy_docs_name_connectors_single_instance() -> None:
    text = (ROOT / "docs/deploy-dev.md").read_text(encoding="utf-8")
    assert "--max-instances 2..3" not in text
    assert "connectors = 1" in text or "connectors 1" in text
