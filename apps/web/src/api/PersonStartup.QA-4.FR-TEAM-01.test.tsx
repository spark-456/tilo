// @vitest-environment happy-dom
import { StrictMode, act } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../test-support/park/componentsHarness";
import { PersonStartup } from "./PersonStartup";
vi.mock("../auth/session", () => ({
  session: {
    getState: () => ({ status: "google", email: "founder@example.test", displayName: "Founder" }),
  },
}));
beforeEach(() => vi.resetModules());
afterEach(cleanup);

it.each([201, 403, 503, 409])(
  "QA-4 FR-TEAM-01 startup settles %s before consumers and never repeats founding",
  async (status) => {
    const { HttpClient } = await import("./http");
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });
    let founded = false;
    const fetch = vi.fn(async (url: RequestInfo | URL) => {
      if (String(url).endsWith("/first")) {
        await pending;
        founded = status === 201;
        return new Response("{}", { status });
      }
      return new Response("{}", { status: founded ? 200 : 404 });
    });
    const http = new HttpClient({ baseUrl: "https://qa4.test", fetch });
    const view = () => (
      <StrictMode>
        <PersonStartup http={http}>
          <p>First-load consumers</p>
        </PersonStartup>
      </StrictMode>
    );
    const ui = mount(view());
    await act(async () => {
      await Promise.resolve();
    });
    expect(ui.container.textContent).not.toContain("First-load consumers");
    await act(async () => {
      finish();
      await pending;
    });
    expect(ui.container.textContent).toContain("First-load consumers");
    ui.unmount();
    await act(async () => {
      mount(view());
    });
    expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/first"))).toHaveLength(1);
  },
);
it("QA-4 FR-TEAM-01 existing person needs no founding write", async () => {
  const { HttpClient } = await import("./http");
  const fetch = vi.fn(async () => new Response("{}"));
  await act(async () => {
    mount(
      <PersonStartup http={new HttpClient({ baseUrl: "https://qa4.test", fetch })}>
        Ready
      </PersonStartup>,
    );
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).toContain("Ready");
});
