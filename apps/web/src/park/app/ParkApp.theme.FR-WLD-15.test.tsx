// @vitest-environment happy-dom
// FR-WLD-15: the Park root carries the chosen theme beside day or night; an unknown id is the default theme.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { ParkApp } from "./ParkApp";

vi.mock("./pages", () => ({ PAGES: {} }));

const root = (container: HTMLElement) => container.querySelector<HTMLElement>("[data-park]");
const visit = async () => {
  window.history.pushState({}, "", "/park/ledger");
  const m = mount(<ParkApp />);
  await act(async () => undefined);
  return m;
};

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

describe("FR-WLD-15 the Park root carries the theme", () => {
  it("FR-WLD-15 Metropolis is the default, day", async () => {
    const m = await visit();
    expect(root(m.container)?.dataset).toMatchObject({ theme: "metropolis", time: "day" });
  });

  it("FR-WLD-15 a stored second theme applies by day and by night", async () => {
    window.localStorage.setItem("tilo.theme", "neutral");
    const day = await visit();
    expect(root(day.container)?.dataset).toMatchObject({ theme: "neutral", time: "day" });
    cleanup();
    window.localStorage.setItem("tilo.time", "night");
    const night = await visit();
    expect(root(night.container)?.dataset).toMatchObject({ theme: "neutral", time: "night" });
  });

  it("FR-WLD-15 an id that no theme file defines falls back to Metropolis", async () => {
    for (const stored of ["nope", 'x"><script>', "NEUTRAL"]) {
      window.localStorage.setItem("tilo.theme", stored);
      const m = await visit();
      expect(root(m.container)?.dataset.theme).toBe("metropolis");
      cleanup();
    }
  });
});
