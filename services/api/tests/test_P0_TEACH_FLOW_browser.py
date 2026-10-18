from tilo_api.runs import browser_control_unavailable
from tilo_api.skills_routes import QuestionIn


class _Registry:
    def get(self, tool: str) -> dict:
        assert tool == "web"
        return {"actions": [{"id": "web_search"}, {"id": "fetch_url"}]}


class _BrowserRegistry(_Registry):
    def get(self, tool: str) -> dict:
        return {"actions": [*super().get(tool)["actions"], {"id": "browse_web"}]}


def test_P0_TEACH_FLOW_open_and_play_skill_fails_honestly_without_browser_action() -> None:
    assert browser_control_unavailable(
        {"goal": "Open YouTube and play the first video"},
        [{"text": "Search for youtube.com", "tool": "web", "action": "web_search"}],
        _Registry(),
    )
    assert not browser_control_unavailable(
        {"goal": "Summarise YouTube search results"},
        [{"text": "Search YouTube", "tool": "web", "action": "web_search"}],
        _Registry(),
    )
    assert browser_control_unavailable(
        {"goal": "Open YouTube and play the first video"}, None, _Registry(), selected_skill=True
    )
    assert not browser_control_unavailable({"goal": "Open YouTube"}, None, _Registry())
    assert not browser_control_unavailable(
        {"goal": "Open YouTube and play the first video"},
        [{"text": "Open YouTube", "tool": "web", "action": "browse_web"}],
        _BrowserRegistry(),
    )


def test_P0_TEACH_FLOW_question_accepts_saved_answer_index() -> None:
    question = QuestionIn.model_validate({"text": "Which file?", "options": ["PDF", "link"], "answer": 0})
    assert question.answer == 0
