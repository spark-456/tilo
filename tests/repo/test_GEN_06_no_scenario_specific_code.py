"""GEN-05, GEN-06 (issue #272; PRD hard rule "No scenario-specific code", G3, 4.3): nothing in the pipeline names a
scenario, quotes a bank brief, or branches on what a task says. Each rule has a failing negative test on synthetic
files, so a scanner that stopped scanning would be caught. The allowlist (`generality_allowlist.txt`) is for
exceptions, one line each with a reason; an entry that no longer matches anything fails the test.
"""

import ast
import json
import os
import re
from functools import cache
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = ROOT / "tests" / "repo" / "generality_allowlist.txt"

# Pipeline code, prompts and config: where a scenario must never be named. Tests, fixtures, docs and design are not.
PIPELINE = ("packages/*/src", "services/*/src", "evals/src", "prompts", "config")
# Code that decides what a run does with a task: where it must never branch on the task's words.
LOGIC = ("packages/*/src", "services/*/src")
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".ts", ".tsx", ".toml"}
SKIP_PARTS = {"node_modules", ".venv", "__pycache__", "dist", "build"}

# PRD 4.3: a scenario may only use configuration: a skill set, connectors, an autonomy policy, seed data and a theme.
SCENARIO_SCHEMA = ROOT / "contracts" / "scenario.schema.json"
# Until contracts/scenario.schema.json (ADR-0014) is on this branch: the keys PRD 4.3 names plus its id and title.
_PRD_KEYS = {"id", "title", "skills", "connectors", "autonomy", "seed_data", "theme"}


def scenario_keys() -> set[str]:
    """The contract wins: the keys a scenario file may hold are the schema's own properties."""
    if SCENARIO_SCHEMA.exists():
        return set(json.loads(SCENARIO_SCHEMA.read_text(encoding="utf-8"))["properties"])
    return _PRD_KEYS


SCENARIO_NAMES = re.compile(r"\bSC-0[1-9]\b|\bscooter\b|\bK1\b|\bharrier\b|\bkestrel\b", re.IGNORECASE)
CONTENT_NAME = re.compile(
    r"(^|_)(task|goal|text|brief|title|description|prompt|summary|body|subject)(_|$)", re.IGNORECASE
)
CONTENT_METHODS = {"startswith", "endswith", "find", "index", "count"}
REGEX_METHODS = {"search", "match", "fullmatch", "findall", "finditer", "sub"}
MAX_SCAN_BYTES = 300_000  # recorded streams and lockfiles are data, not code; skip them in the text scan
SHINGLE_WORDS = 6  # a run of this many words from a bank brief, anywhere outside the bank, is a leak


def _files(patterns: tuple[str, ...], base: Path = ROOT, suffixes: set[str] = TEXT_SUFFIXES) -> list[Path]:
    found: set[Path] = set()
    for pattern in patterns:
        for start in base.glob(pattern):
            if start.is_file():
                found.add(start) if start.suffix in suffixes else None
                continue
            for folder, dirs, names in os.walk(start):
                dirs[:] = [d for d in dirs if d not in SKIP_PARTS]  # never walk into node_modules or a venv
                found.update(Path(folder) / n for n in names if Path(n).suffix in suffixes)
    return sorted(found)


def _rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def scenario_names(base: Path, patterns: tuple[str, ...] = PIPELINE) -> list[tuple[str, str]]:
    """(file, matched name) for every scenario name in pipeline code, prompts and config."""
    out = []
    for path in _files(patterns, base):
        rel = _rel(path, base)
        if rel.startswith("config/scenarios/"):
            continue  # the one place a scenario is allowed to live: as configuration
        for match in SCENARIO_NAMES.finditer(path.read_text(encoding="utf-8", errors="replace")):
            out.append((rel, match.group(0)))
    return out


def _name_of(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        key = node.slice
        return _name_of(node.value) or (
            key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"lower", "casefold", "strip"}
    ):
        return _name_of(node.func.value)
    return None


def _is_content(node: ast.AST) -> bool:
    name = _name_of(node)
    return bool(name and CONTENT_NAME.search(name))


def _long_strings(node: ast.AST) -> list[str]:
    return [
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) > 3
    ]


