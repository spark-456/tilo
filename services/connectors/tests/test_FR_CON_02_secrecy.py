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


# ADR-0032 decision 1: the broker, the live Google transport and every adapter (each takes a token) stay in connectors.
# tilo-api may keep the pure modules (meeting_host, outbox, provenance, registry, errors).
TOKEN_MODULES = ("tilo_connectors.tokens", "tilo_connectors.live", "tilo_connectors.adapters")
TOKEN_NAMES = ("tokens", "TokenBroker", "FakeKms", "live", "adapters")


def _is_token_module(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in TOKEN_MODULES)


def token_module_uses(tree: ast.AST) -> list[int]:
    """Every line that reaches tilo_connectors.tokens, .live or .adapters: an import, a from-import, an attribute
    access (`tilo_connectors.live.X`), a dotted or relative import_module/__import__ string, or getattr by name."""
    found: list[int] = []
    wanted = {m.rsplit(".", 1)[1] for m in TOKEN_MODULES}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and _is_token_module(node.module or ""):
            found.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "tilo_connectors":
            if any(a.name in TOKEN_NAMES for a in node.names):
                found.append(node.lineno)
        elif isinstance(node, ast.Import):
            found += [node.lineno for a in node.names if _is_token_module(a.name)]
        elif isinstance(node, ast.Attribute):
            if node.attr in TOKEN_NAMES and isinstance(node.value, ast.Name) and node.value.id == "tilo_connectors":
                found.append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _is_token_module(node.value):
            found.append(node.lineno)  # importlib.import_module("tilo_connectors.live")
        elif isinstance(node, ast.Call):
            args = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            args += [k.value.value for k in node.keywords if isinstance(k.value, ast.Constant)]
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            relative = (
                name in ("import_module", "__import__")
                and "tilo_connectors" in args
                and any(a.startswith(".") and a.lstrip(".") in wanted for a in args)
            )
            first = node.args[0] if node.args else None
            by_getattr = (
                name == "getattr"
                and isinstance(first, ast.Name)
                and first.id == "tilo_connectors"
                and any(a in TOKEN_NAMES for a in args)
            )
            if relative or by_getattr:
                found.append(node.lineno)
    return found


@pytest.mark.parametrize(
    "snippet",
    [
        "import tilo_connectors.live",
        "from tilo_connectors.adapters import GmailAdapter",
        "from tilo_connectors import live",
        "import tilo_connectors\ntilo_connectors.tokens.TokenBroker",
        "import tilo_connectors\nx = tilo_connectors.adapters",
        "import importlib\nimportlib.import_module('tilo_connectors.live')",
        "import importlib\nimportlib.import_module('.tokens', 'tilo_connectors')",
        "import importlib\nimportlib.import_module('.adapters', package='tilo_connectors')",
        "import tilo_connectors\ngetattr(tilo_connectors, 'live')",
    ],
)
def test_FR_CON_02_the_import_scan_catches_every_form_that_reaches_a_token_module(snippet):
    assert token_module_uses(ast.parse(snippet)), snippet


def test_FR_CON_02_the_import_scan_lets_the_pure_modules_through():
    pure = (
        "from tilo_connectors.meeting_host import HostReceipt\n"
        "from tilo_connectors import Outbox\n"
        "import tilo_connectors"
    )
    assert token_module_uses(ast.parse(pure)) == []


def test_FR_CON_02_no_service_outside_tilo_connectors_imports_the_broker():
    """SEC-02 / PRD 6.5 / ADR-0032: only tilo-connectors can decrypt OAuth tokens or use them, so no other service or
    package reaches tilo_connectors.tokens, .live or .adapters, by any form `token_module_uses` knows."""
    own = (REPO_ROOT / "services" / "connectors").resolve()
    violations = []
    for path in production_files():
        if own in path.resolve().parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations += [f"{path.relative_to(REPO_ROOT)}:{n}" for n in token_module_uses(tree)]
    assert violations == []
