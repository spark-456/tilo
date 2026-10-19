"""M1-SMOKE-1: five bounded, unsigned, read-only deployment checks."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

WEB = "https://essential-wares-510320-f0.web.app"
API_PATTERN = re.compile(r"https://tilo-api-(?:[a-z0-9]+-as\.a\.run\.app|[0-9]+\.asia-southeast1\.run\.app)")
API_REFERENCE = re.compile(API_PATTERN.pattern + r"(?![A-Za-z0-9./:?#+_%=-])")
MAX_BYTES = 20 * 1024 * 1024
MAX_ASSETS = 128  # bounded Vite graph: the deployed Park build exceeds 32 chunks
JS_REFERENCE = re.compile(r"""["']((?:\./|/?assets/)[^"'\s?#]+\.js)["']""")


def bundle_hash(assets: list[tuple[str, str]]) -> str:
    """Stable fingerprint of the fetched JS graph, including asset URLs."""
    return hashlib.sha256(json.dumps(sorted(assets), ensure_ascii=True).encode()).hexdigest()


def release_target(api: str, revision: str, snapshot: str) -> tuple[bool, str]:
    """Read a person's fresh gcloud service snapshot; never call cloud APIs."""
    try:
        path = Path(snapshot)
        if path.stat().st_size > 1024 * 1024:
            return False, ""
        status = json.loads(path.read_text(encoding="utf-8-sig"))["status"]
        traffic = status["traffic"]
        # Tag URLs must identify this service and this exact revision in the snapshot.
        targets = {row["url"] for row in traffic if row.get("revisionName") == revision and row.get("tag")}
        target = next(iter(targets)) if len(targets) == 1 else ""
        if not re.fullmatch(r"https://[a-z0-9-]+---tilo-api-[a-z0-9]+-as\.a\.run\.app", target):
            return False, ""
        percentages = [row.get("percent", 0) for row in traffic]
        valid = all(type(value) is int and 0 <= value <= 100 for value in percentages)
        ok = (
            valid
            and status["url"] == api
            and status["latestReadyRevisionName"] == revision
            and sum(percentages) == 100
            and sum(row.get("percent", 0) for row in traffic if row.get("revisionName") == revision) == 100
        )
        return ok, target
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False, ""


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
    if len(argv) not in (1, 4) or not API_PATTERN.fullmatch(argv[0]):
        print("FAIL url: expected the tilo-api Cloud Run URL")
        return 1
    api = argv[0]
    results: dict[str, bool] = dict.fromkeys(("sign-in", "bundle-api", "health", "cors-intake", "plate-auth"), False)
    target = ""
    if len(argv) == 4:
        if not re.fullmatch(r"tilo-api-[a-z0-9-]+", argv[1]) or not re.fullmatch(r"[a-f0-9]{64}", argv[3]):
            print("FAIL release: expected revision, traffic JSON file and previous SHA256")
            return 1
        results["api-revision-100"], target = release_target(api, argv[1], argv[2])
        results.update({"new-health": False, "bundle-changed": False})
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
            assets: list[tuple[str, str]] = []
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
                assets.append((url, source))
                pending.extend(
                    urljoin(WEB + "/" if path.startswith("assets/") else url, path)
                    for path in JS_REFERENCE.findall(source)
                )
            bundle = "\n".join(bundles)
            results["sign-in"] = "Continue with Google" in page or "Continue with Google" in bundle
            found = set(API_REFERENCE.findall(bundle))
            results["bundle-api"] = found == {api}
            if assets:
                fingerprint = bundle_hash(assets)
                if len(argv) == 4:
                    print(f"BUNDLE-SHA256 {fingerprint}")
                    results["bundle-changed"] = fingerprint != argv[3]
        except (httpx.HTTPError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            print(f"FAIL asset-graph: {reason}")
        for label, method, path in (
            ("health", "GET", "/health"),
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
        if target:
            try:
                results["new-health"] = fetch("GET", target + "/health")[0] == 200
            except (httpx.HTTPError, ValueError):
                pass
    for label, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'} {label}")
    return 0 if all(results.values()) else 1
