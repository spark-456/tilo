// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
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

it("FR_SKL_04_catalog_shows_library_inputs_and_connectors_without_inventing_steps_or_cost", () => {
  const skill = {
    ...skillFromRow({
      id: "tsk_a",
      name: "A",
      scope: { kind: "just_me" as const, team: null },
      status: "learning" as const,
      paused: false,
      plan: [],
      question: null,
    }),
    id: "exec_summary",
    name: "Executive summary",
    builtin: true,
    description: "Summarise a document",
    catalog: {
      inputs: [{ name: "document", label: "Document", kind: "file" as const, required: true }],
      tools: ["google_drive"],
    },
  };
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
  expect(body).toContain("Summarise a document");
  expect(body).toContain("Document (required)");
  expect(body).toContain("google_drive");
  expect(body).not.toContain("Steps it follows");
  expect(body).not.toContain("Estimated cost");
});

it("P0_SKILLS_run_collects_required_inputs_and_submits_the_selected_skill", async () => {
  const skill = skillFromRow({
    id: "tsk_plan",
    name: "Plan a project",
    scope: { kind: "just_me", team: null },
    status: "learning",
    paused: false,
    plan: [{ text: "Draft the plan", tool: "writer", action: "compose", ask_first: false }],
    question: null,
    inputs: [{ name: "brief", label: "Project brief", kind: "text", required: true }],
  });
  const run = vi.fn();
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
      onRun={run}
    />,
  );
  const button = [...m.container.querySelectorAll("button")].find(
    (b) => b.textContent === "Run it",
  );
  expect(button?.disabled).toBe(true);
  const field = m.container.querySelector<HTMLInputElement>('input[aria-label="Project brief"]');
  expect(field).not.toBeNull();
  act(() => {
    if (field) {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(field, "Build a launch checklist");
      field.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  expect(button?.disabled).toBe(false);
  await act(async () => {
    button?.click();
    await Promise.resolve();
  });
  expect(run).toHaveBeenCalledWith(skill, { brief: "Build a launch checklist" }, []);
});

it("P0_SKILLS_browser_tool_step_is_labeled_and_cannot_run", () => {
  const skill = skillFromRow({
    id: "tsk_site",
    name: "Check a supplier",
    scope: { kind: "just_me", team: null },
    status: "learning",
    paused: false,
    plan: [{ text: "Research suppliers", tool: "browser", action: "navigate", ask_first: false }],
    question: null,
  });
  const run = vi.fn();
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
      onRun={run}
    />,
  );
  expect(m.container.textContent).toContain("Needs browser control (coming)");
  const button = [...m.container.querySelectorAll("button")].find(
    (b) => b.textContent === "Run it",
  );
  expect(button?.disabled).toBe(true);
  act(() => button?.click());
  expect(run).not.toHaveBeenCalled();
});

it("P0_SKILLS_owner_can_edit_and_delete_from_the_drawer", async () => {
  const skill = skillFromRow({
    id: "tsk_edit",
    name: "Old name",
    scope: { kind: "just_me", team: null },
    status: "learning",
    paused: false,
    plan: [{ text: "Draft old", tool: "writer", action: "compose", ask_first: false }],
    question: null,
  });
  const edit = vi.fn(async () => undefined);
  const remove = vi.fn(async () => undefined);
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
      onEdit={edit}
      onDelete={remove}
    />,
  );
  const press = (text: string) =>
    [...m.container.querySelectorAll("button")].find((b) => b.textContent === text)?.click();
  act(() => press("Edit skill"));
  const field = m.container.querySelector<HTMLInputElement>('input[aria-label="Skill name"]');
  expect(field).not.toBeNull();
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(field, "New name");
    field?.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    press("Save changes");
    await Promise.resolve();
  });
  expect(edit).toHaveBeenCalledWith(skill, "New name", ["Draft old"]);
  act(() => press("Delete skill"));
  await act(async () => {
    press("Confirm delete");
    await Promise.resolve();
  });
  expect(remove).toHaveBeenCalledWith(skill);
});