def content_branches(base: Path, patterns: tuple[str, ...] = LOGIC) -> list[tuple[str, str]]:
    """(file, enclosing function) for every comparison, string test or regex that sets a task-like value against a
    literal: the shape of `if "invoice" in task_text`. Each must be allowlisted with a reason."""
    out = []
    for path in _files(patterns, base, {".py"}):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)] or [tree]:
            for node in ast.walk(fn):
                hit = False
                if isinstance(node, ast.Compare) and any(
                    isinstance(o, ast.Eq | ast.NotEq | ast.In | ast.NotIn) for o in node.ops
                ):
                    parts = [node.left, *node.comparators]
                    hit = any(_is_content(p) for p in parts) and any(
                        _long_strings(p) for p in parts if not _is_content(p)
                    )
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in CONTENT_METHODS and _is_content(node.func.value):
                        hit = any(_long_strings(a) for a in node.args)
                    elif node.func.attr in REGEX_METHODS:
                        hit = any(_is_content(a) for a in node.args)
                if hit:
                    out.append((_rel(path, base), getattr(fn, "name", "<module>")))
    return sorted(set(out))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def bank_text_leaks(base: Path, bank_dir: Path, exempt: tuple[Path, ...] = ()) -> list[tuple[str, str]]:
    """(file, id of the bank case) for every run of six words of a bank brief found outside `evals/bank/`."""
    quotes: dict[tuple[str, ...], str] = {}
    for case_path in sorted(bank_dir.glob("B-*.yaml")):
        case = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        words = _words(str(case["brief"]))
        for i in range(len(words) - SHINGLE_WORDS + 1):
            quotes.setdefault(tuple(words[i : i + SHINGLE_WORDS]), case["id"])
    leaks = []
    scope = (
        "packages",
        "services",
        "evals/src",
        "evals/tests",
        "config",
        "prompts",
        "skills",
        "templates",
        "tests",
        "contracts",
    )
    for path in _files(scope, base):
        if bank_dir in path.parents or path in exempt or path.stat().st_size > MAX_SCAN_BYTES:
            continue
        words = _words(path.read_text(encoding="utf-8", errors="replace"))
        for i in range(len(words) - SHINGLE_WORDS + 1):
            if (case_id := quotes.get(tuple(words[i : i + SHINGLE_WORDS]))) is not None:
                leaks.append((_rel(path, base), case_id))
                break
    return leaks


def scenario_config_problems(config: object, allowed: set[str] | None = None) -> list[str]:
    """PRD 4.3: a scenario file holds only the keys of contracts/scenario.schema.json (ADR-0014)."""
    if not isinstance(config, dict):
        return ["a scenario file must be a mapping"]
    keys = scenario_keys() if allowed is None else allowed
    return [
        f"key {key!r} is not configuration (allowed: {sorted(keys)})" for key in sorted(set(config) - keys, key=str)
    ]


# ---- the allowlist -----------------------------------------------------------------------------------------


def _allowlist() -> list[tuple[str, str, str, str]]:
    rows = []
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            rule, where, what, reason = (part.strip() for part in line.split("|", 3))
            assert reason, f"an allowlist entry needs a reason: {line!r}"
            rows.append((rule, where, what, reason))
    return rows


def _allowed(rule: str) -> set[tuple[str, str]]:
    return {(where, what) for r, where, what, _ in _allowlist() if r == rule}


# ---- the repo ------------------------------------------------------------------------------------------------


@cache
def _repo_names() -> frozenset[tuple[str, str]]:
    return frozenset(scenario_names(ROOT))


@cache
def _repo_branches() -> frozenset[tuple[str, str]]:
    return frozenset(content_branches(ROOT))


def test_GEN_06_no_scenario_name_in_pipeline_code_prompts_or_config() -> None:
    found = set(_repo_names())
    assert found - _allowed("names") == set(), (
        f"a scenario is named in pipeline code: {sorted(found - _allowed('names'))}"
    )


def test_GEN_06_no_pipeline_code_branches_on_the_words_of_a_task() -> None:
    found = set(_repo_branches())
    assert found - _allowed("branch") == set(), f"code branches on task content: {sorted(found - _allowed('branch'))}"


