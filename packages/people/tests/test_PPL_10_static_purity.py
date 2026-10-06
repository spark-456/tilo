"""PPL-10 (all slices): `tilo_people` is pure and deterministic (API.md "Rules for every module",
packages/people/CLAUDE.md "Local rules"; PE-11, PE-15, PE-19; FR-PA-11).

An `ast` scan of every module under `packages/people/src/tilo_people` (the same technique as
packages/policy/tests/test_no_model_in_decision.py, wider). It forbids, in the source:

- importing a provider, network, randomness, logging, database, subprocess or clock-reading module;
- calling `print`, `open`, `eval`, `exec`, `__import__`, or any clock, randomness, environment or
  file call (`now`, `utcnow`, `today`, `time`, `time_ns`, `monotonic`, `uuid4`, `getenv`, `read_text`, ...);
- validating against the generated pydantic models (they drop `if`/`then`, ADR-0002) instead of
  `tilo_policy.schemas.conforms`;
- a model, provider or vendor id anywhere (PL-01).

One parametrised row per module of API.md, so a slice that has not landed fails only its own rows; a
last test scans every other file under `src/` (private helper modules are allowed, impure ones are not).
`__init__.py` stays a docstring (parallel slices must never conflict there).
"""

from __future__ import annotations

import ast
import re

import _ppl10_testlib as t
import pytest

MODULES = ["errors", "text", "directory", "access", "crossref", "names", "dates", "writes", "stores"]
SLICE = {
    "errors": "10a",
    "text": "10a",
    "directory": "10a",
    "access": "10a",
    "crossref": "10a",
    "names": "10b",
    "dates": "10b",
    "writes": "10c",
    "stores": "10d",
}

FORBIDDEN_IMPORTS = {
    # providers and models (PL-01)
    "tilo_providers",
    "google",
    "openai",
    "anthropic",
    "vertexai",
    "firebase_admin",
    "grpc",
    # network
    "socket",
    "ssl",
    "requests",
    "httpx",
    "urllib",
    "urllib3",
    "http",
    "aiohttp",
    "smtplib",
    "asyncio",
    # randomness and identity minting
    "random",
    "secrets",
    "uuid",
    # logging and printing
    "logging",
    "warnings",
    "pprint",
    # a clock, the environment, files, processes, a database, dynamic import
    "time",
    "os",
    "sys",
    "subprocess",
    "pathlib",
    "shutil",
    "tempfile",
    "sqlite3",
    "importlib",
    # the generated models and a second validator (use tilo_policy.schemas.conforms)
    "tilo_contracts",
    "pydantic",
    "jsonschema",
    "referencing",
}
FORBIDDEN_NAME_CALLS = {
    "print",
    "open",
    "eval",
    "exec",
    "compile",
    "input",
    "__import__",
    "breakpoint",
    "globals",
    "locals",
    "vars",
}
FORBIDDEN_ATTRIBUTE_CALLS = {
    "now",
    "utcnow",
    "today",
    "time",
    "time_ns",
    "monotonic",
    "monotonic_ns",
    "perf_counter",
    "process_time",
    "urandom",
    "uuid1",
    "uuid4",
    "getenv",
    "putenv",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "open",
    "getrandom",
    "randbytes",
    "choice",
    "shuffle",
    "sample",
    "randint",
}
AMBIENT_ATTRIBUTES = {"environ", "argv", "stdin", "stdout", "stderr"}
MODEL_IDS = re.compile(
    r"gemini|gpt-?[0-9]|claude-|llama|nemotron|mistral|gemma|text-embedding|nvidia|openai|anthropic|vertex",
    re.IGNORECASE,
)


def _parse(path):
    assert path.is_file(), (
        f"packages/people/src/tilo_people/{path.name} does not exist yet (slice PPL-{SLICE.get(path.stem, '10')})"
    )
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def forbidden_imports(path):
    found = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]] if node.level == 0 else []
        else:
            continue
        found += [(node.lineno, n) for n in names if n in FORBIDDEN_IMPORTS]
    return found


