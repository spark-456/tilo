// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../test-support/park/componentsHarness";
import { setDensity } from "../display/density";
import { createFixtureApi } from "../park/api/fixtureApi";
import { ParkProvider, useApp } from "../park/app/context";
import { S_22 } from "./S_22";

function Probe() {
  const app = useApp();
  return (
    <output data-testid="prefs">
      {app.time}/{app.motion}
    </output>
  );
}
afterEach(() => {
  cleanup();
  setDensity("friendly");
});
it("UI-10 W8 Settings offers the same appearance preferences as Profile and updates the owning shell", async () => {
  const api = createFixtureApi();
  api.setPref = vi.fn(api.setPref);
  const m = mount(
    <ParkProvider api={api}>
      <S_22 />
      <Probe />
    </ParkProvider>,
  );
  const button = (name: string) => {
    const b = [...m.container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes(name),
    );
    expect(b, name).toBeDefined();
    return b as HTMLButtonElement;
  };
  expect(m.container.querySelectorAll("[data-park]")).toHaveLength(0); // reuse the shell, no nested full-height Park root
  click(button("Night"));
  expect(m.container.querySelector('[data-testid="prefs"]')?.textContent).toBe("night/calm");
  click(button("Still"));
  expect(m.container.querySelector('[data-testid="prefs"]')?.textContent).toBe("night/still");
  expect(api.setPref).toHaveBeenCalledWith("time", "night");
  expect(api.setPref).toHaveBeenCalledWith("motion", "still");
  const professional = m.container.querySelector<HTMLInputElement>('input[value="professional"]');
  expect(professional).not.toBeNull();
  click(professional as HTMLInputElement);
  expect(professional?.checked).toBe(true);
  expect(document.documentElement.dataset.density).toBe("professional");
  await act(async () => undefined);
});
it("UI-10 W8 Settings explains the routines empty state with a create link and hides unavailable data actions", () => {
  const m = mount(<S_22 />);
  expect(m.container.textContent).toContain("No routines");
  const create = [...m.container.querySelectorAll("a")].find((a) =>
    a.textContent?.includes("Create a routine"),
  );
  expect(create?.getAttribute("href")).toBe("/");
  expect(m.container.textContent).not.toContain("Export my data");
  expect(m.container.textContent).not.toContain("Delete my account and data");
  expect(m.container.textContent).not.toContain("Coming soon");
});
