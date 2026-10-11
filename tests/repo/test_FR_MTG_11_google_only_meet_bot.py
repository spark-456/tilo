"""FR-MTG-11 (docs/prd-addendum-people-agents.md): Google-only providers for the meeting bot.

Bot model and speech calls go through `packages/providers`; no model id in `meet-bot/`; no ElevenLabs dependency, key
name or call in the submitted build; speech vendor and voice are config. Static checks over git-tracked files only: no
network, no process started, and no read of any untracked or `.env` file. Each rule has a failing negative test on
synthetic input, so a scanner that stopped scanning would be caught.

These are tripwires, not a proof. They catch a vendor name in any spelling (`elevenlabs`, `eleven_labs`, `eleven-labs`,
`11labs`), a static `import`, `importlib.import_module(...)` and `__import__(...)` of a vendor module, and a vendor key
or name that is written as a constant, as a concatenation, an f-string without placeholders or a `"".join` of constants.
They do NOT catch a name built from variables, `getattr`/`globals()` lookups, `base64`/`chr`/`bytes` decoding, a
name read from a file or the network at run time, or a vendor reached through a library that is already allowed (for
example a URL passed to `httpx`). A dynamic import whose module name is not a constant is reported as a problem, so
that route is closed by rule rather than by detection. Review catches the rest."""

from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT = ROOT / "meet-bot"

# A name that belongs to a non-Google model, speech or voice vendor. `openai_compat` is Tilo's own adapter name and a
# `/openai/` URL path is Google's own endpoint.
NON_GOOGLE = re.compile(
    r"eleven[\s_-]*labs|\b11[\s_-]?labs\b|\bxi[_-]api|\bscribe[_ -]?v\d|deepgram|assembly\s*ai|whisper|speechmatics"
    r"|gladia|\bvosk\b|nuance|watson|rev\.ai"
    r"|\bazure\b|amazon\s+(?:transcribe|polly)|aws\s+(?:transcribe|polly)|\bpolly\b|(?<!/)openai(?![_ -]?compat)",
    re.IGNORECASE,
)
# Python modules that are a vendor SDK or a vendor socket (the provider layer's own google imports live in packages/).
VENDOR_MODULES = (
    "google",
    "genai",
    "vertexai",
    "openai",
    "anthropic",
    "websockets",
    "websocket",
    "elevenlabs",
    "deepgram",
    "assemblyai",
    "whisper",
    "azure",
    "boto3",
    "botocore",
    "mistralai",
    "cohere",
    "ollama",
)
VENDOR_KEY_NAME = re.compile(r"^[A-Z][A-Z0-9_]*(?:API_KEY|_TOKEN|_SECRET|_ACCESS_KEY)$")
ADAPTER = "meet-bot/bot/providers.py"


@cache
def tracked() -> tuple[str, ...]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    return tuple(name for name in out.decode("utf-8").split("\0") if name)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="ignore")


def bot_files(suffix: str | None = None) -> list[str]:
    return [f for f in tracked() if f.startswith("meet-bot/") and (suffix is None or f.endswith(suffix))]


