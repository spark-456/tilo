"""ADR32_T5b / FR-MTG-09 (SEC-02): the `tilo-tokens` database is denied to every client, like `(default)`.

`firebase.json` lists both databases under `firestore`, each with a rules file; no rules file allows anything. Terraform
ships the same deny-all text as a ruleset plus a release `cloud.firestore/tilo-tokens` (firebase.json deploys only the
databases named in a `firebase deploy`, and the CI deployer has no Firebase role), pinned in `security_iam.tftest.hcl`.
Static only: no firebase, no terraform, no network.
"""

from __future__ import annotations

import json
import pathlib
import re

TOKEN_RULES = "firestore.tokens.rules"


def _entries(repo_root: pathlib.Path) -> list[dict[str, str]]:
    firestore = json.loads((repo_root / "firebase.json").read_text(encoding="utf-8"))["firestore"]
    assert isinstance(firestore, list), "firebase.json `firestore` is a list, one entry per database"
    return firestore


def _strip_comments(text: str) -> str:
    return re.sub(r"//[^\n]*", "", text)


def test_ADR32_T5b_FR_MTG_09_firebase_json_covers_both_databases(repo_root: pathlib.Path) -> None:
    by_db = {e["database"]: e["rules"] for e in _entries(repo_root)}
    assert by_db == {"(default)": "firestore.rules", "tilo-tokens": TOKEN_RULES}


def test_ADR32_T5b_FR_MTG_09_no_rules_file_allows_anything(repo_root: pathlib.Path) -> None:
    for entry in _entries(repo_root):
        text = _strip_comments((repo_root / entry["rules"]).read_text(encoding="utf-8"))
        allows = re.findall(r"allow\s+[^;]*;", text)
        assert allows, f"{entry['rules']}: at least the catch-all deny"
        for rule in allows:
            assert re.fullmatch(r"allow\s+read\s*,\s*write\s*:\s*if\s+false\s*;", rule), f"{entry['rules']}: {rule}"
        assert not re.search(r"if\s+(true|request|resource)", text), entry["rules"]


def test_ADR32_T5b_FR_MTG_09_the_token_rules_are_one_catch_all_deny(repo_root: pathlib.Path) -> None:
    text = _strip_comments((repo_root / TOKEN_RULES).read_text(encoding="utf-8"))
    assert re.search(r"match\s+/databases/\{database\}/documents\s*\{\s*match\s+/\{document=\*\*\}\s*\{", text)
    assert len(re.findall(r"allow\s", text)) == 1
    assert len(re.findall(r"\bmatch\b", text)) == 2


def test_ADR32_T5b_FR_MTG_09_terraform_ships_the_ruleset_from_the_same_file(repo_root: pathlib.Path) -> None:
    main = (repo_root / "infra/envs/dev/main.tf").read_text(encoding="utf-8")
    assert 'resource "google_firebaserules_ruleset" "tokens"' in main
    assert 'resource "google_firebaserules_release" "tokens"' in main
    assert "firestore.tokens.rules" in main and "file(" in main, "one text, read by Terraform and by firebase.json"
    assert re.search(r'name\s*=\s*"cloud\.firestore/\$\{google_firestore_database\.tokens\.name\}"', main)
    assert "delete_protection_state" in main


def test_ADR32_T5b_FR_MTG_09_the_deploy_docs_name_the_database_setting(repo_root: pathlib.Path) -> None:
    deploy = (repo_root / "docs/deploy-dev.md").read_text(encoding="utf-8")
    assert "TILO_TOKEN_DATABASE=tilo-tokens" in deploy
    access = (repo_root / "infra/ACCESS.md").read_text(encoding="utf-8")
    assert "firestore.tokens.rules" in access and "cloud.firestore/tilo-tokens" in access
