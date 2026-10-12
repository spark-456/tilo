// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../test-support/park/componentsHarness";
import { PAGE_IDS, PAGE_LABEL, type PageId } from "../park/app/AppCtx";
import FirstRunTourLayer from "./FirstRunTourLayer";
import { PageTourLayer } from "./PageTourLayer";
import { pageTourSteps } from "./pageSteps";
import { requestTour } from "./tourEvents";

const seam = vi.hoisted(() => ({
  firstRun: undefined as boolean | undefined,
  identity: { status: "unavailable" },
}));
vi.mock("./firstRunStub", () => ({ useFirstRun: () => seam.firstRun }));
vi.mock("../park/app/context", () => ({ useApp: () => ({ page: "home", go: vi.fn() }) }));
vi.mock("../auth/session", () => ({
  session: { subscribe: () => () => {}, getState: () => seam.identity },
}));

beforeEach(() => {
  window.localStorage.clear();
  seam.firstRun = undefined;
});
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});
const button = (name: string) => {
  const found = [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === name,
  );
  if (!found) throw new Error(`Missing ${name}`);
  return found;
};
const dialog = () => document.querySelector('[role="dialog"]');

it("FIRST_RUN shared seam selects page tours and suppresses automatic dialogs after a real run", () => {
  seam.firstRun = true;
  const root = mount(
    <div data-park>
      <FirstRunTourLayer />
    </div>,
  );
  expect(dialog()?.textContent).toContain("Take a tour of Home?");
  seam.firstRun = false;
  root.render(
    <div data-park>
      <FirstRunTourLayer />
    </div>,
  );
  expect(dialog()).toBeNull();
});
function view(page: PageId = "home", firstRun = true, userKey = "person-one") {
  return (
    <div data-park data-time="day" data-motion="still">
      <button type="button" aria-label="Account menu">
        Help
      </button>
      <main>
        <div data-testid={`park-page-${page}`}>
          <h1>{PAGE_LABEL[page]}</h1>
          <section>Page content</section>
        </div>
      </main>
      <PageTourLayer page={page} firstRun={firstRun} userKey={userKey} />
    </div>
  );
}

it.each(PAGE_IDS)("FIRST_RUN asks once for %s, scoped per person and page", (page) => {
  const root = mount(view(page));
  expect(dialog()?.textContent).toContain(`Take a tour of ${PAGE_LABEL[page]}?`);
  click(button("Not now"));
  expect(dialog()).toBeNull();
  root.unmount();
  const again = mount(view(page));
  expect(dialog()).toBeNull();
  again.render(view(page, true, "person-two"));
  expect(dialog()?.textContent).toContain(`Take a tour of ${PAGE_LABEL[page]}?`);
});

it("FIRST_RUN a page dismissal does not dismiss a different page", () => {
  const root = mount(view());
  click(button("Not now"));
  root.render(view("worlds"));
  expect(dialog()?.textContent).toContain("Take a tour of Worlds?");
});

it("FIRST_RUN closes immediately on the first real run and never reopens from help", () => {
  const root = mount(view());
  click(button("Take the tour"));
  expect(dialog()).not.toBeNull();
  root.render(view("home", false));
  expect(dialog()).toBeNull();
  act(() => requestTour());
  expect(dialog()).toBeNull();
  cleanup();
  mount(view("home", false, "already-ran"));
  expect(dialog()).toBeNull();
});

it("FIRST_RUN page help replays after Not now, keyboard advances and Escape restores focus", () => {
  mount(view());
  click(button("Not now"));
  const opener = document.querySelector<HTMLButtonElement>('[aria-label="Account menu"]');
  if (!opener) throw new Error("Missing account menu");
  act(() => opener.focus());
  act(() => requestTour());
  expect(dialog()?.textContent).toContain("Home");
  act(() =>
    dialog()?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })),
  );
  expect(dialog()?.textContent).toContain("2 of 3");
  act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(dialog()).toBeNull();
  expect(document.activeElement).toBe(opener);
});

it.each(PAGE_IDS)("FIRST_RUN %s has three steps anchored to existing elements", (page) => {
  mount(view(page));
  const steps = pageTourSteps(page);
  expect(steps).toHaveLength(3);
  for (const step of steps) expect(step.target()?.isConnected).toBe(true);
});

it("FIRST_RUN dialog Tab stays operable and route changes close the old coach mark", () => {
  const root = mount(view());
  const skip = button("Not now");
  act(() => skip.focus());
  act(() =>
    skip.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }),
    ),
  );
  expect(document.activeElement).toBe(button("Take the tour"));
  click(button("Take the tour"));
  root.render(view("connectors"));
  expect(dialog()?.textContent).toContain("Take a tour of Connectors?");
  expect(document.querySelector('[data-onboarding][role="status"]')).toBeNull();
});
