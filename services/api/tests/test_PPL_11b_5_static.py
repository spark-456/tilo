"""PPL-11b static checks (FR-PA-13, FR-PA-14, FR-PA-17, FR-PA-19; API_PPL_11b.md "Rules for every module" and A14-7):
what a test of behaviour cannot see. An `ast` scan of `services/api/src/tilo_api/assistant/`, `people_access.py`,
`desk.py` and `deps.py` pins that the deterministic core imports no model client and no network library (only
`model.py` and `metering.py` may touch the provider layer), that no model id or profile id sits outside `config/`
(PL-01), that there is one place where an action becomes executable, that nothing evaluates or executes text, that
no log call can carry a question, an answer, a title, a prompt or a model reply, that nothing reads a clock, that
`Directory.of` is built in one place (the route, once per request), and that the oracle is called through the module
attribute with the person as actor and `read_full` as action, never as an agent or `system`.

Written before any implementation: every test fails today because the package does not exist. The checks match
what the spec says and nothing the spec leaves open.
"""

from __future__ import annotations

import ast
import pathlib
import re
import string
import tomllib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "services" / "api" / "src" / "tilo_api"
PKG = SRC / "assistant"
MODULES = ["__init__", "config", "words", "facts", "gate", "core", "navigation", "route", "model", "metering"]
PROVIDER_OK = {"model", "metering"}  # the only modules that may import tilo_providers (metering: types only)
NETWORK = ("anthropic", "openai", "google", "vertexai", "httpx", "requests", "urllib", "socket", "aiohttp", "grpc")
LOG_BANNED = {
    "question", "answer", "text", "lines", "line", "prompt", "raw", "title", "titles", "body", "reply", "output",
    "message", "msg", "content", "exc", "e", "err", "error", "exception", "ex", "label", "data", "payload",
}  # fmt: skip


def _source(path: pathlib.Path) -> tuple[str, ast.Module]:
    assert path.is_file(), f"{path.relative_to(REPO_ROOT).as_posix()} does not exist yet (PPL-11b adds it)"
    text = path.read_text(encoding="utf-8")
    return text, ast.parse(text)


def _package() -> dict[str, tuple[str, ast.Module]]:
    assert PKG.is_dir(), "services/api/src/tilo_api/assistant/ does not exist yet (PPL-11b adds it)"
    return {name: _source(PKG / f"{name}.py") for name in MODULES}


def _everything() -> dict[str, tuple[str, ast.Module]]:
    out = {f"assistant/{name}": src for name, src in _package().items()}
    out["people_access"] = _source(SRC / "people_access.py")
    out["desk"] = _source(SRC / "desk.py")
    return out


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _imports(tree: ast.Module) -> list[tuple[str, list[str]]]:
    found: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, []) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(((node.module or ""), [alias.name for alias in node.names]))
    return found


def _calls(tree: ast.Module) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


# --------------------------------------------------------------------------------------------- layout
def test_FR_PA_14_A14_7_the_package_has_the_modules_of_the_four_slices():
    assert set(_package()) == set(MODULES)
    _source(SRC / "people_access.py")
    _source(SRC / "desk.py")


def test_FR_PA_14_the_package_init_stays_a_docstring_so_parallel_slices_never_conflict():
    _, tree = _package()["__init__"]
    assert len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant)


# --------------------------------------------------------------------------------------------- imports
def test_FR_PA_14_A14_7_no_provider_router_safety_or_network_import_outside_model_metering_and_deps():
    for name, (_, tree) in _everything().items():
        short = name.split("/")[-1]
        for module, names in _imports(tree):
            top = module.split(".")[0]
            assert top not in NETWORK, f"{name} imports {module}: no network client in the panel"
            if short not in PROVIDER_OK:
                assert top != "tilo_providers", f"{name} imports the provider layer; only model.py and metering.py may"
                assert module != "tilo_api.intake" and "get_safety" not in names and "get_router" not in names, (
                    f"{name} reaches for the router or safety provider; they arrive through deps.py (PR-9)"
                )


def test_FR_PA_14_the_deterministic_core_never_imports_the_model_modules():
    for name in ("config", "words", "facts", "gate", "core", "navigation"):
        _, tree = _package()[name]
        for module, names in _imports(tree):
            assert module not in {"tilo_api.assistant.model", "tilo_api.assistant.metering"}, name
            assert not (module == "tilo_api.assistant" and {"model", "metering"} & set(names)), name


def test_FR_PA_14_nothing_imports_a_decider_implementation_but_deps_and_the_route_takes_the_protocol_only():
    _, route = _package()["route"]
    for module, names in _imports(route):
        assert "ModelDecider" not in names and "MeteredDecider" not in names, "the route gets its decider from deps"
        assert module != "tilo_api.assistant.model"


