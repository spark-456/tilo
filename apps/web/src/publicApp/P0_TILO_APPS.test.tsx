// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../test-support/park/componentsHarness";
import { PublicAppViewer } from "./PublicAppViewer";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("P0-TILO-APPS serves a signed-out sandbox viewer without Tilo navigation", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue({
        ok: true,
        json: async () => ({ title: "Survey", html: "<form><input name='a'></form>" }),
      }),
  );
  const view = mount(<PublicAppViewer handle="ada" slug="survey" />);
  await act(async () => Promise.resolve());
  const frame = view.container.querySelector("iframe");
  expect(frame?.getAttribute("sandbox")).toBe("allow-scripts allow-forms");
  expect(frame?.srcdoc).toContain("tilo-form-submit");
  expect(view.container.querySelector("nav")).toBeNull();
  expect(view.container.textContent).not.toContain("Thank you");
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/public/apps/ada/survey"),
    expect.anything(),
  );
});
