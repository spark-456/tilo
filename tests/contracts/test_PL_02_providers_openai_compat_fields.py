"""PL-02 (ticket P0-02b): providers contract gains optional `base_url` and
`api_key_env` on `$defs.profile`, allowed only when `provider` is
`openai_compat` (PRD 6.4; PRD 16.1 rule 4 "secrets never enter ... the raw
archive"; ADR-0002 sections 1-2 file/versioning conventions; ADR-0003 decision
2, the NVIDIA NIM example profile).

Additive-only change: contracts/providers.schema.json `$defs.profile` keeps
its current required fields (provider, model, context, caps) and gains two
new *optional* properties, gated by an `if`/`then` on `provider`:

  - `base_url`: string, must start "https://" (never http, PRD 16.1 rule 4 --
    a plaintext endpoint would let a key travel unencrypted) and (per the
    ticket) `format: uri`. This suite checks the `^https://` boundary via
    `pattern`, the same mechanism the rest of contracts/*.schema.json relies
    on -- `tests/contracts/_lib.py` builds validators with no
    `jsonschema.FormatChecker`, matching every other schema test in this
    ticket set (`format` alone is not enforced anywhere in this suite; see
    `_lib.validator_for`), so `format: uri` is documented on the schema but
    not separately asserted here.
  - `api_key_env`: string, `^[A-Z][A-Z0-9_]{2,63}$` -- the *name* of an
    environment variable a value is read from at runtime, never a value
    itself. A profile carries only this name; PL-02 exists precisely so a
    real key is never written into config/, contracts/ fixtures or this test
    file (CLAUDE.md "No secrets in code, prompts, logs or fixtures. Fake
    secrets for tests are assembled at runtime.").
  - `provider: google` profiles carry neither field (ADR-0003 decision 2:
    Google adapters are tested against mocks and recordings, no endpoint or
    key override).

Ambiguity resolved per CLAUDE.md's stated-default rule: the ticket names the
new provider value "openai_compat" throughout (title and body); a single,
unrelated string "openai_compatible" appears in
packages/providers/tests/test_PL_04_prompt_templates.py for a different
ticket's prompt-override suffix and is not this schema's `provider` enum (the
field has always been a free `common.schema.json#/$defs/slug`, not a closed
list), so it does not bind this one. Logged in the report, not in
docs/open-questions.md, since it does not change any acceptance criterion.
"""

from __future__ import annotations

import copy

from _lib import SCHEMA_ID_TEMPLATE, errors_for, list_fixtures, load_json, load_schema
from hypothesis import given
from hypothesis import strategies as st

PROVIDERS_ID = SCHEMA_ID_TEMPLATE.format(name="providers")
PROFILE_REF = {"$ref": f"{PROVIDERS_ID}#/$defs/profile"}

BASE_OPENAI_COMPAT_PROFILE = {
    "provider": "openai_compat",
    "model": "example-openai-compatible-model",
    "context": 128000,
    "caps": ["json", "tools"],
    "base_url": "https://api.example.com/v1",
    "api_key_env": "EXAMPLE_API_KEY",
}

BASE_GOOGLE_PROFILE = {
    "provider": "google",
    "model": "example-flash",
    "context": 1000000,
    "caps": ["json", "tools"],
}

API_KEY_ENV_PATTERN = r"^[A-Z][A-Z0-9_]{2,63}$"


def _profile_errors(registry, profile: dict) -> list[str]:
    return [e.message for e in errors_for(PROFILE_REF, profile, registry)]


# --- 1. an openai_compat profile may carry base_url (https) and api_key_env ---


def test_PL_02_openai_compat_profile_accepts_https_base_url_and_api_key_env(registry):
    errors = _profile_errors(registry, BASE_OPENAI_COMPAT_PROFILE)
    assert not errors, (
        "PL-02: an openai_compat profile must accept an https base_url and an uppercase "
        f"api_key_env name, but contracts/providers.schema.json $defs.profile rejected it: {errors}"
    )


def test_PL_02_openai_compat_profile_without_the_new_fields_still_validates(registry):
    # The change is additive: a plain openai_compat profile (no base_url/api_key_env
    # at all) must keep validating exactly as before.
    minimal = {k: v for k, v in BASE_OPENAI_COMPAT_PROFILE.items() if k not in ("base_url", "api_key_env")}
    errors = _profile_errors(registry, minimal)
    assert not errors, f"PL-02: an openai_compat profile with neither new field must still validate: {errors}"


# --- 2. an http:// base_url is invalid ---


def test_PL_02_openai_compat_base_url_rejects_http(registry):
    profile = copy.deepcopy(BASE_OPENAI_COMPAT_PROFILE)
    profile["base_url"] = "http://api.example.com/v1"
    errors = _profile_errors(registry, profile)
    assert errors, "PL-02: base_url must reject a plain http:// URL (PRD 16.1 rule 4), but it validated"


# --- 3. api_key_env: lower case, containing '=', or otherwise key-value-shaped is invalid ---


def test_PL_02_openai_compat_api_key_env_rejects_lower_case(registry):
    profile = copy.deepcopy(BASE_OPENAI_COMPAT_PROFILE)
    profile["api_key_env"] = "example_api_key"
    errors = _profile_errors(registry, profile)
    assert errors, "PL-02: api_key_env must reject a lower-case name, but it validated"