# ------------------------------------------------------------------------- no model id outside config
def _model_and_profile_ids() -> set[str]:
    ids: set[str] = set()
    for path in sorted((REPO_ROOT / "config").glob("models*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for profile_id, profile in doc["profiles"].items():
            ids |= {profile_id, profile["model"]}
    return {i for i in ids if len(i) >= 4}


def test_FR_PA_14_PL_01_no_model_id_or_profile_id_in_the_panel_sources_or_prompts():
    family = re.compile(r"\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-[A-Za-z0-9][A-Za-z0-9_.\-]*")
    ids = _model_and_profile_ids()
    assert ids, "config/models*.yaml names profiles"
    texts = {name: text for name, (text, _) in _everything().items()}
    prompts = REPO_ROOT / "prompts" / "assistant"
    assert prompts.is_dir(), "prompts/assistant/ does not exist yet (11b-3 adds it)"
    texts |= {f"prompts/{p.name}": p.read_text(encoding="utf-8") for p in prompts.glob("*.md")}
    for name, text in texts.items():
        assert not family.search(text), f"{name} names a model family id"
        for known in ids:
            assert not re.search(rf"(?<![A-Za-z0-9_.\-]){re.escape(known)}(?![A-Za-z0-9_.\-])", text), (
                f"{name} names {known!r}: models are configuration (PL-01)"
            )


def test_FR_PA_14_the_prompts_exist_take_exactly_their_variables_and_are_listed_in_the_prompts_readme():
    root = REPO_ROOT / "prompts" / "assistant"
    for name, variables in (
        ("route_system.md", {"intents", "routes"}),
        ("route_task.md", {"question", "screen", "context"}),
    ):
        path = root / name
        assert path.is_file(), f"prompts/assistant/{name} does not exist yet"
        text = path.read_text(encoding="utf-8")
        found = {
            m.group("named") or m.group("braced")
            for m in string.Template.pattern.finditer(text)
            if m.group("named") or m.group("braced")
        }
        assert found == variables, (name, found)
        assert not [m for m in string.Template.pattern.finditer(text) if m.group("invalid")], name
    assert "assistant" in (REPO_ROOT / "prompts" / "README.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------------- sinks and the one executor
def test_FR_PA_14_A14_7_nothing_evaluates_executes_or_imports_text():
    banned_calls = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "os.system",
        "os.popen",
        "pickle.loads",
        "marshal.loads",
        "yaml.load",
        "yaml.unsafe_load",
    }
    for name, (text, tree) in _everything().items():
        assert "querySelector" not in text, name
        for module, _ in _imports(tree):
            assert module.split(".")[0] not in {"importlib", "subprocess", "pickle", "marshal", "ctypes"}, (
                name,
                module,
            )
        for call in _calls(tree):
            assert _dotted(call.func) not in banned_calls, f"{name} calls {_dotted(call.func)}"


def test_FR_PA_14_A14_7_the_ui_action_schema_is_read_in_navigation_only_and_one_function_vets_actions():
    package = _package()
    for name, (text, _) in package.items():
        if name != "navigation":
            assert "ui_action.schema" not in text, f"{name} reads ui_action.schema.json; only navigation.py may (A14-7)"
    assert "ui_action.schema" in package["navigation"][0]
    defs = [
        (name, node.name)
        for name, (_, tree) in _everything().items()
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "vet_navigate"
    ]
    assert defs == [("assistant/navigation", "vet_navigate")], "one place where an action becomes executable"
    core_calls = {_dotted(c.func).split(".")[-1] for c in _calls(package["core"][1])}
    assert "vet_navigate" in core_calls, "the core vets every action, a rule's and a model's alike"
    model_calls = {_dotted(c.func).split(".")[-1] for c in _calls(package["model"][1])}
    assert "vet_navigate" not in model_calls, "the model module only parses; the core vets"


def test_FR_PA_14_text_is_filled_with_string_template_substitute_never_format_and_never_as_a_template():
    package = _package()
    facts_text, facts_tree = package["facts"]
    assert re.search(r"\bTemplate\b", facts_text), "answer lines come from string.Template over config templates"
    assert any(_dotted(c.func).endswith(".substitute") for c in _calls(facts_tree))
    for name in ("facts", "core", "navigation", "route", "gate", "words"):
        _, tree = package[name]
        for call in _calls(tree):
            dotted = _dotted(call.func)
            assert not dotted.endswith(".format") and not dotted.endswith("safe_substitute"), f"{name}: {dotted}"
            if dotted.split(".")[-1] == "Template" and call.args:
                arg = call.args[0]
                assert not (isinstance(arg, ast.Name) and arg.id in {"title", "label", "question", "text", "row"}), name


# --------------------------------------------------------------------------------------------- logs, clocks
def _names_outside_type_calls(node: ast.AST) -> set[str]:
    names: set[str] = set()

    def walk(n: ast.AST) -> None:
        if isinstance(n, ast.Call) and _dotted(n.func) in {"type", "len", "id"}:
            return
        if isinstance(n, ast.Name):
            names.add(n.id)
        if isinstance(n, ast.Attribute):
            names.add(n.attr)
        for child in ast.iter_child_nodes(n):
            walk(child)

    walk(node)
    return names


def test_FR_PA_17_no_log_call_can_carry_a_question_an_answer_a_title_a_prompt_or_a_model_reply():
    for name, (_, tree) in _everything().items():
        for call in _calls(tree):
            dotted = _dotted(call.func)
            if dotted == "print":
                pytest.fail(f"{name}: print() in the panel")
            base, _, method = dotted.rpartition(".")
            if "log" not in base.lower() or method not in {
                "debug",
                "info",
                "warning",
                "error",
                "critical",
                "exception",
                "log",
            }:
                continue
            assert method != "exception", f"{name}: logger.exception logs the exception message; log its type only"
            assert not any(k.arg == "exc_info" for k in call.keywords), f"{name}: exc_info logs the exception message"
            first = call.args[0] if call.args else None
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
                f"{name}: a log message is a constant string with %s arguments, never an f-string or a variable"
            )
            for arg in [*call.args[1:], *[k.value for k in call.keywords]]:
                bad = _names_outside_type_calls(arg) & LOG_BANNED
                assert not bad, f"{name}: a log call carries {sorted(bad)}; codes, kinds and ids only"


def test_FR_PA_17_the_panel_reads_no_clock_now_is_the_one_server_clock_of_the_request():
    clocks = {
        "datetime.now",
        "datetime.utcnow",
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "date.today",
        "datetime.date.today",
        "time.time",
        "time.time_ns",
        "time.monotonic",
        "time.perf_counter",
        "time.monotonic_ns",
        "time.perf_counter_ns",
    }
    for name, (_, tree) in _everything().items():
        for call in _calls(tree):
            assert _dotted(call.func) not in clocks, f"{name} reads a clock: {_dotted(call.func)}"
    route_calls = {_dotted(c.func) for c in _calls(_package()["route"][1])}
    assert "events.now" in route_calls, "the route reads tilo_api.events.now() (once per request)"


# --------------------------------------------------------------------------------------------- the oracle and the org
def test_FR_PA_17_the_oracle_is_called_through_the_module_attribute_as_the_person_with_read_full():
    text, tree = _source(SRC / "people_access.py")
    calls = {_dotted(c.func) for c in _calls(tree)}
    assert calls & {"access.read", "tilo_people.access.read"}, "read_as calls tilo_people.access.read by attribute"
    for name, (_, other) in _everything().items():
        for module, names in _imports(other):
            if module == "tilo_people.access":
                assert not ({"read", "decide"} & set(names)), (
                    f"{name}: import the module, not the function (spies wrap it)"
                )
    for call in [c for t in _everything().values() for c in _calls(t[1]) if _dotted(c.func).endswith("AccessRequest")]:
        keywords = {k.arg: k.value for k in call.keywords}
        assert not isinstance(keywords.get("actor"), ast.Constant), "the actor is the signed-in person, never a literal"
        action = keywords.get("action")
        assert isinstance(action, ast.Constant) and action.value == "read_full", "the panel reads in full (PE-11)"
    assert '"system"' not in text and "'system'" not in text, "no system actor reaches the oracle (BQ-PPL10-11)"


def test_FR_PA_17_the_directory_is_built_in_the_route_once_never_per_row_and_no_org_is_hard_coded():
    for name, (text, tree) in _everything().items():
        sites = [c for c in _calls(tree) if _dotted(c.func) == "Directory.of"]
        assert len(sites) == (1 if name == "assistant/route" else 0), f"{name}: Directory.of call sites {len(sites)}"
        assert not re.search(r"""["']org_[a-z]""", text), f"{name} hard-codes an org id; the org is deps.ORG_ID"
    assert "ORG_ID" in _package()["route"][0]


def test_FR_PA_17_only_the_route_names_the_event_actors_and_the_oracle_modules_name_no_agent():
    for name in ("config", "words", "facts", "gate", "core", "navigation", "model", "metering"):
        text, _ = _package()[name]
        assert "A_assistant" not in text and '"system"' not in text, f"{name}: event actors are the route's alone"
    assert "A_assistant" in _package()["route"][0] and "/v1/assistant/ask" in _package()["route"][0]


# --------------------------------------------------------------------------------------------- wiring
def test_FR_PA_17_deps_has_the_seams_and_the_process_wide_objects_are_cached():
    text, tree = _source(SRC / "deps.py")
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in (
        "get_people_stores",
        "get_plate_source",
        "get_assistant_config",
        "get_assistant_decider",
        "get_spend_ledger",
        "get_decision_cache",
    ):
        assert name in functions, f"deps.{name} does not exist yet"
    for name in ("get_spend_ledger", "get_decision_cache"):
        decorators = {_dotted(d) for d in functions[name].decorator_list}
        assert decorators & {"functools.cache", "cache", "functools.lru_cache", "lru_cache"}, name
    assert "AssistantConfigError" in text and "not_configured" in text


def test_FR_PA_17_the_app_includes_the_assistant_route_and_the_api_depends_on_tilo_people():
    assert "assistant" in (SRC / "__init__.py").read_text(encoding="utf-8")
    project = tomllib.loads((REPO_ROOT / "services" / "api" / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(re.match(r"tilo-people\b", d) for d in project["project"]["dependencies"])
    assert project["tool"]["uv"]["sources"]["tilo-people"] == {"workspace": True}
