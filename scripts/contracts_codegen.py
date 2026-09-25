"""Contract code generation and drift check (tickets P0-02 and P0-03, FR-WLD-02, FR-WLD-03, ADR-0002).

    uv run python scripts/contracts_codegen.py gen     # `just contracts-gen`
    uv run python scripts/contracts_codegen.py check   # `just contracts-check`

Both commands validate every schema under contracts/ (2020-12, $id, x-version, title) and every
fixture: contracts/fixtures/<name>/ against the schema root, contracts/fixtures/<name>.<def>/
against $defs.<def>; valid fixtures must also round-trip through the generated pydantic models.
The event registry, event fixtures and fixture streams are checked by scripts/contracts_events.py
(rules EV-01 to EV-14, contracts/event.rules.md). The config/ files listed in CONFIG_SHAPES must
validate against the contract that owns their shape.
Generation bundles contracts/**/*.schema.json into one schema whose $defs names cannot collide
(common defs keep their name, e.g. RiskTier; other defs get their contract as prefix, e.g.
PlanGate; each contract root is its own name, e.g. Plan; an event data schema is <Type>Data, e.g.
BuildingCompletedData), writes pydantic v2 models with datamodel-code-generator and TypeScript
types with json-schema-to-typescript, and appends the registry constants. gen writes them into
the packages; check regenerates into memory and fails on any difference. Python and Node only, so
it runs the same on Windows and Linux CI.
"""

from __future__ import annotations

import difflib
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urljoin

import contracts_events as events
import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
PY_OUT = Path("packages/contracts-py/src/tilo_contracts")
TS_OUT = Path("packages/contracts-ts/src")
TS_PKG = ROOT / "packages/contracts-ts"
BASE_URI = "https://contracts.tilo.example/"
# config/ file -> the contract (or "<contract>#<$defs entry>") that owns its shape; a trailing
# "[]" means the file is a list of such documents.
CONFIG_SHAPES = {
    "config/models.yaml": "providers#models",
    "config/prices.yaml": "providers#prices",
    "config/autonomy.yaml": "policy#risk_tier_table",
    "config/agents.yaml": "agents",
    "config/teams.yaml": "team_lead[]",
}
# Contract roots whose generated name is not the PascalCase file name.
ROOT_NAMES = {"events/registry": "EventRegistry", "agents": "AgentsConfig"}
# Fixture folders with their own layout, checked by contracts_events.
EVENT_FIXTURES = {"events", "streams"}
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DEF_POINTER = re.compile(r"^/\$defs/(?P<key>[a-z0-9_]+)$")
DATAMODEL_ARGS = [
    "--input-file-type=jsonschema",
    "--output-model-type=pydantic_v2.BaseModel",
    "--target-python-version=3.12",
    "--formatters=builtin",
    "--enum-field-as-literal=all",
    "--use-type-alias",
    "--naming-strategy=primary-first",
    "--skip-root-model",
    "--field-constraints",
    "--use-annotated",
    "--use-union-operator",
    "--use-double-quotes",
    "--use-schema-description",
    "--use-field-description",
    "--strict-nullable",
    "--disable-timestamp",
    "--ignore-pyproject",
    "--no-allow-remote-refs",
    # A uri stays a str so its pattern and maxLength survive (ADR-0002 decision 8).
    "--type-mappings=string+uri=string",
]


def pascal(snake: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_.]", snake))


def root_name(key: str) -> str:
    """Generated name of a contract root: Plan, EventRegistry, AgentsConfig, BuildingCompletedData."""
    if key.startswith("events/data/"):
        return pascal(key.removeprefix("events/data/")) + "Data"
    return ROOT_NAMES.get(key) or pascal(key)


def type_name(key: str, definition: str | None = None) -> str:
    """Generated name of a contract root (definition None) or of one of its $defs."""
    if definition is None:
        return root_name(key)
    return pascal(definition) if key == "common" else root_name(key) + pascal(definition)


