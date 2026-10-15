// @vitest-environment happy-dom
// CONNECTORS-DESIGN (FR-ACC-01/03/04, design "Tilo S Connectors"): the per-app manage panel on the live list, the
// one sample strip on the demo list, the styled run-connection cards, and the search control height.
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import { flush, makeApp, renderPage, textOf } from "../../../../test-support/park/connectorsDom";
import { createLiveApi } from "../../api/liveApi";

afterEach(cleanup);
const crm = {
  id: "crm",
  name: "Actual CRM",
  state: "connected",
  state_known: true,
  scopes: ["contacts.read"],
  expires_at: "2026-11-01T00:00:00Z",
};
const team = (level: string) => ({
  version: 1,
  me: { id: "me", role: "Owner" },
  members: [],
  switches: [],
  tools: [{ connector: "crm", level }],
  capabilities: [],
  invites: [],
});
const setup = (
  role: "owner" | "member",
  put: () => Response = () => Response.json(team("act")),
) => {
  const fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const { pathname } = new URL(String(url));
    if (init?.method === "PUT") return put();
    if (pathname === "/v1/connectors") return Response.json({ connectors: [crm] });
    if (pathname === "/v1/people")
      return Response.json({
        you: "me",
        people: [{ id: "me", display_name: "Me", org_role: role }],
      });
    if (pathname === "/v1/team") return Response.json(team("draft"));
    return new Response("{}", { status: 404 });
  });
  return { fetch, api: createLiveApi({ baseUrl: "https://api.test", fetch }) };
};
const open = async (role: "owner" | "member", put?: () => Response) => {
  const s = setup(role, put);
  const { container } = await renderPage(makeApp(), s.api);
  await flush();
  const manage = container.querySelector('[aria-label="Manage Actual CRM"]') as HTMLElement;
  click(manage);
  return { ...s, container, manage };
};
const radios = (root: ParentNode) => [
  ...root.querySelectorAll<HTMLInputElement>(".park-connectors-panel input[type=radio]"),
];

describe("CONNECTORS-DESIGN live manage panel", () => {
  it("FR_ACC_01_CONNECTORS_DESIGN owner picks Always, Ask me, Read only or Never and the PUT saves it", async () => {
    const { container, fetch } = await open("owner");
    const choices = radios(container);
    expect(choices.map((r) => textOf(r.parentElement as Element))).toEqual([
      "Always",
      "Ask me",
      "Read only",
      "Never",
    ]);
    expect(choices.find((r) => r.checked)?.value).toBe("draft");
    click(choices[0] as HTMLElement);
    await flush();
    const put = fetch.mock.calls.find((c) => c[1]?.method === "PUT");
    expect(new URL(String(put?.[0])).pathname).toBe("/v1/team/tools/crm");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ level: "act" });
    expect(radios(container).find((r) => r.checked)?.value).toBe("act");
    expect(textOf(container.querySelector('[aria-label="Actual CRM"]') as Element)).toContain(
      "Access level: Always",
    );
  });

  it("FR_ACC_01_CONNECTORS_DESIGN a refused save rolls back and says why", async () => {
    const { container } = await open("owner", () => new Response("{}", { status: 403 }));
    click(radios(container)[3] as HTMLElement);
    await flush();
    expect(radios(container).find((r) => r.checked)?.value).toBe("draft");
    expect(textOf(container.querySelector(".park-connectors-panel") as Element)).toContain(
      "Only an Owner signed in on the web can change this.",
    );
  });

  it("FR_ACC_01_CONNECTORS_DESIGN a non-owner reads who sets the level, sees no choices and makes no write", async () => {
    const { container, fetch } = await open("member");
    const panel = textOf(container.querySelector(".park-connectors-panel") as Element);
    expect(panel).toContain("Set by the workspace owner");
    expect(radios(container)).toHaveLength(0);
    expect(fetch.mock.calls.some((c) => c[1]?.method === "PUT")).toBe(false);
  });

  it("FR_ACC_03_CONNECTORS_DESIGN usage and sync history stay honest in the panel; focus moves in and back", async () => {
    const { container, manage } = await open("member");
    const panel = container.querySelector(".park-connectors-panel") as HTMLElement;
    const text = textOf(panel);
    for (const s of ["Usage not available yet", "Sync history not available yet", "contacts.read"])
      expect(text).toContain(s);
    expect(document.activeElement?.className).toContain("park-connectors-panel-name");
    click(panel.querySelector(".park-connectors-panel-close") as HTMLElement);
    expect(container.querySelector(".park-connectors-panel")).toBeNull();
    expect(document.activeElement).toBe(manage);
    expect(manage.getAttribute("aria-pressed")).toBe("false");
  });
});

describe("CONNECTORS-DESIGN demo list", () => {
  it("FR_CON_CONNECTORS_DESIGN the run connections are cards with status pills, not bare bullet lists", async () => {
    const { container } = await renderPage(makeApp());
    const blocks = [...container.querySelectorAll("section.park-runconn")];
    expect(blocks.map((b) => b.getAttribute("aria-label"))).toEqual([
      "Run connections",
      "Waiting for your consent",
    ]);
    expect(container.querySelectorAll(".park-runconn-pill").length).toBeGreaterThan(0);
    expect(
      textOf(container.querySelector('[data-testid="connected-accounts"]') as Element),
    ).toContain("Starting state:Connected");
    expect(textOf(blocks[1] as Element)).toContain("No access request is waiting.");
  });

  it("FR_CON_CONNECTORS_DESIGN the search control is at least 40 px high, 44 px on a phone", () => {
    const css = fs.readFileSync(path.join(__dirname, "Connectors.studio.css"), "utf8");
    expect(css).toMatch(/park-connectors-search-input \{[^}]*min-height: 40px/);
    expect(css).toMatch(
      /@media \(max-width: 560px\)[\s\S]*park-connectors-search-input \{[^}]*min-height: 44px/,
    );
  });
});
