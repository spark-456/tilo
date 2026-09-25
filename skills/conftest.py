"""Shared fixtures and helpers for the FR-AGT-04 v0 skill-library acceptance suite.

Sources of truth: docs/prd/tilo-prd-v2.md 8.2 (folder shape), 8.6 (FR-AGT-04 and
neighbouring requirements), 16.3 (privilege separation) and contracts/skill.schema.json
(skill.yaml shape). This file holds no test bodies, only discovery and validation
helpers the tests in this directory share.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
CONTRACTS_DIR = REPO_ROOT / "contracts"
LIB_DIR = SKILLS_DIR / "_lib"

# Minimal test wiring (ticket FR-AGT-04 re-scope, point 3): check.py may import the
# shared bounded-guard module as `skills._lib...`. That only resolves if the repo
# root is on sys.path, so the test harness puts it there once, the same way an
# installed package would be importable, rather than leaving each test to hack its
# own sys.path.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The v0 skill library (PRD 8.2 "v0 library (10 skills)", FR-AGT-04): exact
# (domain, skill_id) pairs from the ticket brief. Folder names must match these.
REQUIRED_SKILLS: list[tuple[str, str]] = [
    ("research", "web-research-citations"),
    ("research", "table-extraction"),
    ("commerce", "price-comparison"),
    ("writing", "deck-writing"),
    ("writing", "executive-summary"),
    ("email", "email-triage"),
    ("email", "email-reply-drafting"),
    ("finance", "invoice-po-matching"),
    ("quality", "verification-checklist"),
    ("commerce", "quote-comparison"),
]


def skill_case_id(pair: tuple[str, str]) -> str:
    domain, skill_id = pair
    return f"{domain}/{skill_id}"


REQUIRED_SKILL_CASE_IDS = [skill_case_id(p) for p in REQUIRED_SKILLS]

# Skills that read untrusted content get no side-effect tools (PRD 16.3 point 3,
# privilege separation): the web research skill and both email skills.
UNTRUSTED_READER_SKILLS: list[tuple[str, str]] = [
    ("research", "web-research-citations"),
    ("email", "email-triage"),
    ("email", "email-reply-drafting"),
]
UNTRUSTED_READER_CASE_IDS = [skill_case_id(p) for p in UNTRUSTED_READER_SKILLS]

# action_type substrings counted as a side effect for privilege separation (ticket
# brief: "no send, share, delete or pay action ... send, share, delete, pay, forward,
# post, upload"). Matched as a substring of the action_type slug (e.g. "send_email").
SIDE_EFFECT_TOKENS = ("send", "share", "delete", "pay", "forward", "post", "upload")

# SKILL.md exact level-2 section headings (ticket brief; folder shape PRD 8.2).
REQUIRED_SKILL_MD_HEADINGS = ["When to use", "Steps", "Quality bar", "Checklist", "Pitfalls"]

# Values a malformed check() output is fed, to prove checkers fail closed rather
# than raise (ticket brief: "feed them {} and wrong types; they must return findings").
MALFORMED_OUTPUTS: list[object] = [{}, "not-a-dict", 12345, None, []]


def skill_dir(domain: str, skill_id: str) -> Path:
    return SKILLS_DIR / domain / skill_id


def require_file(path: Path) -> Path:
    if not path.is_file():
        pytest.fail(f"required file missing: {path.relative_to(REPO_ROOT).as_posix()}")
    return path


def load_yaml(path: Path) -> dict:
    require_file(path)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        pytest.fail(f"{path.relative_to(REPO_ROOT).as_posix()} did not parse to a mapping")
    return data


def load_json(path: Path) -> dict:
    require_file(path)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


_registry_cache: Registry | None = None


def _contracts_registry() -> Registry:
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    registry = Registry()
    for name in ("common.schema.json", "skill.schema.json"):
        contents = json.loads((CONTRACTS_DIR / name).read_text(encoding="utf-8"))
        uri = contents["$id"]
        registry = registry.with_resource(uri, Resource.from_contents(contents))
    _registry_cache = registry
    return registry


def skill_contract_validator() -> Draft202012Validator:
    schema = json.loads((CONTRACTS_DIR / "skill.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=_contracts_registry())


def assert_valid_2020_12_schema(schema: object, *, what: str) -> None:
    if not isinstance(schema, dict):
        pytest.fail(f"{what} is not an object")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        pytest.fail(f"{what} is not a valid JSON Schema 2020-12 document: {exc.message}")


def import_check_module(domain: str, skill_id: str) -> ModuleType:
    path = skill_dir(domain, skill_id) / "check.py"
    require_file(path)
    module_name = f"tilo_skill_check__{domain}__{skill_id}".replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load {path.relative_to(REPO_ROOT).as_posix()} as a module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "check") or not callable(module.check):
        pytest.fail(f"{path.relative_to(REPO_ROOT).as_posix()} does not expose a callable check()")
    return module


def _is_allowed_lib_import(dotted: str) -> bool:
    """Ticket FR-AGT-04 re-scope, point 3: check.py may import the shared guard
    module, and only it, as an absolute `skills._lib` import (never a relative
    import, which this function never sees since relative imports are rejected
    before it is called)."""
    return dotted == "skills._lib" or dotted.startswith("skills._lib.")


def assert_stdlib_or_lib_only_imports(path: Path) -> None:
    """check.py may import only the standard library and skills/_lib (ticket
    FR-AGT-04 re-scope, point 3). Anything else, including a relative import,
    is an offender."""
    require_file(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in sys.stdlib_module_names and not _is_allowed_lib_import(alias.name):
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module is None:
                offenders.append("." * node.level)
                continue
            if node.level:
                offenders.append("." * node.level + (node.module or ""))
                continue
            dotted = node.module or ""
            top = dotted.split(".")[0]
            if top and top not in sys.stdlib_module_names and not _is_allowed_lib_import(dotted):
                offenders.append(dotted)
    if offenders:
        rel = path.relative_to(REPO_ROOT).as_posix()
        pytest.fail(f"{rel} imports modules outside stdlib and skills/_lib: {sorted(set(offenders))}")


# Backwards-compatible alias kept only in case another suite still imports the old
# name; the FR-AGT-04 suite itself uses assert_stdlib_or_lib_only_imports.
assert_stdlib_only_imports = assert_stdlib_or_lib_only_imports


COMMENT_LINE_RE = re.compile(r"^\s*#")


def code_line_count(path: Path) -> int:
    """Non-blank, non-comment line count (ticket FR-AGT-04 re-scope, point 4:
    'Hand-written Python across skills/**/check.py and skills/_lib/*.py stays
    under 400 non-blank, non-comment lines in total.'). A line counts unless it
    is empty after stripping, or its first non-space character is '#'; a
    trailing inline comment does not remove an otherwise-code line."""
    text = path.read_text(encoding="utf-8")
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if COMMENT_LINE_RE.match(line):
            continue
        count += 1
    return count


def budget_python_files() -> list[Path]:
    """Every file the FR-AGT-04 re-scope line budget covers: skills/**/check.py
    and skills/_lib/*.py."""
    files = sorted(SKILLS_DIR.glob("*/*/check.py"))
    if LIB_DIR.is_dir():
        files += sorted(LIB_DIR.glob("*.py"))
    return files


HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def extract_level2_headings(text: str) -> list[str]:
    return [m.strip() for m in HEADING_RE.findall(text)]


def extract_section(text: str, heading: str) -> str:
    """Body text of a level-2 section, up to the next level-2 heading or EOF."""
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    return match.group(1) if match else ""


# Check ids are stable slugs (ticket brief). Convention for this suite (PRD 8.2 does
# not specify a listing format): SKILL.md's Quality bar section lists each one as
# inline code, e.g. `citation-source-known`.
CHECK_ID_RE = re.compile(r"`([a-z][a-z0-9-]{1,63})`")


def extract_quality_bar_check_ids(skill_md_text: str) -> set[str]:
    section = extract_section(skill_md_text, "Quality bar")
    return set(CHECK_ID_RE.findall(section))


def golden_case_paths(domain: str, skill_id: str) -> list[Path]:
    d = skill_dir(domain, skill_id) / "tests" / "golden"
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json"))


def example_pairs(domain: str, skill_id: str) -> list[tuple[Path, Path]]:
    d = skill_dir(domain, skill_id) / "examples"
    if not d.is_dir():
        return []
    pairs = []
    for input_path in sorted(d.glob("*.input.json")):
        name = input_path.name[: -len(".input.json")]
        pairs.append((input_path, d / f"{name}.output.json"))
    return pairs


def is_pass_case(expect: object) -> bool:
    return expect == "pass"


def fail_check_id(expect: object) -> str | None:
    if isinstance(expect, dict) and "fail" in expect:
        return expect["fail"]
    return None


@pytest.fixture(scope="session")
def contract_validator() -> Draft202012Validator:
    return skill_contract_validator()
