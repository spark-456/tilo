// @vitest-environment happy-dom
// UI-STUDIO-1: Studio is the default theme of the Park root; the account menu's Light, Dark and System switch sets the
// `time` preference (System follows prefers-color-scheme, live), it persists across a reload, and the nav still
// reaches every destination it had. The shared Studio pieces render in the light and the dark theme.
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../../test-support/park/componentsHarness";
import { Button } from "../components";
import { EmptyState, ErrorState, Skeleton } from "./States";
import { ThemeSwitch, appearanceOf } from "./ThemeSwitch";

vi.mock("../app/pages", () => ({ PAGES: {} }));
vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

import { ParkApp } from "../app/ParkApp";
import { timeFor } from "../app/store";

type Listener = (e: { matches: boolean }) => void;
let deviceDark = false;
const schemeListeners = new Set<Listener>();

beforeEach(() => {
  deviceDark = false;
  schemeListeners.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => {
      const scheme = /prefers-color-scheme: dark/.test(query);
      return {
        get matches() {
          return scheme ? deviceDark : false;
        },
        media: query,
        onchange: null,
        addEventListener: (_t: string, l: Listener) => {
          if (scheme) schemeListeners.add(l);
        },
        removeEventListener: (_t: string, l: Listener) => {
          schemeListeners.delete(l);
        },
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      };
    },
  });
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};

const root = () => q<HTMLElement>(document.body, "[data-park]");
const button = (name: string) => {
  const found = qa<HTMLButtonElement>(document.body, "button").find(
    (b) => b.textContent?.trim() === name,
  );
  expect(found, name).toBeDefined();
  return found as HTMLButtonElement;
};

async function visit(path = "/park/ledger") {
  window.history.pushState({}, "", path);
  const m = mount(<ParkApp />);
  await settle();
  return m;
}

/** A reload: the app goes away, the stored preferences stay (the harness cleanup would clear them). */
function reload(m: { unmount(): void }) {
  m.unmount();
  document.body.innerHTML = "";
}

async function openAccount() {
  await act(async () => click(q(document.body, 'button[aria-label="Account menu"]')));
  await settle();
}

async function choose(name: string) {
  await act(async () => click(button(name)));
  await settle();
}

describe("UI-STUDIO-1 theme: Studio light, dark and system", () => {
  it("STUDIO_1 Studio is the default theme and light is the default appearance", async () => {
    await visit();
    expect(root().dataset).toMatchObject({ theme: "studio", time: "day" });
  });

  it("STUDIO_1 the account menu switch sets light and dark, presses the chosen one and persists it", async () => {
    const first = await visit();
    await openAccount();
    const group = q(document.body, "fieldset.park-theme");
    expect(q(group, "legend").textContent).toBe("Theme");
    expect(qa(group, "button").map((b) => b.textContent)).toEqual(["Light", "Dark", "System"]);
    expect(button("Light").getAttribute("aria-pressed")).toBe("true");
    await choose("Dark");
    expect(root().dataset.time).toBe("night");
    expect(button("Dark").getAttribute("aria-pressed")).toBe("true");
    expect(window.localStorage.getItem("tilo.time")).toBe("night");
    // a reload keeps it
    reload(first);
    await visit();
    expect(root().dataset).toMatchObject({ theme: "studio", time: "night" });
    await openAccount();
    await choose("Light");
    expect(root().dataset.time).toBe("day");
    expect(window.localStorage.getItem("tilo.time")).toBe("day");
  });

  it("STUDIO_1 system follows the device's colour scheme, also when it changes, and persists", async () => {
    deviceDark = true;
    const first = await visit();
    await openAccount();
    await choose("System");
    expect(window.localStorage.getItem("tilo.time")).toBe("system");
    expect(root().dataset.time).toBe("night");
    expect(button("System").getAttribute("aria-pressed")).toBe("true");
    deviceDark = false;
    await act(async () => {
      for (const l of [...schemeListeners]) l({ matches: false });
    });
    expect(root().dataset.time).toBe("day");
    // a reload in a light device keeps System, and light
    reload(first);
    await visit();
    expect(root().dataset.time).toBe("day");
    await openAccount();
    expect(button("System").getAttribute("aria-pressed")).toBe("true");
  });

  it("STUDIO_1 the theme switch does not close the menu, a menu row still does", async () => {
    await visit();
    await openAccount();
    await choose("Dark");
    expect(
      q(document.body, 'button[aria-label="Account menu"]').getAttribute("aria-expanded"),
    ).toBe("true");
  });

  it("STUDIO_1 timeFor and appearanceOf map the stored value", () => {
    expect(timeFor("night", false)).toBe("night");
    expect(timeFor("day", true)).toBe("day");
    expect(timeFor("system", true)).toBe("night");
    expect(timeFor("system", false)).toBe("day");
    expect(timeFor(undefined, true)).toBe("day");
    expect(appearanceOf("system")).toBe("system");
    expect(appearanceOf("night")).toBe("night");
    expect(appearanceOf("nope")).toBe("day");
  });
});

