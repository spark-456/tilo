"""FR-CON-02 (PRD 16.1 rules 2 and 4, 16.4 SEC-01 and SEC-02): a token's plaintext never appears in a
log, an error, an event, a repr or a return value, whatever the provider echoes back; the access
token leaves the broker only through the adapter path, which names the scopes it needs; and no
service outside tilo-connectors imports the broker.

Every secret here is assembled at runtime by _oauth_lib; the fake provider echoes the secrets it
receives inside its error bodies, so any code that copies a provider body is caught.
"""

from __future__ import annotations

import ast
import logging
import pathlib

import pytest
from _oauth_lib import (
    DEV_REDIRECT_URI,
    DRIVE_FILE,
    EXPIRES_IN,
    GMAIL_READONLY,
    OWNER,
    REPO_ROOT,
    base64_forms_of_bytes,
    fake_secret,
    leaks,
    make_env,
)
from tilo_connectors.tokens import (
    ConnectionExpired,
    OAuthSettings,
    TokenBroker,
    TokenError,
    TokenRefreshFailed,
)

SCOPES = [GMAIL_READONLY]


def attempt(fn):
    try:
        return fn()
    except TokenError as exc:  # the broker's own errors; anything else fails the test
        return exc


def test_FR_CON_02_no_secret_appears_in_any_log_error_event_repr_or_return_value(caplog):
    env = make_env()
    caplog.set_level(logging.DEBUG)
    observed: list[str] = []
    tokens: list[str] = []

    def see(value):
        observed.append(f"{value!r} {value}")

    response = env.connect(OWNER, "gmail", SCOPES)
    tokens += [response["access_token"], response["refresh_token"]]
    see(env.broker.granted_scopes(OWNER, "gmail"))
    see(env.broker.connection_state(OWNER, "gmail"))

    # A refresh that gets through, one that is refused, one that never arrives, and a rejected one.
    env.clock.advance(EXPIRES_IN + 1)
    env.google.refresh_mode = "unavailable"
    see(attempt(lambda: env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=SCOPES)))
    env.google.refresh_mode = "network"
    see(attempt(lambda: env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=SCOPES)))
    env.google.refresh_mode = "ok"
    tokens.append(env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=SCOPES))
    see(attempt(lambda: env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=SCOPES + [DRIVE_FILE])))
    env.clock.advance(EXPIRES_IN + 1)
    env.google.refresh_mode = "invalid_grant"
    see(attempt(lambda: env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=SCOPES)))
    see(attempt(lambda: env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=SCOPES)))

    # A second connection whose revoke fails.
    second = env.connect(OWNER, "google_drive", [DRIVE_FILE])
    tokens += [second["access_token"], second["refresh_token"]]
    env.google.revoke_mode = "rejected"
    see(env.broker.disconnect(OWNER, "google_drive"))
    env.google.revoke_mode = "ok"
    env.broker.disconnect(OWNER, "gmail")

    blobs = [
        "\n".join(observed),
        "\n".join(f"{r.getMessage()} {r.exc_text or ''} {r.args!r}" for r in caplog.records),
        repr(env.emitted),
        repr(env.broker),
        str(env.broker),
        repr(env.settings),
        str(env.settings),
        repr(env.service),
    ]
    secrets_ = tokens + [env.secrets["client_secret"]]
    for blob in blobs:
        assert leaks(blob, secrets_) == []
        for data_key in env.kms.encrypted:
            assert not any(form in blob for form in base64_forms_of_bytes(data_key))


def test_FR_CON_02_errors_carry_no_provider_body():
    env = make_env()
    response = env.connect(OWNER, "gmail", SCOPES)
    env.google.refresh_mode = "invalid_grant"
    env.clock.advance(EXPIRES_IN + 1)

    raised = attempt(lambda: env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=SCOPES))

    assert isinstance(raised, ConnectionExpired)
    assert leaks(f"{raised!s} {raised!r} {raised.args!r}", [response["refresh_token"]]) == []

    env2 = make_env()
    r2 = env2.connect(OWNER, "gmail", SCOPES)
    env2.google.refresh_mode = "unavailable"
    env2.clock.advance(EXPIRES_IN + 1)
    raised2 = attempt(lambda: env2.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=SCOPES))
    assert isinstance(raised2, TokenRefreshFailed)
    assert leaks(f"{raised2!s} {raised2!r} {raised2.args!r}", [r2["refresh_token"]]) == []