def forbidden_calls(path):
    found = []
    for node in ast.walk(_parse(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in FORBIDDEN_NAME_CALLS:
            found.append((node.lineno, func.id))
        elif isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_ATTRIBUTE_CALLS:
            found.append((node.lineno, "." + func.attr))
    return found


def ambient_state(path):
    found = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Attribute) and node.attr in AMBIENT_ATTRIBUTES:
            found.append((node.lineno, node.attr))
        if isinstance(node, ast.Name) and node.id in {"__file__", "__builtins__"}:
            found.append((node.lineno, node.id))
    return found


def model_ids(path):
    _parse(path)
    return [
        (n, line.strip()[:80])
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if MODEL_IDS.search(line)
    ]


def generated_model_use(path):
    text = path.read_text(encoding="utf-8")
    _parse(path)
    return [
        word for word in ("model_validate", "parse_obj", "BaseModel", "tilo_contracts", "contracts_py") if word in text
    ]


@pytest.mark.parametrize("module", MODULES)
def test_PPL_10_PE_19_the_module_exists_and_imports_no_provider_network_clock_logging_or_file_module(module):
    assert not forbidden_imports(t.SRC / f"{module}.py")


@pytest.mark.parametrize("module", MODULES)
def test_PPL_10_PE_19_the_module_never_prints_opens_files_reads_a_clock_or_draws_randomness(module):
    assert not forbidden_calls(t.SRC / f"{module}.py")


@pytest.mark.parametrize("module", MODULES)
def test_PPL_10_PE_19_the_module_reads_no_environment_through_attribute_access(module):
    assert not ambient_state(t.SRC / f"{module}.py")


@pytest.mark.parametrize("module", MODULES)
def test_PPL_10_PL_01_no_model_or_vendor_id_appears_in_the_module(module):
    assert not model_ids(t.SRC / f"{module}.py")


@pytest.mark.parametrize("module", MODULES)
def test_PPL_10_ADR_0002_the_module_validates_through_tilo_policy_conforms_never_the_generated_models(module):
    assert not generated_model_use(t.SRC / f"{module}.py")


def test_PPL_10_PE_19_every_other_file_under_src_is_scanned_too_private_helpers_included():
    files = sorted(p for p in t.SRC.rglob("*.py") if p.stem not in MODULES and p.name != "__init__.py")
    problems = {}
    for path in files:
        found = [
            *forbidden_imports(path),
            *forbidden_calls(path),
            *ambient_state(path),
            *model_ids(path),
            *generated_model_use(path),
        ]
        if found:
            problems[str(path.relative_to(t.SRC))] = found
    assert not problems, problems


def test_PPL_10_PE_19_the_nine_modules_of_api_md_all_exist():
    missing = [m for m in MODULES if not (t.SRC / f"{m}.py").is_file()]
    assert not missing, f"missing modules {missing}"


def test_PPL_10_PE_19_init_stays_a_docstring_so_parallel_slices_never_conflict():
    init = t.SRC / "__init__.py"
    assert init.is_file()
    body = ast.parse(init.read_text(encoding="utf-8")).body
    assert all(
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str) for n in body
    ), "tilo_people/__init__.py must hold at most a docstring (API.md): import each name from its module"


def test_PPL_10_PE_19_the_package_declares_only_the_dependencies_it_needs():
    """tilo-policy (the schema checker) and tzdata (zones on Windows and slim images); nothing else."""
    import tomllib

    config = tomllib.loads((t.REPO_ROOT / "packages" / "people" / "pyproject.toml").read_text(encoding="utf-8"))
    names = {re.split(r"[<>=!~ \[]", d, maxsplit=1)[0] for d in config["project"]["dependencies"]}
    assert names == {"tilo-policy", "tzdata"}, names
