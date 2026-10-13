// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { flush, makeApp, renderPage } from "../../../../test-support/park/connectorsDom";
import { renderTeam } from "../../../../test-support/park/teamHarness";
import { createLiveApi } from "../../api/liveApi";

afterEach(cleanup);
const team = {
  version: 1,
  me: { id: "owner", role: "Owner" },
  members: [{ id: "owner", role: "Owner", limit_minor: null }],
  switches: [],
  tools: [{ connector: "mail", level: "read" }],
  capabilities: [],
  invites: [],
};
const setup = (failed = false) => {
  const fetch = vi.fn(async (url: RequestInfo | URL) => {
    const path = new URL(String(url)).pathname;
    const body =
      path === "/v1/team"
        ? team
        : path === "/v1/people"
          ? { you: "owner", people: [{ id: "owner", display_name: "Actual owner" }] }
          : {
              connectors: [
                {
                  id: "mail",
                  name: "Actual Mail",
                  state: "connected",
                  state_known: true,
                  scopes: [],
                  expires_at: null,
                },
              ],
            };
    return new Response(JSON.stringify(body), {
      status: failed && path === "/v1/team" ? 503 : 200,
    });
  });
  const api = createLiveApi({ baseUrl: "https://api.test", fetch });
  // Isolate page directory reads from the provider's independent first-run worlds preflight.
  api.getWorlds = vi.fn(async () => {
    throw new Error("Worlds unavailable in this directory test");
  });
  return { fetch, api };
};
async function expand(root: ParentNode) {
  const details = root.querySelector("details");
  if (!details) throw new Error("Missing team controls disclosure");
  await act(async () => {
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
  await flush();
}

it("TEAM_WEB_integration_catalogue_remains_when_owner_opens_team_controls", async () => {
  const { api, fetch } = setup();
  const { container } = await renderPage(makeApp(), api);
  expect(fetch.mock.calls.map(([url]) => String(url))).toEqual(["https://api.test/v1/connectors"]);
  await expand(container);
  expect(fetch.mock.calls.map(([url]) => String(url))).toEqual([
    "https://api.test/v1/connectors",
    "https://api.test/v1/team",
  ]);
  expect(container.textContent).toContain("Actual Mail");
  expect(container.querySelector('select[aria-label="Access level for mail"]')).not.toBeNull();
});

it("TEAM_WEB_integration_people_directory_survives_failed_team_controls_read", async () => {
  const { api, fetch } = setup(true);
  const { root } = await renderTeam(makeApp(), api);
  expect(fetch.mock.calls.map(([url]) => String(url))).toEqual(["https://api.test/v1/people"]);
  await expand(root);
  expect(fetch.mock.calls.map(([url]) => String(url))).toEqual([
    "https://api.test/v1/people",
    "https://api.test/v1/team",
  ]);
  expect(root.textContent).toContain("Actual owner");
  expect(root.textContent).toContain("Team controls are not set up on this install yet.");
  expect(root.querySelector('[data-testid="live-team"]')).not.toBeNull();
  expect(root.querySelector("select")).toBeNull();
});
