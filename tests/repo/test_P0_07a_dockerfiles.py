"""P0-07a: one Dockerfile per deployable service (PRD 6.2, 6.5; CLAUDE.md hard rules).

Convention pinned here: `services/<svc>/Dockerfile`, built with the REPOSITORY ROOT as context (the uv
workspace needs `pyproject.toml`, `uv.lock` and `packages/`), plus a root `.dockerignore`. The final stage runs
`uvicorn <module>:<attr>` where `<module>` lives in `services/<svc>/src` and the service answers `GET /healthz`
(api and sandbox-web already do; harness, channels, connectors, browser and render have no HTTP app yet, so the
builder adds one: PRD 6.2 says all seven are Cloud Run services).

Static only: no docker daemon, no network. Runs with `uv run --no-project --with pytest --with pyyaml pytest`.
"""

from __future__ import annotations

import ast
import pathlib
import re
import tomllib

import pytest

SERVICES = ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"]
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)
MODEL_ID = re.compile(r"(gemini|gemma|gpt-|claude-|llama|nemotron|qwen|mistral)", re.I)
PAID_FLAG = re.compile(r"\b" + "LI" + "VE" + r"\s*=")  # the paid-call switch: never baked into an image


def _instructions(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#") or (not line and not buf):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        op, _, rest = buf.partition(" ")
        out.append((op.upper(), rest.strip()))
        buf = ""
    return out


def _stages(instrs: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    stages: list[list[tuple[str, str]]] = []
    for op, rest in instrs:
        if op == "FROM":
            stages.append([])
        if stages:
            stages[-1].append((op, rest))
    return stages


def _load(repo_root: pathlib.Path, svc: str) -> list[tuple[str, str]]:
    path = repo_root / "services" / svc / "Dockerfile"
    assert path.is_file(), f"P0-07a: services/{svc}/Dockerfile must exist (context = repo root)"
    return _instructions(path.read_text(encoding="utf-8"))


def _from_parts(rest: str) -> tuple[str, str | None]:
    tokens = [t for t in rest.split() if not t.startswith("--")]
    alias = tokens[2] if len(tokens) >= 3 and tokens[1].lower() == "as" else None
    return tokens[0], alias


def _entry_text(instrs: list[tuple[str, str]]) -> str:
    final = _stages(instrs)[-1]
    return " ".join(rest for op, rest in final if op in ("CMD", "ENTRYPOINT"))


@pytest.mark.parametrize("svc", SERVICES)
def test_P0_07a_dockerfile_is_multistage_with_pinned_base_images(repo_root: pathlib.Path, svc: str) -> None:
    instrs = _load(repo_root, svc)
    stages = _stages(instrs)
    assert len(stages) >= 2, "multi-stage build required (builder stage + slim runtime stage)"
    aliases: set[str] = set()
    for stage in stages:
        image, alias = _from_parts(stage[0][1])
        if image not in aliases and image != "scratch":
            assert "$" not in image, f"{image}: base image must be spelled out, not an ARG"
            if "@sha256:" not in image:
                name = image.rsplit("/", 1)[-1]
                tag = name.split(":", 1)[1] if ":" in name else ""
                assert tag and tag != "latest" and tag[0].isdigit(), f"{image}: pin a version tag or a digest"
        if alias:
            aliases.add(alias)
    assert "3.12" in " ".join(r for _, r in instrs), "Python is 3.12 (requires-python ==3.12.*)"


@pytest.mark.parametrize("svc", SERVICES)
def test_P0_07a_dockerfile_final_stage_is_non_root_and_copies_only_from_builder(
    repo_root: pathlib.Path, svc: str
) -> None:
    final = _stages(_load(repo_root, svc))[-1]
    users = [rest.split(":")[0].strip() for op, rest in final if op == "USER"]
    assert users, "final stage must set USER"
    assert users[-1] not in ("root", "0", ""), "final USER must not be root"
    for op, rest in final:
        if op in ("COPY", "ADD"):
            assert rest.startswith("--from="), f"final stage may only copy from an earlier stage, got: {op} {rest}"


@pytest.mark.parametrize("svc", SERVICES)
def test_P0_07a_dockerfile_has_no_secrets_model_ids_or_paid_flags(repo_root: pathlib.Path, svc: str) -> None:
    instrs = _load(repo_root, svc)
    for op, rest in instrs:
        if op in ("ARG", "ENV"):
            tokens = rest.split()
            names = [t.split("=")[0] for t in tokens if "=" in t] or tokens[:1]
            for name in names:
                assert not SECRET_NAME.search(name), f"{op} {name}: no secret-named ARG/ENV in an image"
        assert not PAID_FLAG.search(rest), "no paid-call switch baked into an image (EFF-01)"
        assert not MODEL_ID.search(rest), f"no model id outside config/ and packages/providers (PL-01): {rest}"
        assert not re.search(r"(AIza|-----BEGIN|\.env\b|service-account)", rest), f"secret-looking input: {rest}"
        assert not re.search(r"(curl|wget)[^|]*\|\s*(ba)?sh", rest), "no curl|sh installs"


@pytest.mark.parametrize("svc", SERVICES)
def test_P0_07a_dockerfile_installs_from_the_lockfile_only(repo_root: pathlib.Path, svc: str) -> None:
    instrs = _load(repo_root, svc)
    runs = [rest for op, rest in instrs if op == "RUN"]
    assert any("uv sync" in r and re.search(r"--(frozen|locked)\b", r) for r in runs), "uv sync --frozen/--locked"
    assert any(op == "COPY" and "uv.lock" in rest for op, rest in instrs), "uv.lock is copied into the build"
    assert f"tilo-{svc}" in " ".join(r for _, r in instrs), f"installs the workspace package tilo-{svc}"
    for r in runs:
        for m in re.finditer(r"pip install([^&;|]*)", r):
            args = [a for a in m.group(1).split() if not a.startswith("-")]
            assert all("==" in a for a in args), f"unpinned pip install: {m.group(0)}"


@pytest.mark.parametrize("svc", SERVICES)
def test_P0_07a_dockerfile_runs_the_real_app_on_port_env(repo_root: pathlib.Path, svc: str) -> None:
    entry = _entry_text(_load(repo_root, svc))
    assert "uvicorn" in entry, "CMD/ENTRYPOINT runs uvicorn"
    assert re.search(r"\$\{?PORT\b", entry), "Cloud Run: listen on $PORT"
    assert "0.0.0.0" in entry, "bind 0.0.0.0"
    assert not re.search(r"(sleep|http\.server|tail -f|echo|hello)", entry), "no placeholder entrypoint"

    match = re.search(r"[\"'\s]([A-Za-z_][\w.]*):([A-Za-z_]\w*)[\"'\s]", entry + " ")
    assert match, f"entrypoint must name <module>:<app>, got: {entry}"
    module, attr = match.groups()
    assert module.split(".")[0] == "tilo_" + svc.replace("-", "_"), "module belongs to the service's own package"
    base = repo_root / "services" / svc / "src"
    rel = pathlib.PurePosixPath(*module.split("."))
    source = next((p for p in (base / f"{rel}.py", base / rel / "__init__.py") if p.is_file()), None)
    assert source is not None, f"{module} not found under services/{svc}/src"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            defined |= {a.asname or a.name for a in node.names}
    assert attr in defined, f"{source.name} must define `{attr}`"


@pytest.mark.parametrize("svc", SERVICES)
def test_P0_07a_service_exposes_healthz_and_declares_its_server_dependencies(repo_root: pathlib.Path, svc: str) -> None:
    src = repo_root / "services" / svc / "src"
    assert any('"/healthz"' in p.read_text(encoding="utf-8") for p in src.rglob("*.py")), "GET /healthz route"
    data = tomllib.loads((repo_root / "services" / svc / "pyproject.toml").read_text(encoding="utf-8"))
    deps = [re.match(r"[A-Za-z0-9_.\-]+", d).group(0).lower() for d in data["project"]["dependencies"]]
    assert "uvicorn" in deps, "pyproject must depend on uvicorn (the image runs it)"
    assert {"fastapi", "starlette"} & set(deps), "pyproject must depend on fastapi or starlette"
    assert f'name = "tilo-{svc}"' in (repo_root / "uv.lock").read_text(encoding="utf-8")


def test_P0_07a_dockerignore_keeps_junk_and_secrets_out_but_not_the_workspace(repo_root: pathlib.Path) -> None:
    path = repo_root / ".dockerignore"
    assert path.is_file(), "root .dockerignore must exist"
    lines = {ln.strip().strip("/") for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    lines = {ln.removeprefix("**/") for ln in lines if not ln.startswith(("#", "!"))}

    def has(*names: str) -> bool:
        return any(n in lines for n in names)

    for need in [(".git",), (".venv",), ("node_modules",), (".env*", ".env.*"), ("design",), ("docs",)]:
        assert has(*need), f".dockerignore must exclude {need[0]}"
    assert has("tests", "services/*/tests"), ".dockerignore must exclude tests"
    for keep in ["uv.lock", "pyproject.toml", "packages", "services", "config", "contracts"]:
        assert keep not in lines, f".dockerignore must not exclude {keep} (the workspace install needs it)"
