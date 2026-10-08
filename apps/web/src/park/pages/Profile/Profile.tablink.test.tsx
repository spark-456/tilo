// @vitest-environment happy-dom
// FR-UX-12 / issue #588 (WEB-MOTION-2 review follow-up): the Profile page follows "?tab=" in the address. After a
// tab was opened by hand, a link to the SAME "?tab=" as the address still says (the notification menu's settings
// link, a link in a page) must open that tab: before, the address had not changed, so nothing told the page.
import { act, createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import { ParkApp } from "../../app/ParkApp";
import { useFollowed } from "../../app/followed";
import { navigatePark, useParkRoute } from "../../app/router";

vi.mock("../../engines/park", async () =>
  (await import("../../../../test-support/park/motionEngine")).parkMock(),
);

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
  await act(async () => undefined);
};
const tabButton = (root: ParentNode, label: string): HTMLButtonElement => {
  const found = qa<HTMLButtonElement>(root, 'nav[aria-label="Settings"] button').find(
    (b) => (b.textContent ?? "").trim() === label,
  );
  if (!found) throw new Error(`no tab named ${label}`);
  return found;
};
const current = (root: ParentNode): string =>
  qa(root, 'nav[aria-label="Settings"] button[aria-current]')
    .map((b) => (b.textContent ?? "").trim())
    .join("|");
const follow = async (to: string): Promise<void> => {
  await act(async () => {
    navigatePark(to);
  });
  await settle();
};

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

describe("FR-UX-12 profile tab link: a link to the address's own ?tab= opens that tab", () => {
  it("FR-UX-12 profile tab link: after a hand-opened tab, the same ?tab= link switches back", async () => {
    window.history.pushState({}, "", "/park/profile?tab=appearance");
    const m = mount(<ParkApp />);
    await settle();
    expect(current(m.container)).toBe("Appearance");
    await act(async () => {
      click(tabButton(m.container, "Security"));
    });
    expect(current(m.container), "the click opened Security").toBe("Security");
    await follow("/park/profile?tab=appearance"); // the address already says appearance
    expect(current(m.container)).toBe("Appearance");
    expect(q(m.container, "main").textContent ?? "").toMatch(/Lamps and glow/);
  });

  it("FR-UX-12 profile tab link: a link to another ?tab= still switches, and the tab can be opened again by hand", async () => {
    window.history.pushState({}, "", "/park/profile?tab=notifications");
    const m = mount(<ParkApp />);
    await settle();
    await follow("/park/profile?tab=security");
    expect(current(m.container)).toBe("Security");
    await act(async () => {
      click(tabButton(m.container, "Plan and billing"));
    });
    expect(current(m.container)).toBe("Plan and billing");
    await follow("/park/profile?tab=security");
    expect(current(m.container)).toBe("Security");
  });
});

describe("FR-UX-12 profile tab link: the follow count is a hint, not a route change", () => {
  function Probe({ seen }: { seen: { count: number; route: unknown }[] }) {
    seen.push({ count: useFollowed(), route: useParkRoute() });
    return createElement("i");
  }

  it("FR-UX-12 follow count: a followed link to the same address changes the count, never the route a page gets", async () => {
    window.history.pushState({}, "", "/park/profile?tab=security");
    const seen: { count: number; route: unknown }[] = [];
    const m = mount(createElement(Probe, { seen }));
    const first = seen.at(-1);
    m.render(createElement(Probe, { seen }));
    expect(seen.at(-1)?.count, "a re-render keeps the count").toBe(first?.count);
    await act(async () => {
      navigatePark("/park/profile?tab=security");
    });
    const after = seen.at(-1);
    expect(after?.count).toBe((first?.count ?? 0) + 1);
    // A page that redirects in an effect keyed on its route would loop if this link changed the route.
    expect(after?.route, "the route is the same object").toBe(first?.route);
  });
});