def load_lint():
    spec = importlib.util.spec_from_file_location("lint_model_ids", ROOT / "scripts" / "lint_model_ids.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["lint_model_ids"] = module
    spec.loader.exec_module(module)
    return module


# -- (1) model ids ---------------------------------------------------------------------------------------------------
def test_FR_MTG_11_the_tree_is_landed_and_tracked():
    for path in (
        "meet-bot/bot/providers.py",
        "meet-bot/bot/session.py",
        "meet-bot/docker/Dockerfile",
        "meet-bot/.env.example",
    ):
        assert path in tracked(), path


def test_FR_MTG_11_model_id_lint_passes_including_meet_bot_and_does_not_exclude_it():
    lint = load_lint()
    assert not any(prefix.startswith("meet-bot") for prefix in lint.EXCLUDED_PREFIXES)
    assert lint._is_scanned("meet-bot/bot/providers.py") and lint._is_scanned("meet-bot/tests/test_brain.py")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lint_model_ids.py"), str(ROOT)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_FR_MTG_11_no_model_id_anywhere_in_meet_bot_code_tests_docs_env_compose_or_fixtures():
    lint = load_lint()
    known = lint._configured_model_ids(ROOT)
    assert known, "config/models.yaml names the configured ids this scan must also catch"
    hits = []
    for path in bot_files():
        text = read(path)
        found = set(lint.FAMILY_PATTERN.findall(text)) | {m for m in known if m in text}
        hits += [f"{path}: {m}" for m in sorted(found)]
    assert hits == []


def test_FR_MTG_11_the_id_scan_would_catch_an_id_in_a_markdown_file(tmp_path):
    lint = load_lint()
    fake_id = "gemini" + "-9.9-flash"  # built at runtime: PL-01's own lint scans this file too
    assert lint.FAMILY_PATTERN.findall(f"run it with the {fake_id} model")  # a doc is scanned like code here


# -- (2) vendor names ------------------------------------------------------------------------------------------------
def build_files() -> list[str]:
    names = ("pyproject.toml", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml")
    return [
        f
        for f in tracked()
        if Path(f).name in names
        or Path(f).name.startswith("requirements")
        and f.endswith(".txt")
        or f.endswith("Dockerfile.dockerignore")
    ]


def scan_for_vendors(files: Iterable[str]) -> list[str]:
    return [f"{f}: {m.group(0)!r}" for f in files for m in NON_GOOGLE.finditer(read(f))]


def test_FR_MTG_11_no_elevenlabs_and_no_non_google_speech_vendor_in_meet_bot_config_env_or_build_files():
    files = [*bot_files(), *(f for f in tracked() if f.startswith("config/")), *build_files()]
    files = [f for f in files if not f.startswith("meet-bot/tests/fixtures/")]  # recorded Meet pages, not our text
    assert scan_for_vendors(sorted(set(files))) == []


def test_FR_MTG_11_the_dependency_and_env_example_scan_finds_no_elevenlabs_key_or_variable():
    env = read("meet-bot/.env.example")
    assert not re.search(r"eleven|xi_api|scribe", env, re.IGNORECASE)
    assert not re.search(r"^[A-Z_]*(?:API_KEY|_TOKEN|_SECRET)\s*=", env, re.MULTILINE), "the bot holds no vendor key"
    assert "elevenlabs" not in "\n".join(read(f) for f in tracked() if f.endswith("uv.lock")).lower()


def test_FR_MTG_11_the_vendor_scan_would_catch_each_named_vendor(tmp_path):
    for sample in (
        "ElevenLabs",
        "elevenlabs",
        "Deepgram",
        "AssemblyAI",
        "openai",
        "Azure Speech",
        "AWS Transcribe",
        "Whisper",
    ):
        assert NON_GOOGLE.search(f"depends on {sample} now"), sample
    assert not NON_GOOGLE.search("provider: openai_compat") and not NON_GOOGLE.search("provider: google")


# -- (3) SDK imports and key names -----------------------------------------------------------------------------------
def py_imports(source: str) -> list[tuple[str, int, int]]:
    """(module, relative level, line) for every import, top-level and nested."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(a.name, 0, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level, node.lineno))
    return found


def fold(node: ast.AST) -> str | None:
    """The string a simple expression always evaluates to, or None: a constant, `a + b`, an f-string with no
    placeholder, or `"sep".join([constants])`. Anything that needs a variable or a call is not folded."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = fold(node.left), fold(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts = [fold(v) for v in node.values]
        return None if any(p is None for p in parts) else "".join(p for p in parts if p is not None)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.List | ast.Tuple)
    ):
        sep, items = fold(node.func.value), [fold(e) for e in node.args[0].elts]
        return None if sep is None or any(i is None for i in items) else sep.join(i for i in items if i is not None)
    return None


