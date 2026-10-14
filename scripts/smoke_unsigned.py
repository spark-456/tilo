"""M1-SMOKE-1: five bounded, unsigned, read-only deployment checks."""

from __future__ import annotations

import re
from collections.abc import Sequence
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

WEB = "https://essential-wares-510320-f0.web.app"
API_PATTERN = re.compile(r"https://tilo-api-(?:[a-z0-9]+-as\.a\.run\.app|[0-9]+\.asia-southeast1\.run\.app)")
API_REFERENCE = re.compile(API_PATTERN.pattern + r"(?![A-Za-z0-9./:?#+_%=-])")
MAX_BYTES = 20 * 1024 * 1024
MAX_ASSETS = 32
JS_REFERENCE = re.compile(r"""["']((?:\./|/assets/)[^"'\s?#]+\.js)["']""")


class Assets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        url = fields.get("src") if tag == "script" else fields.get("href")
        if url and (tag == "script" or tag == "link" and fields.get("rel") == "modulepreload"):
            self.urls.append(url)


def main(argv: Sequence[str], *, transport: httpx.BaseTransport | None = None) -> int:
    if len(argv) != 1 or not API_PATTERN.fullmatch(argv[0]):
        print("FAIL url: expected the tilo-api Cloud Run URL")
        return 1
    api = argv[0]
    results: dict[str, bool] = dict.fromkeys(("sign-in", "bundle-api", "healthz", "cors-intake", "plate-auth"), False)
    with httpx.Client(transport=transport, timeout=15, follow_redirects=False, trust_env=False) as client:
        remaining = MAX_BYTES

        def fetch(method: str, url: str, **kwargs: object) -> tuple[int, httpx.Headers, str]:
            nonlocal remaining
            client.cookies.clear()
            with client.stream(method, url, **kwargs) as response:  # type: ignore[arg-type]
                body = bytearray()
                for chunk in response.iter_bytes():
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise ValueError("response cap")
                    body.extend(chunk)
                return response.status_code, response.headers, body.decode("utf-8", errors="replace")

        try:
            status, _, page = fetch("GET", WEB + "/")
            if status != 200:
                raise ValueError("hosting status")
            parser = Assets()
            parser.feed(page)
            pending = [urljoin(WEB + "/", path) for path in parser.urls]
            seen: set[str] = set()
            bundles: list[str] = []
            while pending:
                url = pending.pop(0)
                parsed = urlsplit(url)
                if url in seen:
                    continue
                if parsed.scheme != "https" or parsed.netloc != urlsplit(WEB).netloc or parsed.query or parsed.fragment:
                    raise ValueError("foreign asset")
                if len(seen) >= MAX_ASSETS:
                    raise ValueError("asset cap")
                seen.add(url)
                status, _, source = fetch("GET", url)
                if status != 200:
                    raise ValueError("asset status")
                bundles.append(source)
                pending.extend(urljoin(url, path) for path in JS_REFERENCE.findall(source))
            bundle = "\n".join(bundles)
            results["sign-in"] = "Continue with Google" in page or "Continue with Google" in bundle
            found = set(API_REFERENCE.findall(bundle))
            results["bundle-api"] = found == {api}
        except (httpx.HTTPError, ValueError):
            pass
        for label, method, path in (
            ("healthz", "GET", "/healthz"),
            ("cors-intake", "OPTIONS", "/intake"),
            ("plate-auth", "GET", "/v1/plate"),
        ):
            try:
                headers = {"X-Tilo-Channel": "web"}
                if method == "OPTIONS":
                    headers.update(
                        {
                            "Origin": WEB,
                            "Access-Control-Request-Method": "POST",
                            "Access-Control-Request-Headers": "authorization,content-type,x-tilo-channel",
                        }
                    )
                status, response_headers, _ = fetch(method, api + path, headers=headers)
                ok = status == (401 if label == "plate-auth" else 200)
                if label == "cors-intake":
                    allowed = {
                        v.strip().lower() for v in response_headers.get("access-control-allow-headers", "").split(",")
                    }
                    methods = {
                        v.strip().upper() for v in response_headers.get("access-control-allow-methods", "").split(",")
                    }
                    ok = (
                        ok
                        and response_headers.get("access-control-allow-origin") == WEB
                        and "POST" in methods
                        and {"authorization", "content-type", "x-tilo-channel"} <= allowed
                    )
                results[label] = ok
            except (httpx.HTTPError, ValueError):
                pass
    for label, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'} {label}")
    return 0 if all(results.values()) else 1
