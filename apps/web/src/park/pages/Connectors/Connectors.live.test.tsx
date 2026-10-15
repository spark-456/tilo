// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { makeApp, renderPage, textOf, typeInto } from "../../../../test-support/park/connectorsDom";
import { TiloApiError } from "../../../api/http";
import { NotBuilt, createLiveApi } from "../../api/liveApi";

afterEach(cleanup);
const row = (state = "connected", known = true) => ({
  id: "crm",
  name: "Actual CRM",
  state,
  state_known: known,
  scopes: ["contacts.read"],
  expires_at: "2026-10-10T00:00:00Z",
});
const setup = (body: unknown, status = 200) => {
  const fetch = vi.fn(
    async (_url: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify(body), { status }),
  );
  return { fetch, api: createLiveApi({ baseUrl: "https://api.test", fetch }) };
};

it("FR_ACC_01_03_04 live page loads the existing route without needing skills or demo terms", async () => {
  const { api, fetch } = setup({
    connectors: [
      row(),
      { ...row("available", false), id: "mail", name: "Actual Mail" },
      { ...row("attention"), id: "chat", name: "Actual Chat" },
    ],
  });
  const app = makeApp();
  const { container: root } = await renderPage(app, api);
  expect((fetch.mock.calls as unknown[][]).map(([u]) => new URL(String(u)).pathname)).toEqual([
    "/v1/connectors",
    "/v1/people",
  ]);
  expect(fetch.mock.calls[0]?.[0]).toBe("https://api.test/v1/connectors");
  const text = textOf(root);
  for (const word of [
    "Actual CRM",
    "Actual Mail",
    "Actual Chat",
    "Connection state not available yet",
    "Needs attention",
    "contacts.read",
    "2026-10-10T00:00:00Z",
    "Access level not available yet",
  ])
    expect(text).toContain(word);
  expect(text).not.toMatch(
    /Synced|Healthy|Connected just now|Not used yet|60\+|HubSpot|reconnected for/,
  );
  const labels = [...root.querySelectorAll("button")].map((b) => b.getAttribute("aria-label"));
  expect(labels).toEqual(["Manage Actual CRM", "Manage Actual Mail", "Manage Actual Chat"]);
  const search = root.querySelector<HTMLInputElement>('input[aria-label="Search connectors"]');
  expect(search).not.toBeNull();
  typeInto(search as HTMLInputElement, "Actual Mail");
  expect(textOf(root)).toContain("Actual Mail");
  expect(textOf(root)).not.toContain("Actual CRM");
  expect(app.toast).not.toHaveBeenCalled();
});
it("FR_ACC_03 live empty list and unreadable or failed reads never become demo data", async () => {
  const empty = await renderPage(makeApp(), setup({ connectors: [] }).api);
  expect(textOf(empty.container)).toContain("No connectors available yet");
  const bad = setup({ connectors: [row("unknown")] });
  await expect(bad.api.getConnectors()).rejects.toBeInstanceOf(TiloApiError);
  const failed = await renderPage(makeApp(), setup({ detail: "Unavailable" }, 503).api);
  expect(textOf(failed.container)).toContain("Connector data is unavailable");
  await expect(createLiveApi().getConnectors()).rejects.toBeInstanceOf(NotBuilt);
});