def computed_strings(source: str) -> list[tuple[int, str]]:
    """(line, text) of every string built from constants (not a plain literal): `"ELEVEN" + "LABS_API_KEY"`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant):
            continue
        text = fold(node)
        if text is not None:
            found.append((node.lineno, text))  # type: ignore[attr-defined]
    return found


def dynamic_import_modules(source: str) -> list[tuple[int, str | None]]:
    """(line, module name or None when it is not a constant) of `importlib.import_module(x)` and `__import__(x)`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name in {"import_module", "__import__"}:
            found.append((node.lineno, fold(node.args[0]) if node.args else None))
    return found


def vendor_import_problems(source: str, *, allow_tilo_providers: bool) -> list[str]:
    problems = []
    for module, level, line in py_imports(source):
        top = module.split(".")[0]
        if level == 0 and top in VENDOR_MODULES:
            problems.append(f"line {line}: vendor SDK import {module}")
        if level == 0 and top == "tilo_providers" and not allow_tilo_providers:
            problems.append(f"line {line}: tilo_providers is imported outside the adapter")
    for line, module in dynamic_import_modules(source):
        top = (module or "").split(".")[0]
        if module is None:
            problems.append(f"line {line}: dynamic import of a module name that is not a constant")
        elif top in VENDOR_MODULES or NON_GOOGLE.search(module):
            problems.append(f"line {line}: vendor SDK import {module} through importlib or __import__")
        elif top == "tilo_providers" and not allow_tilo_providers:
            problems.append(f"line {line}: tilo_providers is imported outside the adapter")
    return problems


def vendor_key_problems(source: str) -> list[str]:
    plain = [
        (n.lineno, n.value)
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    problems = [f"line {line}: vendor key name {text!r}" for line, text in plain if VENDOR_KEY_NAME.match(text)]
    # a literal is scanned for names too: `'eleven' '-labs'` is one constant once parsed, though the file text hides it
    problems += [f"line {line}: vendor name {text!r}" for line, text in plain if NON_GOOGLE.search(text)]
    for line, text in computed_strings(source):
        if VENDOR_KEY_NAME.match(text) or NON_GOOGLE.search(text):
            problems.append(f"line {line}: computed vendor key or name {text!r}")
    return problems


def test_FR_MTG_11_no_vendor_sdk_import_and_no_vendor_key_name_in_any_meet_bot_python_file():
    problems = []
    for path in bot_files(".py"):
        source = read(path)
        allow = path == ADAPTER
        problems += [
            f"{path} {p}" for p in vendor_import_problems(source, allow_tilo_providers=allow or "/tests/" in path)
        ]
        problems += [f"{path} {p}" for p in vendor_key_problems(source)]
    assert problems == []


def test_FR_MTG_11_only_the_adapter_in_bot_imports_tilo_providers_and_it_imports_nothing_else_third_party():
    users = [
        p
        for p in bot_files(".py")
        if p.startswith("meet-bot/bot/") and any(m.startswith("tilo_providers") for m, _, _ in py_imports(read(p)))
    ]
    assert users == [ADAPTER]
    std = set(sys.stdlib_module_names)
    third_party = {
        m.split(".")[0]
        for m, level, _ in py_imports(read(ADAPTER))
        if level == 0 and m.split(".")[0] not in std and m.split(".")[0] != "tilo_providers"
    }
    assert (
        third_party == set()
    )  # the adapter imports only tilo_providers (plus the standard library and the bot itself)


def test_FR_MTG_11_the_adapter_reads_no_environment_variable_except_the_providers_own_switches():
    env_reads = {
        n.args[0].value
        for n in ast.walk(ast.parse(read(ADAPTER)))
        if isinstance(n, ast.Call)
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and isinstance(n.args[0].value, str)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"get", "getenv"}
    }
    assert env_reads <= {
        "LIVE",
        "TILO_REPO_ROOT",
        "TILO_MODELS_FILE",
        "TILO_SPEECH_FILE",
        "TILO_VOICE_FILE",
        "TILO_MEETING_FILE",
    }, env_reads


