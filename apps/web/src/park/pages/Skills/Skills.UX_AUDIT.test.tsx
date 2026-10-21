// @vitest-environment happy-dom
// UX-AUDIT: a disabled "Run skill" says why next to it; the tool-access levels say they are not saved.
import { afterEach, expect, it, vi } from "vitest";
import { stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { mountSkills } from "../../../../test-support/park/skillsHarness";
import { skillFromRow } from "../../api/live/skillsFromApi";
import { SkillDrawer } from "./SkillDrawer";

afterEach(cleanup);

const skill = (paused: boolean) =>
  skillFromRow({
    id: "tsk_plan",
    name: "Plan a project",
    scope: { kind: "just_me", team: null },
    status: "learning",
    paused,
    plan: [{ text: "Draft the plan", tool: "writer", action: "compose", ask_first: false }],
    question: null,
    inputs: [{ name: "brief", label: "Project brief", kind: "text", required: true }],
  });

const drawer = (paused: boolean, onRun?: () => void) =>
  mount(
    <SkillDrawer
      app={stubApp("skills")}
      skill={skill(paused)}
      paused={false}
      currency="USD"
      onPause={null}
      pauseOff=""
      onTeach={() => {}}
      onClose={() => {}}
      {...(onRun ? { onRun } : {})}
    />,
  );

const runButton = (root: HTMLElement) =>
  [...root.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Run skill");

const reason = (root: HTMLElement) => {
  const id = runButton(root)?.getAttribute("aria-describedby");
  return id ? (root.querySelector(`[id="${id}"]`)?.textContent ?? null) : null;
};

it("UX_AUDIT_skill_cards_say_open_and_tool_levels_say_they_are_not_saved", async () => {
  const { el } = await mountSkills();
  const chips = [...el.querySelectorAll(".park-skills-card2__run-btn")].map((c) => c.textContent);
  expect(chips.length).toBeGreaterThan(0);
  expect(new Set(chips)).toEqual(new Set(["Open"]));
  expect(el.querySelector(".park-skills-access-sub")?.textContent).toContain("it is not saved yet");
});

it("UX_AUDIT_run_skill_without_a_runner_says_it_is_not_connected", () => {
  const m = drawer(false);
  expect(runButton(m.container)?.disabled).toBe(true);
  expect(reason(m.container)).toBe("Running a skill is not connected in this session.");
});

it("UX_AUDIT_run_skill_names_the_missing_field_or_the_pause", () => {
  expect(reason(drawer(false, vi.fn()).container)).toBe("Fill in the required fields first.");
  cleanup();
  expect(reason(drawer(true, vi.fn()).container)).toBe(
    "This skill is paused. Resume it to run it.",
  );
});