def test_GEN_06_every_allowlist_entry_still_matches_something() -> None:
    live = {"names": set(_repo_names()), "branch": set(_repo_branches())}
    stale = [(r, w, x) for r, w, x, _ in _allowlist() if (w, x) not in live.get(r, set())]
    assert stale == [], f"remove entries that match nothing: {stale}"


def test_GEN_06_scenario_config_holds_only_configuration() -> None:
    for path in sorted((ROOT / "config" / "scenarios").glob("*.yaml")):  # the directory does not exist yet
        assert scenario_config_problems(yaml.safe_load(path.read_text(encoding="utf-8"))) == [], path.name


def test_GEN_05_no_bank_brief_is_quoted_outside_the_bank() -> None:
    assert bank_text_leaks(ROOT, ROOT / "evals" / "bank") == []


# ---- negative tests: each rule fails on a synthetic violation --------------------------------------------


def _write(base: Path, rel: str, text: str) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("name", ["SC-03", "scooter", "K1", "Harrier", "kestrel"])
def test_GEN_06_names_rule_catches_a_scenario_name(tmp_path, name) -> None:
    _write(tmp_path, "packages/x/src/x/plan.py", f"# special-case the {name} launch\n")
    assert scenario_names(tmp_path) == [("packages/x/src/x/plan.py", name)]
    _write(tmp_path, "prompts/director/plan.md", f"For {name} always add a gate.\n")
    assert ("prompts/director/plan.md", name) in scenario_names(tmp_path)


def test_GEN_06_names_rule_allows_a_scenario_as_configuration(tmp_path) -> None:
    _write(tmp_path, "config/scenarios/sc01.yaml", "theme: city\n# SC-01 competitor analysis\n")
    assert scenario_names(tmp_path) == []


@pytest.mark.parametrize(
    "code",
    [
        'def f(task_text):\n    if "invoice" in task_text:\n        return 1\n',
        'def f(brief):\n    return brief["goal"] == "weekly report"\n',
        'def f(goal):\n    return goal.lower().startswith("plan a trip")\n',
        'import re\ndef f(prompt):\n    return re.search("budget", prompt)\n',
    ],
)
def test_GEN_06_branch_rule_catches_code_that_reads_the_task(tmp_path, code) -> None:
    _write(tmp_path, "packages/p/src/p/logic.py", code)
    assert content_branches(tmp_path) == [("packages/p/src/p/logic.py", "f")]


@pytest.mark.parametrize(
    "code",
    [
        'def f(kind):\n    return kind == "invoice"\n',  # not task content
        "def f(task_text, n):\n    return len(task_text) > n\n",  # a length, not a word
        'def f(task_text):\n    return task_text == ""\n',  # a short literal
    ],
)
def test_GEN_06_branch_rule_leaves_ordinary_code_alone(tmp_path, code) -> None:
    _write(tmp_path, "packages/p/src/p/logic.py", code)
    assert content_branches(tmp_path) == []


def test_GEN_05_bank_rule_catches_a_quoted_brief(tmp_path) -> None:
    bank = tmp_path / "evals" / "bank"
    brief = "Zephyr quantum marmalade orchestrates seventeen velvet lanterns beneath every drifting archipelago tonight"
    _write(tmp_path, "evals/bank/B-001.yaml", yaml.safe_dump({"id": "B-001", "brief": brief}))
    _write(tmp_path, "packages/p/src/p/x.py", f'EXAMPLE = "{brief[10:]}"\n')
    _write(tmp_path, "packages/p/src/p/ok.py", 'X = "nothing to see here at all really"\n')
    assert bank_text_leaks(tmp_path, bank) == [("packages/p/src/p/x.py", "B-001")]


def test_GEN_06_config_rule_refuses_anything_that_is_not_configuration() -> None:
    full = {
        "id": "SC-01",
        "title": "t",
        "skills": [],
        "connectors": [],
        "seed_data": [],
        "theme": "city",
        "autonomy": [],
    }
    assert scenario_config_problems(full) == []
    assert scenario_config_problems({"skills": [], "seed": {}}, allowed={"skills"}) == [
        "key 'seed' is not configuration (allowed: ['skills'])"
    ]
    assert scenario_config_problems({"skills": [], "run_special_code": "x"})
    assert scenario_config_problems(["not", "a", "mapping"])
