// @vitest-environment happy-dom
// WEB-QA-14OCT-1 (UI-10): the sample strip is compact (an icon dismiss, never a word that can collide with its
// neighbours), the honesty label stays, and a dismissal is remembered on this device for a guest too.
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount, q } from "../../../test-support/park/componentsHarness";
import { FirstRunBanner } from "./FirstRunBanner";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

it("UI-10 WEB-QA-14OCT banner dismiss does not overlap status: a compact icon control, remembered for a guest too", () => {
  const props = { page: "home", person: null, first: true, floating: true };
  const node = mount(<FirstRunBanner {...props} />);
  const button = q(node.container, "button");
  expect(button.getAttribute("aria-label")).toBe("Dismiss sample banner");
  expect(button.textContent).toBe("×");
  expect(node.container.textContent).toContain("Sample"); // the honesty label stays in the strip
  click(button);
  expect(node.container.textContent).toBe("");
  node.unmount();
  expect(mount(<FirstRunBanner {...props} />).container.textContent).toBe("");
});

it("UI-10 WEB-QA-14OCT banner still dismisses when device storage throws", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const node = mount(<FirstRunBanner page="home" person={null} first />);
  click(q(node.container, "button"));
  expect(node.container.textContent).toBe("");
});
