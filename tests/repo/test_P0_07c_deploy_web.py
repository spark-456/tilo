"""P0-07c: web deployed mode and `just deploy-web` (PRD 6.5, 6.6, SEC-02, EFF-01; builds on P0-07a / PR #349).

Pinned interface: a `deploy-web` recipe in the root justfile builds apps/web WITHOUT `VITE_TILO_API_URL` (the
deployed web app runs the fixture / replay world, no backend needed) and then runs
`firebase deploy --only hosting --project essential-wares-510320-f0` (the dev project). It refuses any other project,
never mentions tilo-demo, uses only uv/pnpm/python/node (CI is Linux, the dev box is native Windows: no bash-only or
PowerShell-only commands) and contains no secrets. `firebase.json` serves apps/web/dist as an SPA with long-cache
immutable headers on hashed assets and no-cache on index.html. `firebase-tools` is a devDependency of apps/web so
`pnpm exec firebase` works from there. docs/deploy-dev.md documents the exact commands and the resulting URL.

The vitest half (chooseClient returns FixtureClient without VITE_TILO_API_URL, and the app never reads a backend
origin otherwise) is in apps/web/src/api/deployedMode.P0-07c.test.ts; the static source guard is here.

Static only: no firebase, no network, no cloud credentials.
"""

from __future__ import annotations

import json
import pathlib
import re

DEV_PROJECT = "essential-wares-510320-f0"
RECIPE_HEADER = re.compile(r"^deploy-web\b[^\n:]*:[^\n]*$", re.M)
SECRET_LIKE = re.compile(
    r"(AIza[0-9A-Za-z_-]{20,}|ya29\.|-----BEGIN|\bpassword\b|\bpasswd\b|--token\b|FIREBASE_TOKEN|GOOGLE_APPLICATION_CREDENTIALS)",
    re.I,
)


def _recipe(repo_root: pathlib.Path) -> str:
    text = (repo_root / "justfile").read_text(encoding="utf-8")
    header = RECIPE_HEADER.search(text)
    assert header, "justfile must define a `deploy-web` recipe"
    # The recipe is its header plus the indented (or blank) lines that follow; stop at the next unindented line.
    lines = text[header.start() :].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace():
            break
        body.append(line)
    return "\n".join(body)


