// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../test-support/park/componentsHarness";
import { Root } from "./Root";
import { setDensity } from "./park/shell/density";

const visit = async (path: string) => {
  window.history.pushState({}, "", path);
  const m = mount(<Root />);
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
  return m;
};
const createRoutine = (root: ParentNode) =>
  qa<HTMLAnchorElement>(root, "a").find((a) => a.textContent === "Create a routine");
afterEach(() => {
  cleanup();
  setDensity("friendly");
  window.localStorage.removeItem("tilo.density");
  window.history.pushState({}, "", "/");
});
it("UI-10 W7 Settings uses the Park navigation and one main without the flow replay pill", async () => {
  const m = await visit("/settings");
  await vi.waitFor(async () => {
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(m.container.querySelector('main [data-testid="park-page-settings"]')).not.toBeNull();
  });
  expect(qa(m.container, "[data-park]")).toHaveLength(1);
  expect(qa(m.container, "main")).toHaveLength(1);
  expect(m.container.querySelector('main [data-testid="park-page-settings"]')).not.toBeNull();
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
  expect(m.container.textContent).toContain("No routines are recorded in this sample.");
  expect(createRoutine(m.container)?.getAttribute("href")).toBe("/");
  expect(m.container.querySelector('input[name="density"]')).not.toBeNull();
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
it("UI-10 W8b Settings Appearance changes the shell and persists to Profile", async () => {
  const m = await visit("/settings");
  const button = (label: string) => {
    const el = qa<HTMLButtonElement>(m.container, "button").find((b) =>
      b.textContent?.includes(label),
    );
    expect(el, label).toBeDefined();
    return el as HTMLButtonElement;
  };
  click(button("Dark")); // UI-STUDIO-1: the night card is Dark
  click(button("Still"));
  expect(q(m.container, "[data-park]").getAttribute("data-time")).toBe("night");
  expect(q(m.container, "[data-park]").getAttribute("data-motion")).toBe("still");
  const professional = q<HTMLInputElement>(m.container, 'input[value="professional"]');
  click(professional);
  expect(professional.checked).toBe(true);
  expect(m.container.textContent).toContain("No routines are recorded in this sample.");
  expect(createRoutine(m.container)?.getAttribute("href")).toBe("/");
  await act(async () => {
    window.history.pushState({}, "", "/profile?tab=appearance");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await vi.dynamicImportSettled();
  });
  await vi.waitFor(() => expect(button("Dark").getAttribute("aria-pressed")).toBe("true"));
  expect(button("Still").getAttribute("aria-pressed")).toBe("true");
});
