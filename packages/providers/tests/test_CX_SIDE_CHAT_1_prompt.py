from tilo_providers.prompts import DEFAULT_PROMPTS_ROOT


def test_CX_SIDE_CHAT_1_quick_answer_explains_tilo_capabilities_without_refusing_connected_data():
    text = (DEFAULT_PROMPTS_ROOT / "assistant" / "quick_answer_system.md").read_text(encoding="utf-8")
    assert "worlds" in text and "agents" in text and "skills" in text
    assert "meetings" in text and "connected" in text
    assert "Do this as a world" in text
    assert "You cannot see files, mail, calendars" not in text
