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
it("UI-10 W7-FIX Settings provides a Park routine empty state and creation link", async () => {
  const m = await visit("/settings");
  expect(m.container.textContent).toContain("No routines yet.");
  expect(m.container.querySelector('a[href="/start"]')?.textContent).toBe("Create a routine");
  expect(m.container.querySelector('[data-testid="density"]')).not.toBeNull();
});
it("UI-10 W7 unknown routes name the not-found browser tab", async () => {
  await visit("/unknown-page");
  expect(document.title).toBe("Not found · Tilo");
});
it("UI-10 W7-FIX2 shares world names and Settings/More titles through route changes", async () => {
  const m = await visit("/world/k1");
  const heading = m.container.querySelector("h1")?.textContent;
  expect(heading).toBeTruthy();
  expect(document.title).toBe(`${heading} · Tilo`);
  for (const [path, title] of [
    ["/settings", "Settings"],
    ["/more", "More"],
    ["/unknown-page", "Not found"],
  ]) {
    await act(async () => {
      window.history.pushState({}, "", path);
      window.dispatchEvent(new PopStateEvent("popstate"));
      await vi.dynamicImportSettled();
    });
    await vi.waitFor(() => expect(document.title).toBe(`${title} · Tilo`));
  }
});