def data_model(type_: str) -> str:
    return root_name(f"events/data/{type_}")


def load_schemas() -> dict[str, dict]:
    """Every contracts/**/*.schema.json, keyed by its path under contracts/ without the suffix."""
    paths = sorted(CONTRACTS.glob("**/*.schema.json"), key=lambda p: p.relative_to(CONTRACTS).as_posix())
    return {
        p.relative_to(CONTRACTS).as_posix().removesuffix(".schema.json"): json.loads(p.read_text(encoding="utf-8"))
        for p in paths
        if "fixtures" not in p.relative_to(CONTRACTS).parts
    }


def check_schemas(schemas: dict[str, dict]) -> list[str]:
    errors = []
    for name, schema in schemas.items():
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as error:
            errors.append(f"{name}.schema.json is not a valid 2020-12 schema: {error.message}")
        if schema.get("$id") != f"{BASE_URI}{name}.schema.json":
            errors.append(f"{name}.schema.json: $id must be {BASE_URI}{name}.schema.json")
        if not SEMVER.match(str(schema.get("x-version", ""))):
            errors.append(f"{name}.schema.json: x-version must be a semantic version")
        if schema.get("title") != root_name(name):
            errors.append(f"{name}.schema.json: title must be {root_name(name)}")
    return errors


def fixtures(schemas: dict[str, dict]) -> Iterator[tuple[str, str, str, Path]]:
    """(schema name, $defs key or "", "valid" | "invalid", path) for every schema fixture file."""
    for folder in sorted(p for p in (CONTRACTS / "fixtures").iterdir() if p.is_dir() and p.name not in EVENT_FIXTURES):
        name, _, key = folder.name.partition(".")
        if name not in schemas or (key and key not in schemas[name].get("$defs", {})):
            raise SystemExit(f"contracts: fixtures/{folder.name} names no schema or $defs entry")
        for kind in ("valid", "invalid"):
            files = sorted((folder / kind).glob("*.json"))
            if not files:
                raise SystemExit(f"contracts: fixtures/{folder.name}/{kind}/ is empty")
            yield from ((name, key, kind, path) for path in files)


def validator(schemas: dict[str, dict]) -> events.Validate:
    """validate(name, instance) -> error messages against contracts/<name>.schema.json (or
    "<name>#<def>" for one $defs entry). Validators are built once per schema."""
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012))
        for schema in schemas.values()
    )
    cache: dict[str, jsonschema.protocols.Validator] = {}

    def validate(name: str, instance: object) -> list[str]:
        file, _, key = name.partition("#")
        uri = f"{BASE_URI}{file}.schema.json" + (f"#/$defs/{key}" if key else "")
        if uri not in cache:
            cache[uri] = jsonschema.Draft202012Validator({"$ref": uri}, registry=registry)
        return [
            f"{'/'.join(map(str, error.absolute_path)) or '(root)'}: {error.message}"
            for error in cache[uri].iter_errors(instance)
        ]

    return validate


def check_fixtures(schemas: dict[str, dict], validate: events.Validate) -> list[str]:
    errors = []
    for name, key, kind, path in fixtures(schemas):
        found = validate(f"{name}#{key}" if key else name, load(path))
        if kind == "valid" and found:
            errors.append(f"{path.relative_to(CONTRACTS).as_posix()} fails: {found[:3]}")
        if kind == "invalid" and not found:
            errors.append(f"{path.relative_to(CONTRACTS).as_posix()} validates but must not")
    return errors


def check_config(validate: events.Validate) -> list[str]:
    """config/ files whose shape a contract owns must validate against it (when present; the
    loaders in packages/providers and the policy engine require them)."""
    errors = []
    for relative, shape in CONFIG_SHAPES.items():
        path = ROOT / relative
        if not path.is_file():
            continue
        document, name = yaml.safe_load(path.read_text(encoding="utf-8")), shape.removesuffix("[]")
        items = (document or []) if shape.endswith("[]") else [document]
        if not isinstance(items, list):
            errors.append(f"{relative} must be a list of {name} documents")
            continue
        for index, item in enumerate(items):
            if found := validate(name, item):
                errors.append(f"{relative} item {index} fails {name}: {found[:3]}")
    return errors


