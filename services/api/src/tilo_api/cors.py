"""WEB-TO-API: CORS for the deployed web app, only when the owner sets `TILO_API_CORS_ORIGINS` (BQ-WEBAPI-1).

A comma-separated list of exact https origins (scheme, host, optional port; no path, query, userinfo or wildcard).
One invalid entry means no CORS at all: the owner's mistake never widens access. No credentials are allowed (the
web client sends a bearer token and an App Check token as headers, not cookies). Installed last in
`tilo_api/__init__.py`, so it is the outermost middleware: a preflight is answered here, before the access,
App Check and sign-in gates, which a preflight (it carries no token) could never pass; a real request still goes
through every gate. Dev mode keeps its own CORS (`tilo_api.dev`).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ENV = "TILO_API_CORS_ORIGINS"
_ORIGIN_RE = re.compile(r"^https://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?$")


def cors_origins(env: Mapping[str, str] | None = None) -> list[str]:
    """The configured origins, or [] when unset or when any entry is not an exact https origin."""
    raw = (os.environ if env is None else env).get(ENV, "").strip()
    if not raw:
        return []
    origins = [part.strip() for part in raw.split(",")]
    if not all(_ORIGIN_RE.fullmatch(o) for o in origins):
        return []
    return origins


def install_cors(app: FastAPI, env: Mapping[str, str] | None = None) -> bool:
    """Adds the middleware when there are valid origins; returns whether it did."""
    source = os.environ if env is None else env
    if source.get("TILO_API_DEV") == "1":  # dev mode has its own CORS (tilo_api.dev): never both
        return False
    origins = cors_origins(env)
    if not origins:
        return False
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],  # the methods the API's routes use
        allow_headers=["Content-Type", "Idempotency-Key", "X-Firebase-AppCheck", "Authorization", "X-Tilo-Channel"],
        expose_headers=["Retry-After"],
        allow_credentials=False,
    )
    return True
