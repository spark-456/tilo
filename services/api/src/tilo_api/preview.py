"""WEB-2 (ADR-0050, contracts/website.rules.md WS-10, WS-11, WS-13): the fixed preview shell for a native website.

`GET /preview/website` returns the same bytes to every caller: no data, no token, no sign-in, nothing from the request.
The web app frames it as `<iframe sandbox="allow-scripts">`; its one inline script posts `{"tilo":"preview-ready"}` to
the parent, takes exactly ONE `{"tilo":"preview","html":<text>}` message whose origin is one of the web app's origins,
writes the text into its own document and drops the listener. The page keeps the shell's CSP (`sandbox allow-scripts`
makes the origin opaque even when the shell is opened alone; no network of any kind). The response carries no
`X-Frame-Options`: framing is limited by `frame-ancestors` (the web origins), and this is the only route that is
framed. The same CSP rides on a website download (`results.py`, WS-13), so a browser that renders the file anyway runs
it sandboxed and offline.
"""

from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter
from fastapi.responses import Response

from tilo_api import cors, dev
from tilo_api.access import enforced

router = APIRouter()
PATH = "/preview/website"
MAX_HTML_BYTES = 524_288  # AR-10, WS-02
_FEATURES = (
    "accelerometer ambient-light-sensor autoplay battery bluetooth camera clipboard-read clipboard-write "
    "display-capture document-domain encrypted-media fullscreen gamepad geolocation gyroscope hid idle-detection "
    "interest-cohort local-fonts magnetometer microphone midi payment picture-in-picture publickey-credentials-get "
    "screen-wake-lock serial speaker-selection sync-xhr usb web-share window-management xr-spatial-tracking"
).split()
PERMISSIONS_POLICY = ", ".join(f"{feature}=()" for feature in _FEATURES)
_ORIGIN = re.compile(r"^https?://[A-Za-z0-9.-]+(?::[0-9]{1,5})?$")
_SCRIPT = """(function () {
  var allowed = __ORIGINS__;
  function take(event) {
    var data = event.data;
    if (event.source !== window.parent || allowed.indexOf(event.origin) < 0) return;
    if (!data || data.tilo !== "preview" || typeof data.html !== "string") return;
    if (new TextEncoder().encode(data.html).length > __MAX__) return;
    window.removeEventListener("message", take);
    document.open();
    document.write(data.html);
    document.close();
  }
  window.addEventListener("message", take);
  window.parent.postMessage({"tilo": "preview-ready"}, "*");
})();"""


def web_origins() -> list[str]:
    """The web app's origins, as the CORS layer knows them: the two Hosting origins when deployed, the configured
    origins otherwise (dev mode: its own list). Anything that is not a plain origin is dropped."""
    if enforced():
        origins = list(cors.PRODUCTION_ORIGINS)
    elif os.environ.get(dev.ENV_FLAG) == "1":
        raw = os.environ.get(dev.ENV_ORIGINS, dev.DEFAULT_ORIGIN)
        origins = [part.strip() for part in raw.split(",")]
    else:
        origins = cors.cors_origins()
    return [origin for origin in origins if _ORIGIN.fullmatch(origin)]


def content_security_policy(origins: list[str] | None = None) -> str:
    """WS-10: the exact policy of the shell and of a website download."""
    ancestors = " ".join(web_origins() if origins is None else origins) or "'none'"
    return (
        "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src data:; font-src data:; media-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'; "
        "frame-src 'none'; worker-src 'none'; object-src 'none'; manifest-src 'none'; "
        f"frame-ancestors {ancestors}"
    )


def shell(origins: list[str]) -> str:
    script = _SCRIPT.replace("__ORIGINS__", json.dumps(origins)).replace("__MAX__", str(MAX_HTML_BYTES))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Preview</title></head><body>'
        f"<script>{script}</script></body></html>"
    )


@router.get(PATH)
def get_preview_shell() -> Response:
    origins = web_origins()
    return Response(
        shell(origins),
        media_type="text/html",
        headers={
            "Content-Security-Policy": content_security_policy(origins),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
            "Permissions-Policy": PERMISSIONS_POLICY,
        },
    )
