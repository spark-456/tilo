// @vitest-environment happy-dom
// OPEN-ACCESS (owner's order, 16 Oct 2026): "Everyone must be able to access through their mail". A person who signs in
// with Google on a deployment with an API reaches the app straight away: no "visitor or judge" question, no "under
// construction" notice, no call to /access. The only step before the app is PersonStartup (their own record in the org).
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q } from "../test-support/park/componentsHarness";

const calls: string[] = [];

vi.mock("./park/app/ParkApp", async () => {
  const { createElement } = await import("react");
  return { default: () => createElement("div", { "data-testid": "park-app" }, "park app") };
});
vi.mock("./auth/SignInGate", () => ({
  SignInGate: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("./auth/session", () => {
  const state = { status: "google", email: "new.person@example.test", displayName: "New Person" };
  return { session: { subscribe: () => () => undefined, getState: () => state } };
});
vi.mock("./api/ClientProvider", () => ({
  API_URL: "https://api.open-access.test",
  appCheckToken: undefined,
  authToken: undefined,
}));
vi.mock("./api/http", () => ({
  HttpClient: class {
    getJson(path: string) {
      calls.push(`GET ${path}`);
      return Promise.resolve({});
    }
    postJson(path: string) {
      calls.push(`POST ${path}`);
      return Promise.resolve({});
    }
  },
}));

import { Root } from "./Root";

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};

afterEach(() => {
  cleanup();
  calls.length = 0;
});

describe("OPEN_ACCESS web: a Google sign-in goes straight to the app", () => {
  it("OPEN_ACCESS_a_new_google_person_sees_the_app_and_no_declaration_or_notice", async () => {
    const m = mount(<Root />);
    await settle();
    expect(q(m.container, '[data-testid="park-app"]')).not.toBeNull();
    for (const gone of ["sign-up-declaration", "under-construction", "access-failed"]) {
      expect(document.querySelector(`[data-testid="${gone}"]`), gone).toBeNull();
    }
    expect(document.body.textContent).not.toMatch(/visitor|judge|under construction/i);
  });

  it("OPEN_ACCESS_the_web_never_calls_the_retired_access_routes", async () => {
    mount(<Root />);
    await settle();
    expect(calls.filter((c) => c.includes("/access"))).toEqual([]);
    expect(calls).toContain("GET /v1/people"); // their own record in the org, the one startup step
  });
});