def test_FR_MTG_11_the_import_and_key_scans_would_catch_a_violation():
    assert vendor_import_problems("from google import genai\n", allow_tilo_providers=False)
    assert vendor_import_problems("def f():\n    import websockets\n", allow_tilo_providers=False)
    assert vendor_import_problems("import tilo_providers\n", allow_tilo_providers=False)
    assert not vendor_import_problems("import tilo_providers\n", allow_tilo_providers=True)
    assert not vendor_import_problems("from .brain import Busy\nimport asyncio\n", allow_tilo_providers=False)
    assert vendor_key_problems("import os\nos.environ.get('ELEVENLABS_API_KEY')\n")
    assert vendor_key_problems("k = 'GEMINI_API_KEY'\n") and not vendor_key_problems("k = 'LIVE'\n")


def test_FR_MTG_11_the_tripwires_catch_dynamic_imports_other_spellings_and_computed_names():
    for source in (
        "import importlib\nm = importlib.import_module('elevenlabs')\n",
        "from importlib import import_module\nm = import_module('google.genai')\n",
        "m = __import__('openai')\n",
        "m = __import__('web' + 'sockets')\n",
        "import importlib\nm = importlib.import_module(name)\n",  # not a constant: closed by rule
    ):
        assert vendor_import_problems(source, allow_tilo_providers=False), source
    assert not vendor_import_problems("import importlib\nimportlib.import_module('json')\n", allow_tilo_providers=False)
    assert vendor_import_problems("__import__('tilo_providers')\n", allow_tilo_providers=False)
    for source in (
        "k = 'ELEVEN' + 'LABS_API_KEY'\n",
        "k = ''.join(['GEMINI', '_API_', 'KEY'])\n",
        "k = f'XI_API_KEY'\n",
        "n = 'eleven' + '_labs'\n",
        "n = 'eleven' '-labs'\n",
    ):
        assert vendor_key_problems(source), source
    assert not vendor_key_problems("k = 'a' + 'b'\nj = ','.join(['x', 'y'])\n")
    for sample in ("eleven_labs", "eleven-labs", "Eleven Labs", "11labs", "11 labs", "xi-api-key"):
        assert NON_GOOGLE.search(f"uses {sample} here"), sample
    assert not NON_GOOGLE.search("a 115 labs sample") and not NON_GOOGLE.search("level11 labsolute")


# -- (E) Docker and dependencies ------------------------------------------------------------------------------------
def requirement_names(text: str) -> set[str]:
    names = set()
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.add(re.split(r"[\[<>=!~ ;]", line, maxsplit=1)[0].lower().replace("_", "-"))
    return names


@cache
def provider_dependency_names() -> set[str]:
    deps = tomllib.loads(read("packages/providers/pyproject.toml"))["project"]["dependencies"]
    return requirement_names("\n".join(deps)) | {
        "pydantic",
        "pyyaml",
    }  # pydantic via tilo-contracts, pyyaml read by config


def lock_versions() -> dict[str, str]:
    packages = tomllib.loads(read("uv.lock"))["package"]
    return {p["name"].lower().replace("_", "-"): p["version"] for p in packages}


def pinned_requirements(text: str) -> dict[str, str | None]:
    """name -> the exact version of a `name==x.y.z` line, or None for any other specifier."""
    pins: dict[str, str | None] = {}
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line:
            name = re.split(r"[\[<>=!~ ;]", line, maxsplit=1)[0].lower().replace("_", "-")
            match = re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[^\]]*\])?==([0-9][A-Za-z0-9.+!-]*)", line)
            pins[name] = match.group(1) if match else None
    return pins