def _hosting(repo_root: pathlib.Path) -> dict:
    hosting = json.loads((repo_root / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    return hosting[0] if isinstance(hosting, list) else hosting


def test_P0_07c_deploy_web_recipe_builds_without_api_url_then_deploys_hosting_to_the_dev_project(
    repo_root: pathlib.Path,
) -> None:
    body = _recipe(repo_root)
    cmd = re.search(r"firebase\s+deploy\s+--only\s+hosting\b[^\n]*", body)
    assert cmd, "recipe must run `firebase deploy --only hosting ...` (via `pnpm exec firebase`)"
    assert re.search(r"pnpm\s+(exec|--filter\s+\S+\s+exec)\s+firebase|pnpm\s+dlx\s+firebase-tools", body), (
        "run firebase through pnpm so the devDependency is used"
    )
    assert re.search(rf"--project[ =]{DEV_PROJECT}\b", cmd.group(0)), f"deploy must pass --project {DEV_PROJECT}"
    build = re.search(r"vite build|run build|pnpm\s+(--filter\s+\S+\s+)?build", body)
    assert build, "recipe must build apps/web before deploying (pnpm --filter @tilo/web run build)"
    assert build.start() < cmd.start(), "the build comes before the deploy"
    # Fixture / replay world: the build must not get an API origin. Neither set nor passed through from the shell.
    code = re.sub(r"(?m)^\s*#.*$", "", body)
    for m in re.finditer(r"VITE_TILO_API_URL(\s*=\s*(\S*))?", code):
        value = (m.group(2) or "").strip("\"'")
        assert m.group(1) is not None and value == "", "the web build must not be given a VITE_TILO_API_URL value"


def test_P0_07c_deploy_web_recipe_refuses_other_projects_and_never_mentions_demo(repo_root: pathlib.Path) -> None:
    body = _recipe(repo_root)
    text = (repo_root / "justfile").read_text(encoding="utf-8")
    assert "tilo-demo" not in body, "deploy-web must never name tilo-demo"
    assert DEV_PROJECT in body, "the dev project id appears in the recipe"
    # No free-form project parameter: either no parameters at all, or a refusal before the deploy when it differs.
    header = RECIPE_HEADER.search(text).group(0)
    params = header.split(":")[0].split()[1:]
    deploy_at = body.index("firebase deploy")
    if params:
        refusal = re.search(r"!=|exit\(1\)|sys\.exit", body)
        assert refusal and refusal.start() < deploy_at, "a parameterised recipe must refuse a non-dev project first"
        assert "essential-wares-510320-f0" in body[: deploy_at + 200]
    # Whatever project ids are mentioned, the only one is the dev project.
    mentioned = set(re.findall(r"--project[ =](\S+)", body))
    assert mentioned and all(p.strip("'\"") in (DEV_PROJECT, "{{project}}", "{{env}}") for p in mentioned), mentioned
    assert "--project" in body and "--only hosting" in body, "hosting only, project pinned"
    assert "--only functions" not in body and "firestore" not in body.lower().replace("firestore.rules", ""), (
        "hosting only: no functions or firestore deploys"
    )


def test_P0_07c_deploy_web_recipe_is_cross_platform_and_secret_free(repo_root: pathlib.Path) -> None:
    body = _recipe(repo_root)
    commands = [ln.strip() for ln in body.splitlines()[1:] if ln.strip() and not ln.strip().startswith("#")]
    assert commands, "deploy-web needs at least one command"
    allowed_first = ("pnpm", "uv", "python", "node", "npx")
    for ln in commands:
        first = ln.lstrip("@-").split()[0]
        assert first in allowed_first, f"`{first}`: only uv/pnpm/python/node commands (cross-platform), got: {ln}"
    assert not re.search(r"\bbash\b|\bsh\s+-c\b|&&\s*export|\bexport\s+\w+=|\$\(|`|\bpowershell\b|\bpwsh\b", body, re.I)
    assert not SECRET_LIKE.search(body), "no secrets, passwords or tokens in the recipe"
    assert "firebase login" not in body, "login is interactive and the user's own: documented, never in the recipe"
    text = (repo_root / "justfile").read_text(encoding="utf-8")
    check_header = re.search(r"^check:.*$", text, re.M).group(0)
    assert "deploy-web" not in check_header, "`just check` must never deploy"


def test_P0_07c_firebase_json_serves_dist_as_spa_with_rewrite_to_index(repo_root: pathlib.Path) -> None:
    hosting = _hosting(repo_root)
    assert hosting["public"] == "apps/web/dist"
    # P0-07e (documented test change): the catch-all `**` became `!/assets/**` so a missing asset 404s. That the
    # source excludes /assets and still covers every route is pinned in test_P0_07e_hosting_routing.py.
    assert any(r.get("destination") == "/index.html" for r in hosting["rewrites"])


def test_P0_07c_firebase_json_caches_hashed_assets_forever_and_never_caches_index_html(
    repo_root: pathlib.Path,
) -> None:
    hosting = _hosting(repo_root)
    rules = hosting.get("headers") or []
    assert rules, "firebase.json hosting.headers must set Cache-Control"

    def cache_control(rule: dict) -> str:
        values = [h["value"] for h in rule["headers"] if h["key"].lower() == "cache-control"]
        return values[0].lower() if values else ""

    def source_of(rule: dict) -> str:
        return rule.get("source") or rule.get("glob") or ""

    asset_rules = [r for r in rules if "assets" in source_of(r)]
    assert asset_rules, "a headers rule must target the hashed Vite assets (/assets/**)"
    for rule in asset_rules:
        cc = cache_control(rule)
        assert "immutable" in cc and "public" in cc, f"hashed assets must be immutable: {cc!r}"
        max_age = re.search(r"max-age=(\d+)", cc)
        assert max_age and int(max_age.group(1)) >= 31536000, f"hashed assets need max-age >= 1 year: {cc!r}"
    index_rules = [r for r in rules if re.search(r"index\.html|^/?\*\*/?\*?\.html$|^/$", source_of(r))]
    assert index_rules, "a headers rule must target index.html"
    for rule in index_rules:
        cc = cache_control(rule)
        assert "no-cache" in cc or "max-age=0" in cc, f"index.html must not be cached: {cc!r}"
        assert "immutable" not in cc


def test_P0_07c_firebase_json_has_no_project_ids_or_secrets(repo_root: pathlib.Path) -> None:
    text = (repo_root / "firebase.json").read_text(encoding="utf-8")
    # SEC-15 / SIGNIN (documented test change, BQ-SIGNIN-5): the Content-Security-Policy must name two origins whose
    # spelling contains a word this guard searches for: the project's own sign-in iframe on its auth domain (it IS the
    # project id; `/__/auth/` is where Firebase serves it) and the SDK's Secure Token REST host (`token`). They are
    # public hostnames, not ids or secrets; they are removed here and nothing else is.
    for origin in ("https://essential-wares-510320-f0.firebaseapp.com/__/auth/", "https://securetoken.googleapis.com"):
        assert text.count(origin) == 1, f"{origin} is named exactly once, in the CSP"
        text = text.replace(origin, "")
    # ADR32 T5b (documented test change): the second Firestore database is named `tilo-tokens` and its rules file
    # `firestore.tokens.rules` in the `firestore` list; both are public names holding the word `token`, each named once.
    for name in ('"tilo-tokens"', "firestore.tokens.rules"):
        assert text.count(name) == 1, f"{name} appears exactly once, in the firestore list"
        text = text.replace(name, "")
    assert not re.search(r"tilo-demo|apiKey|secret|token|essential-wares", text, re.I)


def test_P0_07c_web_package_has_firebase_tools_as_a_dev_dependency(repo_root: pathlib.Path) -> None:
    pkg = json.loads((repo_root / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
    dev = pkg.get("devDependencies", {})
    assert "firebase-tools" in dev, "apps/web devDependencies must include firebase-tools (pnpm exec firebase)"
    assert "firebase-tools" not in pkg.get("dependencies", {}), "a deploy tool is a devDependency, not shipped"
    assert re.match(r"^\^?~?\d+\.\d+\.\d+$", dev["firebase-tools"]), "a concrete version, not latest/*"
    lock = (repo_root / "pnpm-lock.yaml").read_text(encoding="utf-8")
    # The apps/web importer block runs from "\n  apps/web:\n" to the next importer key (two-space indent).
    block = re.search(r"\n  apps/web:\n(.*?)(?=\n  \S|\n\S|\Z)", lock, re.S)
    assert block, "pnpm-lock.yaml must have an apps/web importer"
    recorded = re.search(r"\n {6}firebase-tools:\n {8}specifier: \S+\n {8}version: (\d+\.\d+\.\d+)", block.group(1))
    assert recorded, "pnpm-lock.yaml must record firebase-tools with a concrete version for apps/web"


def test_P0_07c_runbook_documents_the_exact_web_deploy_commands(repo_root: pathlib.Path) -> None:
    text = (repo_root / "docs" / "deploy-dev.md").read_text(encoding="utf-8")
    assert "firebase login" in text, "document `firebase login` (the user signs in; Tilo never handles passwords)"
    assert "just deploy-web" in text, "document `just deploy-web`"
    assert f"https://{DEV_PROJECT}.web.app" in text, "document the resulting URL form"
    assert DEV_PROJECT in text
    low = text.lower()
    assert "fixture" in low or "replay" in low, "say the deployed web app runs the fixture / replay world"
    assert "VITE_TILO_API_URL" in text, "say the deploy build leaves VITE_TILO_API_URL unset"
    ci = re.search(r"[^\n]*(ci|deployer)[^\n]*(no|not|without|never)[^\n]*firebase[^\n]*", text, re.I) or re.search(
        r"[^\n]*firebase[^\n]*(no|not|without|never)[^\n]*(ci|deployer)[^\n]*", text, re.I
    )
    assert ci, "state that the CI deployer has no Firebase role (so Hosting is deployed by hand)"
    section = text.split("## Never", 1)[0]
    assert "tilo-demo" not in re.sub(r"[^\n]*(never|not)[^\n]*", "", section, flags=re.I), (
        "tilo-demo is only ever mentioned as something not to deploy"
    )


def test_P0_07c_web_source_never_reads_a_backend_origin_when_api_url_is_unset(repo_root: pathlib.Path) -> None:
    src = repo_root / "apps" / "web" / "src"
    files = [p for p in src.rglob("*") if p.suffix in (".ts", ".tsx") and ".test." not in p.name]
    assert files
    env_readers: dict[str, list[str]] = {}
    for p in files:
        text = p.read_text(encoding="utf-8")
        for var in re.findall(r"import\.meta\.env\.(VITE_\w+)", text):
            env_readers.setdefault(var, []).append(p.relative_to(src).as_posix())
        # No hard-coded remote origin may be used as an API base outside tests and docs links.
        for url in re.findall(r"""["'`](https?://(?!localhost|127\.0\.0\.1|www\.w3\.org)[^"'`\s]+)""", text):
            host = url.split("/")[2]
            assert not re.search(r"run\.app|cloudfunctions|appspot|googleapis", host), (
                f"{p.name}: hard-coded backend origin {url}; the origin comes only from VITE_TILO_API_URL"
            )
    # SEC-10 (documented test change): App Check needs the Firebase web `apiKey` and `projectId`, which the build
    # supplies (`just deploy-web` reads them from `firebase apps:sdkconfig`; no key literal is committed). They are
    # public client values, not backend origins, and only the App Check starter may read them. The API origin rule
    # is unchanged.
    app_check_vars = {"VITE_FIREBASE_API_KEY", "VITE_FIREBASE_PROJECT_ID"}
    assert set(env_readers) <= {"VITE_TILO_API_URL"} | app_check_vars, (
        f"only VITE_TILO_API_URL and the two App Check config variables may be read: {env_readers}"
    )
    for var in app_check_vars & set(env_readers):
        assert env_readers[var] == ["appcheck/appCheck.ts"], (
            f"{var} is read only by appcheck/appCheck.ts: {env_readers}"
        )
    assert env_readers.get("VITE_TILO_API_URL") == ["api/ClientProvider.tsx"], (
        f"the single reader of VITE_TILO_API_URL is api/ClientProvider.tsx (feeding chooseClient): {env_readers}"
    )
    # The deployed build gets no .env that would set it for production builds.
    for name in (".env", ".env.production", ".env.production.local"):
        assert not (repo_root / "apps" / "web" / name).exists(), (
            f"apps/web/{name} must not exist (would leak an origin)"
        )
