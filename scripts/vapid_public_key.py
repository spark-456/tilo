"""Prints the VAPID PUBLIC key (the browser's applicationServerKey) for a VAPID private key read from stdin.

`TILO_WEBPUSH_VAPID_PUBLIC_KEY` on tilo-api is the public half of the secret `webpush-vapid-private-key`
(docs/runbooks/infra-sitting-2.md). The private key is parsed exactly as tilo-channels parses it
(`tilo_channels.web_push_sender._vapid`: PEM, or a base64url raw 32-byte or DER key), is never printed, and an
unusable input gets one fixed message with no part of the input in it.

    gcloud secrets versions access latest --secret=webpush-vapid-private-key |
      uv run --package tilo-channels --frozen python -I scripts/vapid_public_key.py

Nothing is sent anywhere.
"""

from __future__ import annotations

import base64
import sys


def public_key(private: str) -> str:
    """The unpadded base64url uncompressed P-256 point (87 characters) of a VAPID private key."""
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    from py_vapid import Vapid  # noqa: PLC0415  (installed with pywebpush)

    key = private.strip()
    vapid = Vapid.from_pem(key.encode()) if "-----BEGIN" in key else Vapid.from_string(key)
    point = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(point).rstrip(b"=").decode()


def main(stdin: str) -> int:
    try:
        print(public_key(stdin))
    except Exception:  # noqa: BLE001 - a parser's text can quote the input: say nothing about it
        print("could not read a VAPID private key from stdin", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.stdin.read()))
