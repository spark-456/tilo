// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount, qa } from "../test-support/park/componentsHarness";
import { Root } from "./Root";

const visit = async (path: string) => {
  window.history.pushState({}, "", path);
  const m = mount(<Root />);
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
  return m;
};
afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});
it("UI-10 W7 Settings uses the Park navigation and one main without the flow replay pill", async () => {
  const m = await visit("/settings");
  await vi.waitFor(async () => {
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(m.container.querySelector('main [data-testid="settings"]')).not.toBeNull();
  });
  expect(qa(m.container, "[data-park]")).toHaveLength(1);
  expect(qa(m.container, "main")).toHaveLength(1);
  expect(m.container.querySelector('main [data-testid="settings"]')).not.toBeNull();
  expect(m.container.querySelector("nav")).not.toBeNull();
  expect(m.container.textContent).not.toContain("Fixture replay");
  expect(document.title).toBe("Settings · Tilo");
});
it("UI-10 W7 More names its browser tab", async () => {
  await visit("/more");
  expect(document.title).toBe("More · Tilo");
});
it("UI-10 W7 unknown routes name the not-found browser tab", async () => {
  await visit("/unknown-page");
  expect(document.title).toBe("Not found · Tilo");
});
