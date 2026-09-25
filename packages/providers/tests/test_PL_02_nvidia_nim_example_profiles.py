"""PL-02 / ADR-0003: "An example profile set for NVIDIA NIM
(https://integrate.api.nvidia.com/v1, key from NVIDIA_API_KEY in the
git-ignored .env) is added alongside the Google examples, preferring Gemma
models where NIM hosts them." Ticket P0-05 item 3: "add them to the example
config so a user can route roles to NIM for live tests: provider
openai_compat, base_url https://integrate.api.nvidia.com/v1, api_key_env
NVIDIA_API_KEY... Provide a way to select NIM routing without editing code:
e.g. a second example file config/models.nim.yaml selected by an env var
such as TILO_MODELS_FILE, validated by the same loader and denylist."

CONTRACT BLOCKER (see report, "needs contract change"): `ProvidersProfile`
(`contracts/providers.schema.json` `$defs.profile`) is `additionalProperties:
false` with only `provider`, `model`, `context`, `caps` -- no `base_url` or
`api_key_env`. A NIM profile cannot pass `tilo_providers.config.
load_providers_config` (PL-06/PL-07/NFR-25 start-up checks) until the
contract owner adds two optional fields, applicable when `provider ==
"openai_compat"`: `base_url` (string, `format: uri`) and `api_key_env`
(string). Not editing `contracts/` here per root CLAUDE.md.
`test_PL_02_nim_profiles_load_through_the_same_loader_and_denylist` is
expected to stay red until that lands, even once `config/models.nim.yaml`
exists -- every other test in this file checks the example file directly
(raw YAML) and does not depend on the contract change.
"""

from __future__ import annotations

import re

import pytest
import yaml

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_API_KEY_ENV = "NVIDIA_API_KEY"


@pytest.fixture
def nim_models_path(repo_root):
    path = repo_root / "config" / "models.nim.yaml"
    if not path.exists():
        pytest.fail(
            f"PL-02/ADR-0003: {path} does not exist yet -- ticket P0-05 item 3 adds it "
            "(a second example config, alongside config/models.yaml, routing roles to NVIDIA NIM)."
        )
    return path


def _load_raw(path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_PL_02_nim_profiles_use_the_openai_compat_provider_and_nim_base_url(nim_models_path):
    raw = _load_raw(nim_models_path)
    profiles = raw["profiles"]
    assert profiles, "config/models.nim.yaml must declare at least one profile"
    for profile_id, profile in profiles.items():
        assert profile["provider"] == "openai_compat", f"{profile_id}: provider must be openai_compat"
        assert profile["base_url"] == NIM_BASE_URL, f"{profile_id}: base_url must be NVIDIA's NIM endpoint"


def test_PL_02_nim_profiles_name_their_key_by_env_var_and_never_contain_a_key(nim_models_path):
    raw_text = nim_models_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    for profile_id, profile in raw["profiles"].items():
        assert profile.get("api_key_env") == NIM_API_KEY_ENV, (
            f"{profile_id}: must name the key by env var ({NIM_API_KEY_ENV}), 16.1 rule 4 / ADR-0003"
        )
        assert "api_key" not in profile, f"{profile_id}: must not carry a literal api_key field"

    # No secret-shaped literal anywhere in the file: a plausible API key is a
    # long run of base64url-ish characters that is not just the env var name.
    suspicious = re.findall(r"[A-Za-z0-9_-]{24,}", raw_text)
    leaked = [token for token in suspicious if token not in {NIM_API_KEY_ENV, "integrate.api.nvidia.com"}]
    assert not leaked, f"16.1 rule 4: config/models.nim.yaml must never contain a secret-shaped value, found {leaked}"


def test_PL_02_nim_profiles_prefer_gemma_models(nim_models_path):
    raw = _load_raw(nim_models_path)
    models = [profile["model"] for profile in raw["profiles"].values()]
    assert any("gemma" in model.lower() for model in models), (
        f"ADR-0003: NIM profiles must prefer Gemma models where NIM hosts them, got {models}"
    )


def test_PL_02_nim_profiles_cite_their_source_and_a_retrieval_date(nim_models_path):
    """Ticket item 3: "Verify the current model ids from NVIDIA's public
    model catalog or API docs... and cite the source and date in a config
    comment." """
    raw_text = nim_models_path.read_text(encoding="utf-8")
    comment_lines = [line for line in raw_text.splitlines() if line.strip().startswith("#")]
    commentary = "\n".join(comment_lines)
    assert "nvidia" in commentary.lower(), "must cite NVIDIA's catalog/docs as the source, in a comment"
    assert re.search(r"20\d{2}-\d{2}-\d{2}", commentary), "must cite a retrieval date (YYYY-MM-DD), in a comment"


def test_PL_02_nim_profiles_selectable_by_env_var_without_editing_code(monkeypatch, repo_root, nim_models_path):
    """Ticket item 3: "Provide a way to select NIM routing without editing
    code... selected by an env var such as TILO_MODELS_FILE." Assumption
    (see report): `tilo_providers.config.resolve_models_path` reads
    `TILO_MODELS_FILE`, defaulting to `config/models.yaml`."""
    from tilo_providers.config import resolve_models_path  # noqa: PLC0415

    monkeypatch.setenv("TILO_MODELS_FILE", str(nim_models_path))
    assert resolve_models_path(repo_root=repo_root) == nim_models_path

    monkeypatch.delenv("TILO_MODELS_FILE", raising=False)
    assert resolve_models_path(repo_root=repo_root) == repo_root / "config" / "models.yaml"


@pytest.mark.xfail(
    reason=(
        "needs contract change: contracts/providers.schema.json $defs.profile has no base_url/api_key_env "
        "(additionalProperties: false); see this file's module docstring (CONTRACT BLOCKER) and "
        "config/models.nim.yaml's header comment. Stays red -- by design, not weakened -- until the contract "
        "owner adds the two fields; remove this marker once they land."
    ),
    strict=False,
)
def test_PL_02_nim_profiles_load_through_the_same_loader_and_denylist(nim_models_path, repo_root):
    """Expected red until the contract change in this file's module
    docstring lands -- see CONTRACT BLOCKER above."""
    from tilo_providers.config import load_providers_config  # noqa: PLC0415

    config = load_providers_config(nim_models_path, repo_root / "config" / "prices.yaml")

    assert config.profiles, "NIM profiles must load through the same start-up checks as config/models.yaml"
