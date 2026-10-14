// @vitest-environment happy-dom
import { StrictMode, act } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../test-support/park/componentsHarness";
import { PAGE_IDS, PAGE_LABEL, type PageId } from "../park/app/AppCtx";
import FirstRunTourLayer from "./FirstRunTourLayer";
import { PageTourLayer } from "./PageTourLayer";
import { pageTourSteps } from "./pageSteps";
import { requestTour } from "./tourEvents";

const seam = vi.hoisted(() => ({
  firstRun: false,
  identity: { status: "unavailable" },
}));
vi.mock("../park/sample/useFirstRun", () => ({ useFirstRun: () => seam.firstRun }));
vi.mock("../park/app/context", () => ({ useApp: () => ({ page: "home", go: vi.fn() }) }));
vi.mock("../auth/session", () => ({
  session: { subscribe: () => () => {}, getState: () => seam.identity },
}));

beforeEach(() => {
  window.history.replaceState(null, "", "/?onboarding=1");
  window.localStorage.clear();
  window.sessionStorage.clear();
  seam.firstRun = false;
});
afterEach(() => {
  window.history.replaceState(null, "", "/");
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
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

it("FIRST_RUN_FR_UX_13_effect_replay_keeps_the_first_invitation_visible", () => {
  mount(<StrictMode>{view()}</StrictMode>);
  expect(dialog()?.textContent).toContain("Take a tour of Home?");
});

it("FIRST_RUN_FR_UX_13_returns_focus_when_the_account_button_is_replaced", () => {
  mount(view());
  click(button("Not now"));
  const original = document.querySelector<HTMLButtonElement>('button[aria-label="Account menu"]');
  if (!original) throw new Error("Missing account menu");
  act(() => original.focus());
  act(() => requestTour());
  const replacement = document.createElement("button");
  replacement.setAttribute("aria-label", "Account menu");
  original.replaceWith(replacement);
  act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(document.activeElement).toBe(replacement);
});

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

it("QA_22_Not_now_on_one_page_silences_every_page_invitation_for_the_session", () => {
  const root = mount(view());
  click(button("Not now"));
  for (const page of ["worlds", "agenda", "team", "connectors", "profile"] as const) {
    root.render(view(page));
    expect(dialog(), page).toBeNull(); // no scrim, no prompt
  }
  act(() => requestTour()); // the person asking for the tour on purpose still gets it
  expect(dialog()).not.toBeNull();
});

it("QA_22_Escape_on_the_invitation_is_a_Not_now", () => {
  const root = mount(view());
  act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  root.render(view("worlds"));
  expect(dialog()).toBeNull();
});

it("QA_22_another_person_in_the_same_browser_is_still_asked", () => {
  const root = mount(view());
  click(button("Not now"));
  root.render(view("worlds", true, "person-two"));
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
