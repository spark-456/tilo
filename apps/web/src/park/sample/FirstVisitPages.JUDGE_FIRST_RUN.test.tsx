// @vitest-environment happy-dom
// JUDGE-FIRST-RUN F1 and F4: on a first visit (no worlds yet) Skills, Team and Agenda keep their real page, with the
// built-in skills and "Teach a skill" on Skills, and the labelled recorded examples come below it, never instead of it.
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../test-support/park/componentsHarness";
import { liveApi, mountShell, settle } from "../../../test-support/park/shellHarness";
import { skills as fixtureSkills } from "../api/fixtures";
import { useApp } from "../app/context";
import { AgendaPage } from "../pages/Agenda/AgendaPage";
import { SkillsPage } from "../pages/Skills/SkillsPage";
import { TeamPage } from "../pages/Team/TeamPage";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);
afterEach(cleanup);

function Pages() {
  const app = useApp();
  return (
    <>
      <SkillsPage app={app} />
      <TeamPage app={app} />
      <AgendaPage app={app} />
    </>
  );
}

it("JUDGE_FIRST_RUN_F4_skills_lists_the_built_in_skills_and_teach_above_the_labelled_examples", async () => {
  const api = liveApi();
  api.getWorlds = vi.fn(async () => ({ data: [], source: "live" as const }));
  const builtin = {
    ...(fixtureSkills[0] as (typeof fixtureSkills)[number]),
    id: "web-research",
    name: "Web research",
    builtin: true,
    st: "trusted" as const,
  };
  api.getSkills = vi.fn(async () => ({ data: [builtin], source: "live" as const }));
  const { m } = mountShell(<Pages />, { api });
  await settle();
  const root = m.container;
  const skillsPage = root.querySelector('[data-testid="park-page-skills"]');
  expect(skillsPage).not.toBeNull();
  expect(skillsPage?.textContent).toContain("Web research");
  expect(skillsPage?.textContent).toContain("Teach a skill");
  // the examples are present once each, labelled, and come after the real page in the document
  for (const page of ["skills", "team", "agenda"]) {
    const examples = root.querySelectorAll(`[data-first-run-panels="${page}"]`);
    expect(examples).toHaveLength(1);
    expect(examples[0]?.querySelector("h2")?.textContent).toBe("Recorded examples");
    expect(examples[0]?.querySelector("h1")).toBeNull();
  }
  const examples = root.querySelector('[data-first-run-panels="skills"]') as Element;
  expect(
    (skillsPage as Element).compareDocumentPosition(examples) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  // one page heading each: the examples add none
  expect([...root.querySelectorAll("h1")].filter((h) => h.textContent === "Skills")).toHaveLength(
    1,
  );
});
