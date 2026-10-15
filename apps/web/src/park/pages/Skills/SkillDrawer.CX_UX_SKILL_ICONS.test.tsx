// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import type { Skill } from "../../api/types";
import { takeDraft } from "../../chat/handoff";
import { SkillDrawer } from "./SkillDrawer";

afterEach(() => {
  cleanup();
  takeDraft();
});

const skill = (over: Partial<Skill> = {}): Skill => ({
  id: "web-research",
  name: "Web research",
  description: "Research public sources",
  builtin: true,
  tools: [["browser", 1]],
  steps: [],
  used: [],
  team: "",
  owner: "Tilo",
  role: "",
  runs: null,
  rate: null,
  last: "",
  improved: "",
  status: "live",
  st: "draft",
  from: "1.0.0",
  ...over,
});

describe("CX_UX_SKILL_ICONS detail", () => {
  it("CX_UX_SKILL_ICONS shows served context and prefills Home without a run", () => {
    const app = stubApp("skills");
    const m = mount(
      <SkillDrawer
        app={app}
        skill={skill()}
        paused={false}
        currency="USD"
        onPause={null}
        pauseOff=""
        onTeach={() => {}}
        onClose={() => {}}
      />,
    );
    expect(m.container.textContent).toContain("How Tilo uses this skill");
    expect(m.container.textContent).toContain("Research public sources");
    expect(m.container.textContent).toContain("browser");
    const tryButton = [...m.container.querySelectorAll("button")].find(
      (b) => b.textContent === "Try it",
    );
    if (!tryButton) throw new Error("Try it button missing");
    click(tryButton);
    expect(takeDraft()).toContain("Web research");
    expect(app.go).toHaveBeenCalledWith("home");
  });

  it("CX_UX_SKILL_ICONS omits absent detail lines", () => {
    const m = mount(
      <SkillDrawer
        app={stubApp("skills")}
        skill={skill({ description: "", tools: [] })}
        paused={false}
        currency="USD"
        onPause={null}
        pauseOff=""
        onTeach={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(m.container.textContent).toContain("How Tilo uses this skill");
    expect(m.container.textContent).not.toContain("When Tilo picks it");
    expect(m.container.textContent).not.toContain("What it needs");
    expect(m.container.textContent).not.toContain("What it produces");
  });
});
