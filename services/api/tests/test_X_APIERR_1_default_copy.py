"""Missing and inaccessible worlds keep the same fixed, private refusal."""

import ast
from pathlib import Path

import pytest
from _api_lib import WORLD, as_principal, make_principal, make_world


@pytest.mark.parametrize("suffix", ["events", "layout"])
@pytest.mark.parametrize("channel", ["web", "mobile_web", "email"])
def test_missing_and_foreign_worlds_have_identical_readable_404s(client, store, suffix, channel):
    as_principal(make_principal(user_id="u_reader", role="owner", world_id=WORLD, channel=channel))
    store.worlds["w_private"] = make_world(owner="u_other")
    before = dict(store.worlds)
    missing = client.get(f"/worlds/w_missing/{suffix}")
    foreign = client.get(f"/worlds/w_private/{suffix}")
    assert missing.status_code == foreign.status_code == 404
    assert missing.content == foreign.content
    assert missing.json() == {"detail": "Tilo could not find that."}
    assert "u_other" not in foreign.text
    assert store.worlds == before


def test_http_refusals_do_not_fall_back_to_stock_copy():
    root = Path(__file__).resolve().parents[1] / "src" / "tilo_api"
    omitted = []
    for path in root.rglob("*.py"):
        # Meeting sources and assistant helpers retain their separate owners.
        if path.name in {"meeting_room.py", "meeting_voice_meter.py"} or "assistant" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "HTTPException":
                if len(node.args) < 2 and not any(keyword.arg == "detail" for keyword in node.keywords):
                    omitted.append(f"{path.name}:{node.lineno}")
    assert omitted == []