def load_module(python: str) -> object:
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / "tilo_contracts_fresh.py"
        path.write_text(python, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("tilo_contracts_fresh", path)
        assert spec and spec.loader
        module = sys.modules["tilo_contracts_fresh"] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def check_models(schemas: dict[str, dict], module: object) -> list[str]:
    """Valid fixtures must load into the generated pydantic models and dump back unchanged."""
    errors = []
    for name, key, kind, path in fixtures(schemas):
        if kind == "valid":
            data, model = load(path), getattr(module, type_name(name, key or None))
            try:
                dumped = model.model_validate(data).model_dump(mode="json", by_alias=True, exclude_unset=True)
            except ValueError as error:
                dumped = str(error)
            if dumped != data:
                errors.append(f"{path.relative_to(CONTRACTS).as_posix()} does not round-trip through {model.__name__}")
    return errors


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def bundle(schemas: dict[str, dict]) -> dict:
    """One schema holding every contract root and $def under a collision-free name."""

    def rewrite(node: object, name: str) -> object:
        if isinstance(node, list):
            return [rewrite(item, name) for item in node]
        if not isinstance(node, dict):
            return node
        out = {k: rewrite(v, name) for k, v in node.items()}
        if isinstance(node.get("$ref"), str):
            uri, _, fragment = urljoin(schemas[name]["$id"], node["$ref"]).partition("#")
            file = uri.removeprefix(BASE_URI).removesuffix(".schema.json")
            pointer = DEF_POINTER.match(fragment)
            if file not in schemas or not uri.startswith(BASE_URI) or (fragment and not pointer):
                raise SystemExit(f"contracts: {name}.schema.json has an unsupported $ref {node['$ref']!r}")
            out["$ref"] = "#/$defs/" + type_name(file, pointer["key"] if pointer else None)
        return out

    defs: dict[str, object] = {}
    for name, schema in schemas.items():
        root = {k: v for k, v in schema.items() if k not in ("$schema", "$id", "$defs", "x-version")}
        entries = [(type_name(name), root)] + [(type_name(name, k), v) for k, v in schema.get("$defs", {}).items()]
        for bundled, sub in entries:
            if bundled in defs:
                raise SystemExit(f"contracts: generated name {bundled} is used twice; rename a $defs entry")
            defs[bundled] = rewrite(sub, name)
    # The root is an empty object on purpose: json-schema-to-typescript emits every $defs entry
    # ("unreachable definitions") only as members of an object root; datamodel-codegen skips it.
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "TiloContracts",
        "description": "Index of the generated contract types; not a document.",
        "type": "object",
        "additionalProperties": False,
        "$defs": defs,
    }


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def header(schemas: dict[str, dict], registry: dict) -> list[str]:
    lines = [
        "GENERATED by scripts/contracts_codegen.py from the JSON Schemas under contracts/ and",
        "contracts/events/registry.yaml. Do not edit. Regenerate with `just contracts-gen`;",
        "`just contracts-check` fails CI on drift (FR-WLD-02, FR-WLD-03).",
    ]
    lines += [f"{name}.schema.json {schema['x-version']} sha256:{digest(schema)}" for name, schema in schemas.items()]
    lines.append(f"events/registry.yaml {registry['version']} sha256:{digest(registry)}")
    return lines


def generate_python(bundled: dict, head: list[str]) -> str:
    with tempfile.TemporaryDirectory() as work:
        source, target = Path(work) / "bundle.json", Path(work) / "models.py"
        source.write_text(json.dumps(bundled, indent=2), encoding="utf-8")
        run(
            [sys.executable, "-m", "datamodel_code_generator", f"--input={source}", f"--output={target}"]
            + DATAMODEL_ARGS
            + ["--custom-file-header=" + "\n".join(f"# {line}" for line in head)]
        )
        return target.read_text(encoding="utf-8")


