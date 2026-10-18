from fastapi.testclient import TestClient
from tilo_api import app, chat_routes, deps


def test_P0_CHAT_FUNCTIONS_history_is_private_durable_and_newest_first():
    client = TestClient(app)
    memory = chat_routes.MemoryChatStore()
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal("alice", "owner")
    app.dependency_overrides[chat_routes.get_chat_store] = lambda: memory
    try:
        for chat_id, stamp in (("first", 1), ("second", 2)):
            result = client.put(
                f"/v1/me/chats/{chat_id}",
                json={
                    "title": chat_id,
                    "updated_at": stamp,
                    "turns": [{"id": 1, "question": chat_id, "state": "answered", "text": "ok"}],
                },
            )
            assert result.status_code == 200, result.text
        assert [chat["id"] for chat in client.get("/v1/me/chats").json()["chats"]] == ["second", "first"]
        app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal("bob", "owner")
        assert client.get("/v1/me/chats").json()["chats"] == []
    finally:
        app.dependency_overrides.clear()
