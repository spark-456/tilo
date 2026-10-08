// @vitest-environment happy-dom
// FR-UX-12 / issue #588: the 'still' motion preference (Profile > Appearance) must also stop the loader's ring and
// the boot splash's bar; before, only the page swap and the fades were instant and these two kept spinning.
// The shell root carries the chosen preference as `data-motion`; park.shell.css stops both there.
import fs from "node:fs";
import path from "node:path";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";
import { cleanup, mount, q } from "../../../test-support/park/componentsHarness";
import { ParkApp } from "../app/ParkApp";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/motionEngine")).parkMock(),
);

const css = fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8");
const stillRules = parseRules(css).rules.filter((r) => /\[data-motion="still"\]/.test(r.selector));
const stops = (cls: string): boolean =>
  stillRules.some(
    (r) => r.selector.includes(cls) && /^none\b/.test(r.decls.get("animation") ?? ""),
  );

describe("FR-UX-12 still css: the loader ring and the boot bar stop under 'still'", () => {
  it("FR-UX-12 still css: .park-shell__ring has animation none under [data-motion=still]", () => {
    expect(stops(".park-shell__ring")).toBe(true);
  });

  it("FR-UX-12 still css: .park-shell__bootfill has animation none under [data-motion=still]", () => {
    expect(stops(".park-shell__bootfill")).toBe(true);
  });

  it("FR-UX-12 still css: the rules are scoped to the Park root, so nothing outside it changes", () => {
    for (const r of stillRules) expect(r.selector).toMatch(/^\[data-park\]\[data-motion="still"\]/);
  });
});

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
  await act(async () => undefined);
};

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

describe("FR-UX-12 still dom: the Park root says which motion the person chose", () => {
  it.each(["still", "calm", "lively"])(
    "FR-UX-12 still dom: choosing %s sets data-motion",
    async (pref) => {
      window.localStorage.setItem("tilo.motion", pref);
      window.history.pushState({}, "", "/park");
      const m = mount(<ParkApp />);
      await settle();
      expect(q(m.container, "[data-park]").getAttribute("data-motion")).toBe(pref);
    },
  );
});