def draft7_tuples(node: object) -> object:
    """json-schema-to-typescript reads tuples only in the draft-07 spelling (items: [...])."""
    if isinstance(node, list):
        return [draft7_tuples(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {k: draft7_tuples(v) for k, v in node.items()}
    if "prefixItems" in out:
        out["items"], out["additionalItems"] = out.pop("prefixItems"), node.get("items", True)
    return out


def generate_typescript(bundled: dict, head: list[str]) -> str:
    if not (TS_PKG / "node_modules/json-schema-to-typescript/package.json").is_file():
        pnpm = shutil.which("pnpm") or sys.exit("contracts: pnpm not found; run `just setup`")
        print("contracts: json-schema-to-typescript is not installed here; running an offline, frozen pnpm install")
        run([pnpm, "install", "--frozen-lockfile", "--offline"])
    node = shutil.which("node") or sys.exit("contracts: node not found; run `just setup`")
    schema = json.dumps(draft7_tuples(bundled)).encode("utf-8")
    output = run([node, str(TS_PKG / "scripts/json2ts.mjs")], stdin=schema)
    return "\n".join(["/*", *(f" * {line}" for line in head), " */", "", output.replace("\r\n", "\n")])


def run(command: list[str], stdin: bytes | None = None) -> str:
    result = subprocess.run(command, cwd=ROOT, input=stdin, capture_output=True, check=False)
    if result.returncode != 0:
        sys.exit(f"contracts: {Path(command[0]).name} failed:\n{result.stderr.decode('utf-8', 'replace')}")
    return result.stdout.decode("utf-8")


def committed() -> dict[Path, str]:
    files = {}
    for out in (PY_OUT, TS_OUT):
        for path in sorted((ROOT / out).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(ROOT)] = path.read_bytes().decode("utf-8")
    return files


def report(problems: list[str]) -> int:
    print("\n  ".join(["contracts: schema or fixture problems:", *problems]), file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if argv not in (["gen"], ["check"]):
        print(__doc__)
        return 2
    schemas = load_schemas()
    if problems := check_schemas(schemas):
        return report(problems)
    validate, registry = validator(schemas), events.load_registry(CONTRACTS)
    problems = check_fixtures(schemas, validate) + check_config(validate)
    if problems := problems + events.check_registry(CONTRACTS, schemas, registry, validate):
        return report(problems)
    bundled, head = bundle(schemas), header(schemas, registry)
    python = generate_python(bundled, head) + events.python_constants(registry, data_model)
    module = load_module(python)
    problems = check_models(schemas, module)
    if problems := problems + events.check_event_fixtures(CONTRACTS, registry, validate, module, data_model):
        return report(problems)
    typescript = generate_typescript(bundled, head) + events.typescript_constants(registry, data_model)
    fresh = {PY_OUT / "__init__.py": python, PY_OUT / "py.typed": "", TS_OUT / "index.ts": typescript}
    current = committed()
    if argv == ["gen"]:
        for stale in set(current) - set(fresh):
            (ROOT / stale).unlink()
        for path, text in fresh.items():
            (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / path).write_text(text, encoding="utf-8", newline="\n")
        print(f"contracts: generated {len(fresh)} files from {len(schemas)} schemas")
        return 0
    drift = sorted({p.as_posix() for p in set(fresh) | set(current) if fresh.get(p) != current.get(p)})
    for name in drift:
        before, after = current.get(Path(name), "").splitlines(), fresh.get(Path(name), "").splitlines()
        print("\n".join(list(difflib.unified_diff(before, after, name, name, lineterm=""))[:40]), file=sys.stderr)
    if drift:
        print(
            f"contracts: generated types drifted from contracts/ in {drift}; run `just contracts-gen`", file=sys.stderr
        )
        return 1
    print(f"contracts: {len(schemas)} schemas, the event registry, their fixtures and the generated types are in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
