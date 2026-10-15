// @vitest-environment happy-dom
// STUDIO-WIRE-1 (FR-ACC-01/03/04): the live Connectors list shows only what GET /v1/connectors and GET /v1/team serve.
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { makeApp, renderPage, textOf } from "../../../../test-support/park/connectorsDom";
import { createLiveApi } from "../../api/liveApi";

afterEach(cleanup);
const connector = (over: Record<string, unknown>) => ({
  id: "crm",
  name: "Actual CRM",
  state: "connected",
  state_known: true,
  scopes: ["contacts.read", "deals.read"],
  expires_at: "2026-11-01T00:00:00Z",
  ...over,
});
const people = (role: "owner" | "member") => ({
  you: "me",
  people: [{ id: "me", display_name: "Me", org_role: role }],
});
const team = (level: string) => ({
  version: 1,
  me: { id: "me", role: "Owner" },
  members: [],
  switches: [],
  tools: [
    { connector: "crm", level },
    { connector: "mail", level: "off" },
  ],
  capabilities: [],
  invites: [],
});
const setup = (role: "owner" | "member", connectors: unknown[] = [connector({})]) => {
  const fetch = vi.fn(async (url: RequestInfo | URL) => {
    const path = new URL(String(url)).pathname;
    if (path === "/v1/connectors") return new Response(JSON.stringify({ connectors }));
    if (path === "/v1/people") return new Response(JSON.stringify(people(role)));
    if (path === "/v1/team") return new Response(JSON.stringify(team("draft")));
    return new Response("{}", { status: 404 });
  });
  return { fetch, api: createLiveApi({ baseUrl: "https://api.test", fetch }) };
};
const paths = (fetch: ReturnType<typeof setup>["fetch"]) =>
  fetch.mock.calls.map((c) => new URL(String(c[0])).pathname);

it("FR_ACC_01_STUDIO_WIRE_1 owner sees each app's access level from GET /v1/team", async () => {
  const { api, fetch } = setup("owner", [connector({}), connector({ id: "mail", name: "Mail" })]);
  const { container } = await renderPage(makeApp(), api);
  const crm = container.querySelector('[aria-label="Actual CRM"]');
  const mail = container.querySelector('[aria-label="Mail"]');
  expect(textOf(crm as Element)).toContain("Access level: Ask me");
  expect(textOf(mail as Element)).toContain("Access level: Never");
  expect(paths(fetch)).toEqual(["/v1/connectors", "/v1/people", "/v1/team"]);
});

it("FR_ACC_01_STUDIO_WIRE_1 a non-owner never requests the owner route and sees who sets the level", async () => {
  const { api, fetch } = setup("member");
  const { container } = await renderPage(makeApp(), api);
  expect(textOf(container)).toContain("Access level: Set by the workspace owner");
  expect(paths(fetch)).not.toContain("/v1/team");
});

it("FR_ACC_03_STUDIO_WIRE_1 an unreadable people reply keeps the access level honest", async () => {
  const fetch = vi.fn(async (url: RequestInfo | URL) =>
    new URL(String(url)).pathname === "/v1/connectors"
      ? new Response(JSON.stringify({ connectors: [connector({})] }))
      : new Response("{}", { status: 200 }),
  );
  const { container } = await renderPage(
    makeApp(),
    createLiveApi({ baseUrl: "https://api.test", fetch }),
  );
  expect(textOf(container)).toContain("Access level not available yet");
});

it("FR_ACC_04_STUDIO_WIRE_1 scopes and expiry come from the list; null expiry says none recorded", async () => {
  const { api } = setup("member", [
    connector({}),
    connector({ id: "mail", name: "Mail", expires_at: null, scopes: [] }),
    connector({ id: "chat", name: "Chat", state: "available", state_known: false }),
  ]);
  const { container } = await renderPage(makeApp(), api);
  const crm = textOf(container.querySelector('[aria-label="Actual CRM"]') as Element);
  expect(crm).toContain("Granted scopes: contacts.read, deals.read");
  expect(crm).toContain("Grant expiry: 2026-11-01T00:00:00Z");
  const mail = textOf(container.querySelector('[aria-label="Mail"]') as Element);
  expect(mail).toContain("Grant expiry: No expiry recorded");
  expect(mail).toContain("Granted scopes: None recorded");
  const chat = textOf(container.querySelector('[aria-label="Chat"]') as Element);
  expect(chat).toContain("Grant expiry: Not available yet");
  expect(chat).toContain("Connection state not available yet");
});

it("FR_ACC_01_STUDIO_WIRE_1 the contradictory connect note is gone and usage stays unavailable", async () => {
  const { api } = setup("member");
  const { container } = await renderPage(makeApp(), api);
  const text = textOf(container);
  expect(text).not.toContain("Connecting and reconnecting these apps is not available");
  expect(text).toContain("What Tilo may do in each app is set beside this list.");
  expect(text).toContain("Usage not available yet");
  expect(text).toContain("Sync history not available yet");
});
