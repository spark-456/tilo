// @vitest-environment happy-dom
// WEB-8a acceptance: the shared-file seams the Skills page needs, pinned so the builder adds exactly these.
//  1. park/app/context.tsx exports `useSchedule(): Schedule`, the `schedule` the ParkProvider was given
//     (realSchedule when none), so a page's timer is the injected one and a test never waits (plan section 10:
//     "no timers in page code"; the 900 ms of recording and of the practice run go through this). WEB-4 (Home)
//     adds the same hook; whichever lands first, the other keeps it as is.
//  2. park/app/pages.ts: `skills` is the Skills page, not the Placeholder (one line, as plan section 10 allows),
//     and test-support/park/realPages.ts lists "skills" (the WEB-3a tests that assume a Placeholder skip it).
//  3. The Api's `saveSkill(skill: Skill)` already exists (park/api/index.ts): the page calls it, nothing new.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { type ReactNode, Suspense, act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import { PLACEHOLDER_PAGES, REAL_PAGES } from "../../../../test-support/park/realPages";
import { settle } from "../../../../test-support/park/skillsHarness";
import { ParkProvider, useSchedule } from "../../app/context";
import { PAGES } from "../../app/pages";
import type { Schedule } from "../../app/store";

afterEach(cleanup);

const provider = (children: ReactNode, schedule?: Schedule) => (
  <ParkProvider
    api={fakeApi()}
    navigate={vi.fn()}
    {...(schedule ? { schedule } : {})}
    viewport={{ vw: 1440, vh: 900 }}
  >
    {children}
  </ParkProvider>
);

describe("WEB_8a_skills_schedule: useSchedule", () => {
  it("WEB_8a_skills_schedule_useSchedule_returns_the_schedule_the_provider_was_given", () => {
    const given: Schedule = () => () => undefined;
    let seen: Schedule | undefined;
    function Probe() {
      seen = useSchedule();
      return null;
    }
    mount(provider(<Probe />, given));
    expect(seen).toBe(given);
  });

  it("WEB_8a_skills_schedule_without_a_schedule_prop_it_is_a_function_that_returns_a_cancel", () => {
    let seen: Schedule | undefined;
    function Probe() {
      seen = useSchedule();
      return null;
    }
    mount(provider(<Probe />));
    expect(typeof seen).toBe("function");
    const cancel = seen?.(() => undefined, 60_000);
    expect(typeof cancel).toBe("function");
    cancel?.(); // nothing real keeps running after the test
  });

  it("WEB_8a_skills_schedule_outside_a_provider_it_throws_like_the_other_hooks", () => {
    let error: unknown;
    function Probe() {
      try {
        useSchedule();
      } catch (caught) {
        error = caught;
      }
      return null;
    }
    mount(<Probe />);
    expect(() => {
      throw error;
    }).toThrow(/ParkProvider is missing/);
  });
});

describe("WEB_8a_skills_schedule: the page registry", () => {
  it("WEB_8a_skills_schedule_pages_skills_renders_the_Skills_page_not_the_placeholder", async () => {
    const Page = PAGES.skills;
    const m = mount(
      provider(
        <Suspense fallback={null}>
          <Page app={stubApp("skills")} />
        </Suspense>,
      ),
    );
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    await settle();
    expect(q(m.container, "h1").textContent).toBe("Skills");
    expect(q(m.container, 'section[aria-label="Teach a skill"]')).toBeTruthy();
    expect(m.container.textContent).not.toContain("Not built yet");
    expect(qa(m.container, '[data-testid="park-page-skills"]')).toHaveLength(1);
  });

  it("WEB_8a_skills_schedule_pages_ts_has_one_skills_line_for_the_page_and_keeps_the_other_eight", () => {
    const src = readFileSync(join(__dirname, "..", "..", "app", "pages.ts"), "utf8");
    const lines = src.split(/\r?\n/);
    const mine = lines.filter((l) => /^\s*skills\s*:/.test(l));
    expect(mine).toHaveLength(1);
    expect(mine[0]).toMatch(/pages\/Skills\/SkillsPage/);
    expect(mine[0]).not.toMatch(/Placeholder/);
    for (const id of ["worlds", "world", "ledger", "agenda", "team", "profile", "connectors"]) {
      expect(lines.filter((l) => new RegExp(`^\\s*${id}\\s*:`).test(l))).toHaveLength(1);
    }
  });

  it("WEB_8a_skills_schedule_REAL_PAGES_lists_skills_so_the_placeholder_checks_skip_it", () => {
    expect(REAL_PAGES).toContain("skills");
    expect(PLACEHOLDER_PAGES).not.toContain("skills");
  });
});