def test_PL_02_openai_compat_api_key_env_rejects_key_value_shape(registry):
    # Assembled at runtime, never a literal secret (CLAUDE.md): a fake env-style
    # "NAME=value" pair standing in for someone pasting a whole KEY=... line
    # instead of just the variable's name.
    fake_env_line = "EXAMPLE_API_KEY" + "=" + "placeholder-not-a-real-value"
    profile = copy.deepcopy(BASE_OPENAI_COMPAT_PROFILE)
    profile["api_key_env"] = fake_env_line
    errors = _profile_errors(registry, profile)
    assert errors, (
        "PL-02: api_key_env must reject a value that contains '=' / looks like a KEY=value pair "
        "(it must be only the variable's name), but it validated"
    )


# --- 4. a google profile carrying either field is invalid ---


def test_PL_02_google_profile_rejects_base_url(registry):
    profile = copy.deepcopy(BASE_GOOGLE_PROFILE)
    profile["base_url"] = "https://generativelanguage.googleapis.com/v1"
    errors = _profile_errors(registry, profile)
    assert errors, (
        "PL-02: a provider: google profile must reject base_url (ADR-0003 decision 2: only "
        "openai_compat profiles carry an endpoint override), but it validated"
    )


def test_PL_02_google_profile_rejects_api_key_env(registry):
    profile = copy.deepcopy(BASE_GOOGLE_PROFILE)
    profile["api_key_env"] = "GOOGLE_API_KEY"
    errors = _profile_errors(registry, profile)
    assert errors, "PL-02: a provider: google profile must reject api_key_env (ADR-0003 decision 2), but it validated"


def test_PL_02_google_profile_without_the_new_fields_still_validates(registry):
    errors = _profile_errors(registry, BASE_GOOGLE_PROFILE)
    assert not errors, f"PL-02: a plain google profile must still validate unchanged: {errors}"


# --- 5. property tests: the api_key_env pattern is exactly the validity boundary ---
# (Hypothesis, per the ticket-writer's rule to property-test invariants.)


@given(st.from_regex(API_KEY_ENV_PATTERN, fullmatch=True))
def test_PL_02_any_name_matching_the_api_key_env_pattern_validates(registry, name):
    profile = copy.deepcopy(BASE_OPENAI_COMPAT_PROFILE)
    profile["api_key_env"] = name
    errors = _profile_errors(registry, profile)
    assert not errors, f"PL-02: api_key_env {name!r} matches ^[A-Z][A-Z0-9_]{{2,63}}$ but was rejected: {errors}"


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=40))
def test_PL_02_a_name_not_matching_the_api_key_env_pattern_never_validates(registry, name):
    import re

    if re.fullmatch(API_KEY_ENV_PATTERN, name):
        return  # not a counter-example; the positive property test above covers this branch
    profile = copy.deepcopy(BASE_OPENAI_COMPAT_PROFILE)
    profile["api_key_env"] = name
    errors = _profile_errors(registry, profile)
    assert errors, f"PL-02: api_key_env {name!r} does not match ^[A-Z][A-Z0-9_]{{2,63}}$ but validated anyway"


# --- 6. the NVIDIA NIM example profile shape validates (ADR-0003 decision 2) ---


def test_PL_02_nvidia_nim_example_profile_fixture_validates(repo_root, registry):
    fixtures = list_fixtures(repo_root, "providers", "valid")
    nim_fixture = next((p for p in fixtures if p.name == "nvidia_nim_example_profile.json"), None)
    assert nim_fixture is not None, (
        "PL-02: contracts/fixtures/providers/valid/nvidia_nim_example_profile.json must exist "
        "(ADR-0003 decision 2: the NVIDIA NIM example profile shape)"
    )
    instance = load_json(nim_fixture)
    schema = load_schema(repo_root, "providers")
    errors = [e.message for e in errors_for(schema, instance, registry)]
    assert not errors, f"PL-02: the NVIDIA NIM example fixture must validate against providers.schema.json: {errors}"

    profile = instance["models"]["profiles"]["nim-gemma"]
    assert profile["provider"] == "openai_compat"
    assert profile["base_url"] == "https://integrate.api.nvidia.com/v1", (
        "PL-02/ADR-0003: the NIM example's base_url must be the documented NIM endpoint"
    )
    assert profile["api_key_env"] == "NVIDIA_API_KEY", (
        "PL-02/ADR-0003: the NIM example's api_key_env must name NVIDIA_API_KEY "
        "(ADR-0003 decision 2: 'key from NVIDIA_API_KEY in the git-ignored .env')"
    )


# --- 7. additive minor version bump (ADR-0002 section 2) ---


def test_PL_02_providers_schema_version_bumped_to_minor_1_1_0(repo_root):
    schema = load_schema(repo_root, "providers")
    version = tuple(int(p) for p in str(schema.get("x-version")).split("."))
    # 1.1.0 for this change; later minors are additive (1.2.0: audio_input and the speech role, ADR-0027).
    assert version >= (1, 1, 0) and version[0] == 1, (
        "PL-02: contracts/providers.schema.json must bump x-version to 1.1.0 or a later 1.x for this additive "
        f"change (ADR-0002 section 2: 'additive change is minor'), got {schema.get('x-version')!r}"
    )