# ---- OAuthSettings -----------------------------------------------------------------------------


def test_FR_CON_02_settings_repr_hides_the_client_secret():
    secret = fake_secret("cs")
    settings = OAuthSettings(client_id=fake_secret("client"), client_secret=secret)

    assert secret not in repr(settings)
    assert secret not in str(settings)


def test_FR_CON_02_settings_default_redirect_is_the_local_dev_callback():
    settings = OAuthSettings(client_id=fake_secret("client"), client_secret=fake_secret("cs"))

    assert settings.redirect_uri == DEV_REDIRECT_URI == "http://localhost:8080/oauth/google/callback"


@pytest.mark.parametrize("base", ["https://api.tilo.example", "https://api.tilo.example/"])
def test_FR_CON_02_settings_redirect_base_url_is_configurable(base):
    settings = OAuthSettings(client_id=fake_secret("client"), client_secret=fake_secret("cs"), redirect_base_url=base)

    assert settings.redirect_uri == "https://api.tilo.example/oauth/google/callback"


def test_FR_CON_02_settings_come_from_the_named_env_vars_in_an_injected_mapping():
    client_id, secret = fake_secret("client"), fake_secret("cs")
    environ = {"GOOGLE_OAUTH_CLIENT_ID": client_id, "GOOGLE_OAUTH_CLIENT_SECRET": secret}

    settings = OAuthSettings.from_env(environ)

    assert settings.client_id == client_id
    assert settings.client_secret == secret
    assert settings.redirect_uri == DEV_REDIRECT_URI
    assert secret not in repr(settings)


@pytest.mark.parametrize("missing", ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"])
def test_FR_CON_02_settings_from_env_names_the_variable_that_is_missing(missing):
    environ = {"GOOGLE_OAUTH_CLIENT_ID": fake_secret("client"), "GOOGLE_OAUTH_CLIENT_SECRET": fake_secret("cs")}
    del environ[missing]

    with pytest.raises(ValueError, match=missing):
        OAuthSettings.from_env(environ)


# ---- The adapter path and the single decryptor -------------------------------------------------

ADAPTER_ENTRY = "access_token_for_adapter"
SRC = REPO_ROOT / "services" / "connectors" / "src" / "tilo_connectors"
SKIPPED_PARTS = {".venv", "node_modules", "__pycache__", "tests", "dist", "build"}


def production_files() -> list[pathlib.Path]:
    found = []
    for root in (REPO_ROOT / "services", REPO_ROOT / "packages"):
        for path in root.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT)
            if SKIPPED_PARTS & set(rel.parts) or path.name.startswith("test_") or path.name == "conftest.py":
                continue
            found.append(path)
    return found


def references(tree: ast.AST, name: str) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == name:
            lines.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id == name:
            lines.append(node.lineno)
        elif isinstance(node, ast.Constant) and node.value == name:
            lines.append(node.lineno)
    return lines


def test_FR_CON_02_the_adapter_entry_exists_on_the_broker():
    assert callable(getattr(TokenBroker, ADAPTER_ENTRY, None))


def test_FR_CON_02_the_access_token_is_reachable_only_from_the_adapter_path():
    """The broker's one plaintext-returning call is referenced only by tokens.py itself and by
    adapters under tilo_connectors/adapters/ (PRD 12.1: connectors are implemented as adapters)."""
    files = production_files()
    assert len(files) > 10, "the scan found the source tree"
    allowed_dir = (SRC / "adapters").resolve()
    allowed_file = (SRC / "tokens.py").resolve()
    violations = []
    for path in files:
        resolved = path.resolve()
        if resolved == allowed_file or allowed_dir in resolved.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations += [f"{path.relative_to(REPO_ROOT)}:{line}" for line in references(tree, ADAPTER_ENTRY)]
    assert violations == []


def test_FR_CON_02_no_service_outside_tilo_connectors_imports_the_broker():
    """SEC-02 / PRD 6.5: only tilo-connectors can decrypt OAuth tokens, so no other service or
    package imports tilo_connectors.tokens."""
    own = (REPO_ROOT / "services" / "connectors").resolve()
    violations = []
    for path in production_files():
        if own in path.resolve().parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tilo_connectors.tokens"):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.module == "tilo_connectors":
                if any(a.name in ("tokens", "TokenBroker", "FakeKms") for a in node.names):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                violations += [
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
                    for a in node.names
                    if a.name.startswith("tilo_connectors.tokens")
                ]
    assert violations == []
