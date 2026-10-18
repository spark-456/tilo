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
    vi.fn().mockResolvedValue({
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

it("P0-TILO-APPS ignores other frames and thanks only after public POST succeeds", async () => {
  let save: ((value: { ok: boolean }) => void) | undefined;
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ title: "Survey", html: "<form></form>" }),
    })
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          save = resolve;
        }),
    );
  vi.stubGlobal("fetch", fetcher);
  const view = mount(<PublicAppViewer handle="ada" slug="survey" />);
  await act(async () => Promise.resolve());
  const frame = view.container.querySelector("iframe");
  await act(async () =>
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "tilo-form-submit", fields: { name: "Ada" } },
        source: window,
      }),
    ),
  );
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () =>
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "tilo-form-submit", fields: { name: "Ada" } },
        source: frame?.contentWindow,
      }),
    ),
  );
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(view.container.textContent).not.toContain("Thank you");
  await act(async () => save?.({ ok: true }));
  expect(view.container.textContent).toContain("Thank you");
});
