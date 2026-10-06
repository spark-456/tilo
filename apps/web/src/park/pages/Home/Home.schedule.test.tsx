// @vitest-environment happy-dom
// WEB-4 acceptance: the two shared-file seams Home needs, pinned so the builder adds exactly these.
//  1. park/app/context.tsx exports `useSchedule(): Schedule`, the `schedule` the ParkProvider was given
//     (realSchedule when none), so a page's timer is the injected one and a test never waits (plan section 10:
//     "no timers in page code"; the 900 ms of the composer goes through this).
//  2. park/app/pages.ts: `home` is the Home page, not the Placeholder (one line, as plan section 10 allows).
import { Suspense, act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler, stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import { settle } from "../../../../test-support/park/homeHarness";
import { ParkProvider, useSchedule } from "../../app/context";
import { PAGES } from "../../app/pages";
import type { Schedule } from "../../app/store";

afterEach(cleanup);

describe("WEB_4_home_schedule: useSchedule", () => {
  it("WEB_4_home_schedule_useSchedule_returns_the_schedule_the_provider_was_given", () => {
    const sch = fakeScheduler();
    let seen: Schedule | undefined;
    function Probe() {
      seen = useSchedule();
      return null;
    }
    mount(
      <ParkProvider
        api={fakeApi()}
        navigate={vi.fn()}
        schedule={sch.schedule}
        viewport={{ vw: 1440, vh: 900 }}
      >
        <Probe />
      </ParkProvider>,
    );
    expect(seen).toBe(sch.schedule);
  });

  it("WEB_4_home_schedule_without_a_schedule_prop_it_is_a_function_that_returns_a_cancel", () => {
    let seen: Schedule | undefined;
    function Probe() {
      seen = useSchedule();
      return null;
    }
    mount(
      <ParkProvider api={fakeApi()} navigate={vi.fn()} viewport={{ vw: 1440, vh: 900 }}>
        <Probe />
      </ParkProvider>,
    );
    expect(typeof seen).toBe("function");
    const cancel = seen?.(() => undefined, 60_000);
    expect(typeof cancel).toBe("function");
    cancel?.(); // nothing real keeps running after the test
  });

  it("WEB_4_home_schedule_outside_a_provider_it_throws_like_the_other_hooks", () => {
    function Probe() {
      useSchedule();
      return null;
    }
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => mount(<Probe />)).toThrow(/ParkProvider is missing/);
    error.mockRestore();
  });
});

describe("WEB_4_home_schedule: the page registry", () => {
  it("WEB_4_home_schedule_pages_home_renders_the_Home_page_not_the_placeholder", async () => {
    const Page = PAGES.home;
    const m = mount(
      <ParkProvider api={fakeApi()} navigate={vi.fn()} viewport={{ vw: 1440, vh: 900 }}>
        <Suspense fallback={null}>
          <Page app={stubApp("home")} />
        </Suspense>
      </ParkProvider>,
    );
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    await settle();
    expect(q(m.container, "h1").textContent).toBe("Good morning, Alex.");
    expect(q(m.container, 'input[aria-label="Describe your task"]')).toBeTruthy();
    expect(m.container.textContent).not.toContain("Not built yet");
    expect(qa(m.container, '[data-testid="park-page-home"]')).toHaveLength(1);
  });
});
