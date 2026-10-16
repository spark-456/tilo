// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { skillFromRow } from "../../api/live/skillsFromApi";
import { SkillDrawer } from "./SkillDrawer";

afterEach(cleanup);

it("CX_SKILL_UX_1 shows only served step tools inputs hosts and cost", () => {
  const skill = skillFromRow({
    id: "tsk_plan",
    name: "Plan a project",
    scope: { kind: "just_me", team: null },
    status: "learning",
    paused: false,
    version: 2,
    plan: [{ text: "Read the brief", tool: "google_drive", action: "read_file", ask_first: false }],
    question: null,
    inputs: [{ name: "brief", label: "Project brief", kind: "file", required: true }],
    hosts: ["example.com"],
    estimates: { credits_per_run: 9 },
  });
  const m = mount(
    <SkillDrawer
      app={stubApp("skills")}
      skill={skill}
      paused={false}
      currency="USD"
      onPause={null}
      pauseOff=""
      onTeach={() => {}}
      onClose={() => {}}
    />,
  );
  const body = m.container.textContent ?? "";
  expect(body).toContain("Read the brief");
  expect(body).toContain("google_drive · read_file");
  expect(body).toContain("Project brief");
  expect(body).toContain("example.com");
  expect(body).toContain("9 credits per run");
  expect(body).not.toContain("What it produces");
  expect(body).not.toContain("Last run 0");
});
