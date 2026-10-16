from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from tilo_contracts import PlanMakeChoice, PlanMakeOption

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CONFIG_DIR = _REPO_ROOT / "config"
_CONTRACTS_DIR = _REPO_ROOT / "contracts"


class MakerConfigError(ValueError):
    pass


class MakerSelectionError(ValueError):
    pass


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise MakerConfigError("Maker choices are not configured correctly.") from exc


def _contracts_registry(contracts_dir: Path) -> Registry:
    resources = []
    for path in contracts_dir.rglob("*.schema.json"):
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MakerConfigError("Maker choices are not configured correctly.") from exc
        resources.append((schema.get("$id") or path.resolve().as_uri(), Resource.from_contents(schema, DRAFT202012)))
    return Registry().with_resources(resources)


def load_makers_config(*, config_dir: Path = _CONFIG_DIR, contracts_dir: Path = _CONTRACTS_DIR) -> dict[str, Any]:
    raw = _read_yaml(config_dir / "makers.yaml")
    try:
        schema = json.loads((contracts_dir / "makers.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema, registry=_contracts_registry(contracts_dir))
        validator.validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError, jsonschema.ValidationError) as exc:
        raise MakerConfigError("Maker choices are not configured correctly.") from exc

    connectors = _read_yaml(config_dir / "connectors.yaml") or []
    canva = _read_yaml(config_dir / "canva.yaml") or []
    mcp = _read_yaml(config_dir / "mcp.yaml") or {}
    if not isinstance(connectors, list) or not isinstance(canva, list) or not isinstance(mcp, dict):
        raise MakerConfigError("Maker choices are not configured correctly.")
    declared = {item.get("id"): item for item in [*connectors, *canva] if isinstance(item, dict)}
    allowlist = mcp.get("servers", [])
    if not isinstance(allowlist, list):
        raise MakerConfigError("Maker choices are not configured correctly.")

    for options in raw["formats"].values():
        for partner in options["partners"]:
            make_with, action = partner["make_with"], partner["action"]
            if make_with.startswith("connector:"):
                connector_id = make_with.removeprefix("connector:")
                record = declared.get(connector_id)
                actions = record.get("actions", []) if record else []
                actions = actions if isinstance(actions, list) else []
                found = next((a for a in actions if isinstance(a, dict) and a.get("id") == action), None)
                if not found or found.get("risk_tier") != "T3" or found.get("gate_type") != "approval":
                    raise MakerConfigError("Maker choices are not configured correctly.")
            elif make_with.startswith("mcp:"):
                _, server_id, tool_name = make_with.split(":", 2)
                server = next((s for s in allowlist if isinstance(s, dict) and s.get("id") == server_id), None)
                tools = server.get("tools", []) if server else []
                tools = tools if isinstance(tools, list) else []
                tool = next((t for t in tools if isinstance(t, dict) and t.get("name") == tool_name), None)
                if (
                    not tool
                    or tool.get("action_type") != action
                    or tool.get("risk_tier") != "T3"
                    or tool.get("side_effect") is not True
                ):
                    raise MakerConfigError("Maker choices are not configured correctly.")
    return copy.deepcopy(raw)


def _load_config() -> dict[str, Any]:
    return load_makers_config()


def _state(views: Any, owner: str, connector: str) -> str | None:
    if views is None:
        return None
    try:
        state, _, _ = views.view(owner, connector)
        return state
    except Exception:
        return None


_PAGE_WORDS = (
    "one two three four five six seven eight nine ten "
    "eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
).split()
_PAGE_COUNT = re.compile(r"(?<![a-z0-9])(\d+|" + "|".join(_PAGE_WORDS) + r")[ -]+pages?\b")
_WORDS = dict(zip(_PAGE_WORDS, range(1, 21)))


def _large_reason(deliverable: dict[str, Any], brief: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    rule = cfg["large_site"]
    chunks = [brief.get(field, "") for field in ("goal", "audience")]
    chunks.extend([deliverable.get("title", ""), *brief.get("constraints", [])])
    for key, fields in (
        ("assumptions", ("question", "assumed")),
        ("applied_preferences", ("value",)),
        ("sources", ("label",)),
    ):
        chunks.extend(row.get(field, "") for row in brief.get(key, []) for field in fields)
    text = " ".join(" ".join(str(v).lower().split()) for v in chunks)
    for need in rule["needs"]:
        pattern = r"(?<![a-z0-9])" + re.escape(need).replace(r"\ ", r"[ -]") + r"(?![a-z0-9])"
        if re.search(pattern, text):
            return f"This brief needs {need}, which a small native website cannot provide."
    pages = []
    for match in _PAGE_COUNT.finditer(text):
        raw = match.group(1)
        pages.append(int(raw) if raw.isdigit() else _WORDS[raw])
    too_many = next((count for count in pages if count > rule["max_native_pages"]), None)
    return f"This brief asks for {too_many} pages." if too_many else None


def _options_for(
    fmt: str, deliverable: dict[str, Any], brief: dict[str, Any], owner: str, cfg: dict[str, Any], views: Any
) -> tuple[list[dict[str, Any]], str]:
    options: list[dict[str, Any]] = [
        {"make_with": "native", "label": "Tilo", "status": "ready", "suggested": False, "note": None}
    ]
    for partner in cfg["formats"][fmt]["partners"]:
        make_with = partner["make_with"]
        if make_with.startswith("connector:"):
            connector_id = make_with.removeprefix("connector:")
            declared, canva = _declarations(cfg, connector_id)
            record = canva or declared
            if record is None:
                raise MakerConfigError("Maker choices are not configured correctly.")
            if canva and not declared:
                status, note = "needs_setup", "Needs the workspace owner's Canva app."
            elif record.get("auth") == "none" or _state(views, owner, connector_id) == "connected":
                status, note = "ready", None
            else:
                status, note = "needs_setup", f"Connect {record['name']} before choosing it."
            label = record["name"]
        else:
            _, server_id, tool_name = make_with.split(":", 2)
            server = next(s for s in cfg["_mcp"]["servers"] if s["id"] == server_id)
            label = server["name"]
            status = "ready" if _state(views, owner, server_id) == "connected" else "needs_setup"
            note = None if status == "ready" else f"Connect {label} before choosing it."
        options.append({"make_with": make_with, "label": label, "status": status, "suggested": False, "note": note})

    reason = _large_reason(deliverable, brief, cfg) if fmt == "website" else None
    if reason:
        for option in options[1:]:
            if option["status"] == "ready":
                option["suggested"], option["note"] = True, reason
                break
    selected: str | None = next((o["make_with"] for o in options[1:] if o["suggested"]), None)
    if not cfg["preselect_suggested"] or selected is None:
        selected = "native"
    return options, selected


def _declarations(cfg: dict[str, Any], connector_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    return cfg.get("_connectors", {}).get(connector_id), cfg.get("_canva", {}).get(connector_id)


def make_choices(brief: dict[str, Any], owner: str, *, views: Any = None) -> list[dict[str, Any]]:
    cfg = _load_config()
    connectors = _read_yaml(_CONFIG_DIR / "connectors.yaml") or []
    canva = _read_yaml(_CONFIG_DIR / "canva.yaml") or []
    cfg["_mcp"] = _read_yaml(_CONFIG_DIR / "mcp.yaml") or {"servers": []}
    cfg["_connectors"] = {row["id"]: row for row in connectors}
    cfg["_canva"] = {row["id"]: row for row in canva}
    if views is None:
        try:
            from tilo_api import deps  # noqa: PLC0415

            views = deps.get_connection_views()
        except Exception:
            views = None
    choices = []
    for index, deliverable in enumerate(brief.get("deliverables", [])):
        if index > 9:
            break
        fmt = deliverable.get("format")
        if fmt not in cfg["formats"]:
            continue
        options, selected = _options_for(fmt, deliverable, brief, owner, cfg, views)
        typed_options = [PlanMakeOption.model_validate(option) for option in options]
        choices.append(
            PlanMakeChoice(deliverable=index, options=typed_options, selected=selected).model_dump(mode="json")
        )
    return choices


def resolve_picks(
    choices: list[dict[str, Any]], requested: list[dict[str, Any]], brief: dict[str, Any]
) -> list[dict[str, Any]]:
    supplied = {item["deliverable"]: item["make_with"] for item in requested}
    if len(supplied) != len(requested):
        raise MakerSelectionError("Choose one maker per deliverable.")
    choice_indexes = {choice["deliverable"] for choice in choices}
    if not supplied.keys() <= choice_indexes:
        raise MakerSelectionError("That maker was not offered for this deliverable.")
    picks = []
    deliverables = brief.get("deliverables", [])
    for choice in choices:
        index = choice["deliverable"]
        selected = supplied.get(index, choice["selected"])
        option = next((o for o in choice["options"] if o["make_with"] == selected), None)
        if option is None:
            raise MakerSelectionError("That maker was not offered for this deliverable.")
        if option["status"] != "ready":
            raise MakerSelectionError(f"{option['label']} needs setup before you can choose it.")
        picks.append(
            {
                "deliverable": index,
                "title": deliverables[index]["title"],
                "format": deliverables[index]["format"],
                "make_with": selected,
                "label": option["label"],
                "suggested": next((o["make_with"] for o in choice["options"] if o["suggested"]), None),
            }
        )
    return picks