def test_FR_MTG_11_every_image_requirement_is_pinned_to_the_version_in_uv_lock():
    pins, lock = pinned_requirements(read("meet-bot/docker/requirements.txt")), lock_versions()
    assert pins and set(pins) - {"playwright"}
    unpinned = sorted(name for name, version in pins.items() if version is None)
    assert unpinned == [], f"pin with ==: {unpinned}"
    drift = {n: (v, lock.get(n)) for n, v in pins.items() if n != "playwright" and lock.get(n) != v}
    assert drift == {}, f"requirements.txt and uv.lock disagree (pin, lock): {drift}"
    image_tag = re.search(r"playwright/python:v([0-9.]+)", read("meet-bot/docker/Dockerfile"))
    assert image_tag and pins["playwright"] == image_tag.group(1), "the playwright pin matches the base image tag"


def test_FR_MTG_11_the_pin_check_would_catch_a_range_a_missing_pin_and_a_drifted_version():
    pins = pinned_requirements("pydantic>=2.11\nhttpx==0.28.1 # c\nGoogle_Auth[requests]==2.58.1\n")
    assert pins == {"pydantic": None, "httpx": "0.28.1", "google-auth": "2.58.1"}
    assert lock_versions().get("httpx") and lock_versions()["httpx"] != "0.0.1"


def test_FR_MTG_11_the_image_requirements_hold_playwright_and_what_the_provider_layer_needs_and_nothing_else():
    names = requirement_names(read("meet-bot/docker/requirements.txt"))
    assert names <= provider_dependency_names() | {"playwright"}, names - provider_dependency_names()
    assert "playwright" in names and "elevenlabs" not in names and "websockets" not in names


def test_FR_MTG_11_the_bots_pyproject_lists_no_vendor_sdk_of_its_own():
    meta = tomllib.loads(read("meet-bot/pyproject.toml"))["project"]
    names = requirement_names("\n".join([*meta["dependencies"], *meta["optional-dependencies"]["dev"]]))
    assert names <= {"pytest", "playwright"}, names


def test_FR_MTG_11_the_dockerfile_copies_every_package_the_adapter_imports_and_the_config_it_reads():
    dockerfile = read("meet-bot/docker/Dockerfile")
    copies = re.findall(r"^COPY(?: --chown=\S+)? (\S+) (\S+)$", dockerfile, re.MULTILINE)
    sources = {src for src, _ in copies}
    package_dirs = {
        "tilo_providers": "packages/providers",
        "tilo_contracts": "packages/contracts-py",
        "tilo_redact": "packages/redact",
    }
    needed = {m.split(".")[0] for m, level, _ in py_imports(read(ADAPTER)) if level == 0 and m.startswith("tilo_")}
    provider_src = ROOT / "packages" / "providers" / "src" / "tilo_providers"
    for path in provider_src.glob("*.py"):  # what the provider layer imports from Tilo, transitively one hop
        needed |= {
            m.split(".")[0]
            for m, level, _ in py_imports(path.read_text(encoding="utf-8"))
            if level == 0 and m.startswith("tilo_")
        }
    needed.discard("tilo_providers_tests")
    assert needed <= set(package_dirs), f"the Dockerfile test does not know where {needed - set(package_dirs)} lives"
    for module in needed:
        assert f"{package_dirs[module]}/src" in sources, f"the image must COPY {package_dirs[module]}/src for {module}"
    for source in (
        "config/models*.yaml",
        "config/prices*.yaml",
        "config/speech*.yaml",
        "config/voice*.yaml",
        "config/meeting*.yaml",
        "prompts/router",
        "prompts/speech",
        "meet-bot/bot",
        "meet-bot/docker/entrypoint.py",
        "meet-bot/docker/requirements.txt",
    ):
        assert source in sources, source
    assert "TILO_REPO_ROOT=/opt/tilo" in dockerfile and "/opt/tilo/packages/providers/src" in dockerfile
    assert (
        "/opt/tilo/packages/contracts-py/src" in dockerfile
        and "/opt/tilo/config" in dockerfile
        and "/opt/tilo/prompts" in dockerfile
    )
    assert "config" not in sources and "prompts" not in sources, "copy only the files the bot reads"