describe("UI-STUDIO-1 nav: every destination is still reached", () => {
  it("STUDIO_1 the nav renders all six tabs and the account menu's pages", async () => {
    await visit("/park/worlds");
    const nav = q(document.body, 'header nav[aria-label="Main"]');
    expect(
      qa<HTMLAnchorElement>(nav, "a").map((a) => [
        (a.textContent ?? "").replace(/\d+$/, ""),
        a.getAttribute("href"),
      ]),
    ).toEqual([
      ["Home", "/"],
      ["Chat", "/chat"],
      ["Worlds", "/worlds"],
      ["Skills", "/skills"],
      ["Needs you", "/needs"], // STUDIO-4
      ["Ledger", "/ledger"],
      ["Agenda", "/agenda"],
      ["Team", "/team"],
    ]);
    expect(q(nav, '[aria-current="page"]').textContent).toMatch(/^Worlds/);
    for (const label of ["Notifications", "Account menu", "Your context"]) {
      expect(q(document.body, `button[aria-label="${label}"]`)).toBeTruthy();
    }
    await openAccount();
    const rows = qa(document.body, '[role="menuitem"]').map((r) => r.textContent ?? "");
    for (const page of [
      "Profile and settings",
      "Connectors",
      "More",
      "Team and roles",
      "Library",
    ]) {
      expect(
        rows.some((r) => r.startsWith(page)),
        page,
      ).toBe(true);
    }
  });
});

describe("UI-STUDIO-1 components render in both themes", () => {
  for (const time of ["day", "night"] as const) {
    it(`STUDIO_1 the shared Studio pieces render under the ${time} Studio root`, () => {
      const m = mount(
        <div data-park="" data-theme="studio" data-time={time}>
          <Button variant="primary">Start</Button>
          <Button variant="secondary">Change</Button>
          <ThemeSwitch value={time} onChange={() => undefined} />
          <EmptyState
            title="Nothing needs you"
            line="Your helpers are getting on with it."
            action={<Button variant="secondary">Back to Home</Button>}
          />
          <Skeleton label="Loading worlds" card />
          <ErrorState
            title="Web search is not connected yet"
            detail="Try again, or continue without it."
            action={<Button variant="secondary">Try again</Button>}
          />
        </div>,
      );
      const c = m.container;
      expect(qa(c, ".park-btn--primary")).toHaveLength(1); // UX-1
      expect(q(c, '[role="status"]').getAttribute("aria-label")).toBe("Loading worlds");
      expect(qa(c, ".park-skeleton [aria-hidden='true']").length).toBeGreaterThan(1);
      expect(c.textContent).not.toMatch(/\d+%/); // a skeleton claims no progress
      expect(q(c, '[role="alert"] h2').textContent).toBe("Web search is not connected yet");
      expect(q(c, ".park-state--empty h2").textContent).toBe("Nothing needs you");
      expect(qa(c, ".park-state--empty button")).toHaveLength(1); // one next step
      const pressed = qa(c, ".park-theme button").filter(
        (b) => b.getAttribute("aria-pressed") === "true",
      );
      expect(pressed.map((b) => b.textContent)).toEqual([time === "day" ? "Light" : "Dark"]);
    });
  }
});
