"""EFF-04: stable identity instructions in every agent system prompt."""

import re

from tilo_providers.prompts import DEFAULT_PROMPTS_ROOT

SYSTEM_PROMPTS = {
    "assistant": ("quick_answer_system.md", "quick_classify_system.md", "route_system.md"),
    "autopilot": ("draft_system.md", "followup_system.md", "triage_system.md"),
    "autorater": ("plan_fit.md",),
    "director": ("approaches_system.md", "brief_system.md", "plan_system.md", "revision_system.md"),
    "eval_judge": ("plan_groundedness.md", "plan_pairwise.md"),
    "generator": ("briefs.md",),
    "lead": ("review.md",),
    "meeting_analyst": ("meeting_analyst.md", "verifier.md"),
    "meeting_room": ("reply_system.md",),
    "narrator": ("story.md",),
    "search": ("ground.md",),
    "skill_describe": ("capture_system.md", "version_system.md"),
    "specialist": ("must_ask_system.md", "unit.md"),
    "speech": ("live_read_aloud.md", "transcribe.md"),
    "verifier": ("claim_system.md", "unit.md"),
    "writer": ("build_handoff.md", "unit.md", "unit_pdf.md"),
}


def test_EFF_04_agent_identity_in_every_system_prompt():
    listed = {DEFAULT_PROMPTS_ROOT / folder / name for folder, names in SYSTEM_PROMPTS.items() for name in names}
    assert set(DEFAULT_PROMPTS_ROOT.glob("*/*_system.md")) <= listed
    for folder, names in SYSTEM_PROMPTS.items():
        for name in names:
            path = DEFAULT_PROMPTS_ROOT / folder / name
            text = path.read_text(encoding="utf-8")
            role = folder.replace("_", " ")
            assert text.count(f"Identity: You are Tilo's {role} agent.") == 1, path
            assert "I'm Tilo's " + role + " agent." in text, path
            assert "Tilo runs on Google Cloud models" in text, path
            forbidden = r"\b(?:Gemini|GPT(?:-\w+)?|Claude|OpenAI|Vertex)\b"
            assert not re.search(forbidden, text, re.I), path


def test_EFF_04_identity_paragraph_is_static():
    for folder, names in SYSTEM_PROMPTS.items():
        for name in names:
            text = (DEFAULT_PROMPTS_ROOT / folder / name).read_text(encoding="utf-8")
            paragraph = next(p for p in text.split("\n\n") if p.startswith("Identity: "))
            assert "$" not in paragraph
