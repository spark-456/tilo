"""FR-CHN-17 / INFRA-SITTING2: `scripts/vapid_public_key.py` derives the browser's applicationServerKey from the
VAPID private key the way tilo-channels parses it, prints nothing of the private key, and says nothing about a bad
input. Keys are generated at runtime (no key material in the repo)."""

from __future__ import annotations

import base64
import importlib.util
import pathlib

import pytest

pytest.importorskip("py_vapid")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "vapid_public_key.py"


def _load():
    spec = importlib.util.spec_from_file_location("vapid_public_key", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _expected(private: ec.EllipticCurvePrivateKey) -> str:
    point = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(point)


def test_FR_CHN_17_public_key_from_raw_der_and_pem_private_keys(capsys: pytest.CaptureFixture[str]) -> None:
    script = _load()
    private = ec.generate_private_key(ec.SECP256R1())
    raw = _b64(private.private_numbers().private_value.to_bytes(32, "big"))
    der = _b64(
        private.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    for secret in (raw, der, pem):
        assert script.main(secret + "\n") == 0
        out = capsys.readouterr().out.strip()
        assert out == _expected(private)
        assert len(out) == 87 and secret.strip() not in out


def test_FR_CHN_17_public_key_script_says_nothing_about_a_bad_input(capsys: pytest.CaptureFixture[str]) -> None:
    script = _load()
    junk = "not-a-key-" + "x" * 40
    assert script.main(junk) == 1
    seen = capsys.readouterr()
    assert seen.out == "" and junk not in seen.err and "x" * 20 not in seen.err