def test_FR_MTG_11_the_compose_build_context_is_the_repo_root_and_the_dockerignore_whitelists_what_is_copied():
    compose = yaml.safe_load(read("meet-bot/docker-compose.yml"))
    build = compose["services"]["bot"]["build"]
    assert build["context"] == ".." and build["dockerfile"] == "meet-bot/docker/Dockerfile"
    assert (BOT / ".dockerignore").exists() is False  # the old context-local ignore file no longer applies
    lines = [
        ln.strip()
        for ln in read("meet-bot/docker/Dockerfile.dockerignore").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    assert lines[0] == "*"
    for keep in (
        "!meet-bot/bot",
        "!meet-bot/docker",
        "!packages/contracts-py/src",
        "!packages/providers/src",
        "!packages/redact/src",
        "!config/models*.yaml",
        "!config/prices*.yaml",
        "!config/speech*.yaml",
        "!config/voice*.yaml",
        "!config/meeting*.yaml",
        "!prompts/router",
        "!prompts/speech",
    ):
        assert keep in lines, keep
    assert "!config" not in lines and "!prompts" not in lines  # not all of config/ and prompts/
    assert not (set(lines) & {"service-account*.json", "*-credentials.json", "application_default_credentials.json"})
    assert not missing_deep_secret_patterns(lines)
    env = compose["services"]["bot"]["environment"]
    assert not any(re.search(r"API_KEY|TOKEN|SECRET", str(name)) for name in env), "no key is passed to the container"


# A bare `service-account*.json` only matches at the context root; a key file at any depth needs `**/`.
DEEP_SECRETS = (
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/service-account*.json",
    "**/*-credentials.json",
    "**/credentials.json",
    "**/application_default_credentials.json",
    "**/client_secret*.json",
    "**/token*.json",
)


def missing_deep_secret_patterns(lines: Iterable[str]) -> list[str]:
    have = set(lines)
    return [pattern for pattern in DEEP_SECRETS if pattern not in have]


def test_FR_MTG_11_the_root_dockerignore_also_excludes_key_files_at_any_depth():
    lines = [ln.strip() for ln in read(".dockerignore").splitlines() if ln.strip() and not ln.startswith("#")]
    assert missing_deep_secret_patterns(lines) == []
    assert not (set(lines) & {"service-account*.json", "*-credentials.json", "application_default_credentials.json"})


def test_FR_MTG_11_the_secret_pattern_check_would_catch_a_root_only_pattern():
    assert missing_deep_secret_patterns(["service-account*.json", "**/.env"])
    assert "**/service-account*.json" in missing_deep_secret_patterns(["service-account*.json"])
    assert missing_deep_secret_patterns(DEEP_SECRETS) == []


def test_FR_MTG_11_the_requirement_scan_would_catch_a_vendor_package():
    assert requirement_names("playwright==1.52.0\nelevenlabs>=1\nwebsockets>=13 # x\n") == {
        "playwright",
        "elevenlabs",
        "websockets",
    }
    assert {"elevenlabs"} - provider_dependency_names()


# -- speech vendor and voice are config -------------------------------------------------------------------------------
def test_FR_MTG_11_speech_and_voice_vendors_are_config_and_google_or_fake_only():
    for name in ("speech.yaml", "speech.dev.yaml", "voice.yaml", "voice.dev.yaml"):
        section = yaml.safe_load(read(f"config/{name}"))[name.split(".")[0]]
        assert section["vendor"] in {"google", "fake"}, name
    assert yaml.safe_load(read("config/voice.yaml"))["voice"]["vendor"] == "google"
    assert yaml.safe_load(read("config/voice.yaml"))["voice"]["voice"]  # the voice name is config, not code
