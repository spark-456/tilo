// @vitest-environment happy-dom
import { act, createElement } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { isParkPath, parseParkPath, useParkRoute } from "./router";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("FR_MTG_08 OLDUI5 old routines links reach Park Worlds", () => {
  for (const path of ["/routines", "/routines/", "/park/routines"]) {
    expect(isParkPath(path)).toBe(true);
    expect(parseParkPath(path, "")).toEqual({ page: "worlds", params: {} });
  }
});
it("FR_MTG_08 OLDUI5 routines redirect replaces history without another visit", async () => {
  window.history.replaceState({}, "", "/routines?unused=1");
  const replace = vi.spyOn(window.history, "replaceState");
  const push = vi.spyOn(window.history, "pushState");
  function Route() {
    return useParkRoute()?.page ?? null;
  }
  await act(async () => {
    mount(createElement(Route));
  });
  expect(window.location.pathname).toBe("/worlds");
  expect(replace).toHaveBeenCalledWith({}, "", "/worlds");
  expect(push).not.toHaveBeenCalled();
});
