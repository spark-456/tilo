"""P0-07e: Firebase Hosting routing and header hardening (PRD 6.5, SEC-02; follow-up to P0-07c).

Three things are pinned, all read from the root `firebase.json`:

1. The SPA rewrite must not swallow `/assets/**`. Firebase Hosting only applies a rewrite where no file exists at the
   path, so a stale browser tab asking for a hashed asset that a redeploy removed would otherwise get `index.html`
   with a 200. The browser refuses it as a module script (`X-Content-Type-Options: nosniff`) and the page goes
   blank. A missing asset must be a plain 404. `/`, `/s/foo` and every other app route keep rewriting to
   `/index.html`.
2. Every response served from index.html carries the full security header set and `Cache-Control: no-cache`;
   `/assets/**` overrides the cache header with the immutable one-year policy.
3. The CSP no longer allows inline styles (`style-src 'self'` exactly) and `base-uri` is `'none'`.

How the semantics are checked. Firebase Hosting matches `source` globs with minimatch (the library inside
superstatic, which firebase-tools bundles): the docs show the idiom `!/@(js|css)/**` for "everything except these
folders", and a leading `!` negates the whole pattern. The `/!(assets)/**` shape is wrong: it does not match `/`,
`/index.html` or one-segment routes such as `/foo`, so those would 404. `GlobMatcher` below is a small re-implementation
of the minimatch subset firebase.json uses here (`**`, `*`, `?`, literals, leading `!`) INCLUDING minimatch's default
`dot: false`: `**` never matches a dot segment, so `/.x`, `/foo/.bar` and `/.well-known/x` match `!/assets/**` (they
get the SPA shell) but do not match a `**` headers rule (they would get no headers). The invariant test below pins
that no path served from index.html can miss a header, however the builder writes the rules (globs or `regex`).
One test cross-checks GlobMatcher against the real minimatch when `pnpm install` has been run (skipped otherwise;
this suite also runs before `just setup`).

Header precedence. The Hosting docs do not state which of several matching header rules wins for the same key.
superstatic 10.0.0 (`lib/middleware/headers.js`, the same code the Hosting emulator runs) collects the headers of
every matching rule in file order and calls `res.setHeader` for each, so a later rule overrides an earlier one for the
same key. `effective_headers` follows that, so rule order is checked implicitly through the effective values.

Static only: no firebase run, no network, no cloud credentials.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

SPA_DESTINATION = "/index.html"
IMMUTABLE = "public, max-age=31536000, immutable"

# Paths a deployed SPA really sees. `ROUTES` have no static file behind them (client-side routes) and must fall
# back to the SPA shell; `ASSETS` are Vite's hashed output, which exists on disk or is a 404, never the SPA shell.
ROUTES = ["/", "/index.html", "/s/foo", "/foo", "/s/foo/bar", "/settings/profile", "/s/assets-overview"]
# Dot paths: minimatch's `dot: false` makes `**` skip them, so a glob rewrite and a glob header rule can disagree on
# them. Whether they get the SPA shell or a 404 is the builder's choice; whatever gets the shell must get every header.
# (`**/.*` in `ignore` keeps dot files out of the upload, so no static file ever answers these.)
DOT_PATHS = ["/.x", "/foo/.bar", "/.well-known/x", "/.a/.b/c", "/assets/.x"]
ASSETS = ["/assets/index-abc123.js", "/assets/index-abc123.css", "/assets/nested/chunk-9f8e7d.js", "/assets/missing.js"]


class GlobMatcher:
    """The minimatch subset used by firebase.json sources, with minimatch's default `dot: false`.

    Supports `**`, `*`, `?`, literals and a leading `!` negation. As in minimatch, `*`, `?` and `**` never match a
    path segment that starts with `.` unless the pattern segment itself starts with a literal `.`; so `**` does NOT
    match `/.x` or `/foo/.bar`. A `**` that ends the pattern needs at least one more (possibly empty) segment, so
    `/assets/**` matches `/assets/` but not `/assets`.
    """

    def __init__(self, source: str) -> None:
        self.negated = source.startswith("!")
        glob = source[1:] if self.negated else source
        self.parts = glob.split("/")

    @staticmethod
    def _segment(pattern: str, segment: str) -> bool:
        if segment.startswith(".") and not pattern.startswith("."):
            return False
        if segment == "" and pattern != "":
            return False  # minimatch: `*` and `?` never match an empty segment
        regex = "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in pattern)
        return re.fullmatch(regex, segment) is not None

    def _match(self, pattern: list[str], path: list[str]) -> bool:
        if not pattern:
            return not path
        head, rest = pattern[0], pattern[1:]
        if head == "**":
            # Zero or more non-dot segments; as the last pattern segment it needs at least one.
            for taken in range(0 if rest else 1, len(path) + 1):
                if taken and path[taken - 1].startswith("."):
                    return False
                if self._match(rest, path[taken:]):
                    return True
            return False
        return bool(path) and self._segment(head, path[0]) and self._match(rest, path[1:])

    def matches(self, path: str) -> bool:
        return self._match(self.parts, path.split("/")) != self.negated


class RegexMatcher:
    """A Hosting `regex` source (RE2 in production; unanchored search, like superstatic's `path.match`)."""

    def __init__(self, regex: str) -> None:
        self.regex = re.compile(regex)

    def matches(self, path: str) -> bool:
        return self.regex.search(path) is not None


def _matcher(rule: dict) -> GlobMatcher | RegexMatcher:
    """Matcher for a rewrite/header rule, whichever of `source`, `glob` or `regex` it uses."""
    if "regex" in rule:
        return RegexMatcher(rule["regex"])
    return GlobMatcher(rule.get("glob") or rule["source"])


def _hosting(repo_root: pathlib.Path) -> dict:
    hosting = json.loads((repo_root / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    return hosting[0] if isinstance(hosting, list) else hosting


def rewrite_for(repo_root: pathlib.Path, path: str) -> str | None:
    """Destination of the first rewrite whose source matches `path`, assuming no static file exists there."""
    for rule in _hosting(repo_root).get("rewrites", []):
        if _matcher(rule).matches(path):
            return rule["destination"]
    return None


def effective_headers(repo_root: pathlib.Path, path: str) -> dict[str, str]:
    """Response headers for `path`: matching rules applied in file order, later rules overriding earlier ones."""
    out: dict[str, str] = {}
    for rule in _hosting(repo_root).get("headers", []):
        if _matcher(rule).matches(path):
            for h in rule["headers"]:
                out[h["key"].lower()] = h["value"]
    return out


def _directives(csp: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for part in csp.split(";"):
        tokens = part.split()
        if tokens:
            result[tokens[0].lower()] = tokens[1:]
    return result


# -- 1. the SPA rewrite does not swallow /assets/** ---------------------------------------------------------------


@pytest.mark.parametrize("path", ASSETS)
def test_P0_07e_missing_asset_is_not_rewritten_to_index_html(repo_root: pathlib.Path, path: str) -> None:
    assert rewrite_for(repo_root, path) is None, (
        f"{path}: a missing hashed asset must 404, not get {SPA_DESTINATION} (nosniff then blocks it as a module "
        "script and a stale tab goes blank)"
    )


@pytest.mark.parametrize("path", ROUTES)
def test_P0_07e_app_routes_still_rewrite_to_index_html(repo_root: pathlib.Path, path: str) -> None:
    assert rewrite_for(repo_root, path) == SPA_DESTINATION, f"{path} must still fall back to the SPA shell"


def test_P0_07e_rewrite_source_is_the_negated_assets_glob(repo_root: pathlib.Path) -> None:
    # Exact form pinned on purpose: `!/assets/**` is the Hosting-docs idiom (`!/@(js|css)/**`) and is the only
    # single-glob shape that keeps `/`, `/foo` and `/s/foo` rewriting; `/!(assets)/**` would 404 `/` and `/foo`.
    rewrites = _hosting(repo_root)["rewrites"]
    assert {"source": "!/assets/**", "destination": SPA_DESTINATION} in rewrites
    assert {"source": "**", "destination": SPA_DESTINATION} not in rewrites, "the catch-all rewrite must be gone"


def test_P0_07e_glob_model_agrees_with_real_minimatch(repo_root: pathlib.Path) -> None:
    """Cross-check GlobMatcher (dot: false) against the minimatch in firebase-tools. Skipped before `pnpm install`."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (
        "const {createRequire}=require('module');const path=require('path');"
        "const r1=createRequire(path.join(process.argv[1],'apps/web/package.json'));"
        "const r2=createRequire(r1.resolve('firebase-tools/package.json'));"
        "const r3=createRequire(r2.resolve('superstatic/package.json'));"
        "const mm=r3('minimatch');"
        "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{"
        "console.log(JSON.stringify(JSON.parse(s).map(([g,p])=>mm(p,g))))});"
    )
    hosting = _hosting(repo_root)
    rules = hosting.get("rewrites", []) + hosting.get("headers", [])
    sources = {r.get("glob") or r["source"] for r in rules if "regex" not in r}
    sources |= {"!/assets/**", "**", "/**", "/assets/**", "/index.html", "/", "/*.js", "/.*"}
    paths = ROUTES + DOT_PATHS + ASSETS + ["/assets/", "/.js", "/a.js", "/a/.js"]
    pairs = [[g, p] for g in sorted(sources) for p in paths]
    proc = subprocess.run(
        [node, "-e", script, str(repo_root)],
        input=json.dumps(pairs),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"firebase-tools/superstatic/minimatch not installed: {proc.stderr.strip()[-200:]}")
    real = json.loads(proc.stdout)
    for (glob, path), expected in zip(pairs, real, strict=True):
        assert GlobMatcher(glob).matches(path) == expected, f"model disagrees with minimatch on {glob!r} vs {path!r}"


# -- 2. headers: no-cache for the shell, immutable for hashed assets, nothing missed -------------------------------


def test_P0_07e_every_route_gets_no_cache_by_default(repo_root: pathlib.Path) -> None:
    for path in ROUTES:
        assert effective_headers(repo_root, path).get("cache-control") == "no-cache", path


@pytest.mark.parametrize("path", ASSETS)
def test_P0_07e_hashed_assets_keep_the_immutable_cache_policy(repo_root: pathlib.Path, path: str) -> None:
    # Also pins rule order: the immutable rule must override the default for the same key (later rule wins).
    assert effective_headers(repo_root, path).get("cache-control") == IMMUTABLE, path


def test_P0_07e_security_headers_still_cover_assets_and_routes(repo_root: pathlib.Path) -> None:
    for path in ROUTES + ASSETS:
        headers = effective_headers(repo_root, path)
        assert "content-security-policy" in headers, path
        assert headers["x-content-type-options"].lower() == "nosniff", path
        assert headers["referrer-policy"].lower() == "strict-origin-when-cross-origin", path


def test_P0_07e_every_path_that_gets_the_spa_shell_gets_every_security_header_and_no_cache(
    repo_root: pathlib.Path,
) -> None:
    """Invariant, however the rules are written: no response served from index.html lacks CSP/nosniff/Referrer-Policy.

    minimatch skips dot segments for `**`, so `!/assets/**` rewrites `/.x` or `/foo/.bar` to index.html while a `**`
    headers rule does not match them; that gap must not exist (fix it with a `regex` header rule, or keep dot paths
    out of the rewrite; either satisfies this test).
    """
    for path in ROUTES + DOT_PATHS + ASSETS:
        if rewrite_for(repo_root, path) != SPA_DESTINATION:
            continue
        headers = effective_headers(repo_root, path)
        csp = _directives(headers.get("content-security-policy", ""))
        assert csp.get("frame-ancestors") == ["'none'"], f"{path} is served index.html without a framing-safe CSP"
        assert headers.get("x-content-type-options", "").lower() == "nosniff", f"{path}: missing nosniff"
        assert headers.get("referrer-policy", "").lower() == "strict-origin-when-cross-origin", (
            f"{path}: missing Referrer-Policy"
        )
        assert headers.get("cache-control") == "no-cache", f"{path}: index.html must not be cached"


def test_P0_07e_dot_paths_never_get_the_immutable_cache_policy(repo_root: pathlib.Path) -> None:
    for path in DOT_PATHS:
        assert effective_headers(repo_root, path).get("cache-control") != IMMUTABLE, path


# -- 3. CSP: no inline styles, base-uri 'none' --------------------------------------------------------------------


def test_P0_07e_csp_style_src_is_self_only(repo_root: pathlib.Path) -> None:
    csp = _directives(effective_headers(repo_root, "/")["content-security-policy"])
    assert csp["style-src"] == ["'self'"], f"style-src must be exactly 'self', got {csp.get('style-src')}"
    assert not any("'unsafe-inline'" in sources for sources in csp.values()), "no directive may allow 'unsafe-inline'"


def test_P0_07e_csp_base_uri_is_none(repo_root: pathlib.Path) -> None:
    csp = _directives(effective_headers(repo_root, "/")["content-security-policy"])
    assert csp["base-uri"] == ["'none'"], f"base-uri must be 'none', got {csp.get('base-uri')}"
