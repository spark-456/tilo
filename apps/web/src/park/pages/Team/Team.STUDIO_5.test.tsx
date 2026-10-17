// @vitest-environment happy-dom
// UI-STUDIO-5 Team (design/studio-v2 "Tilo S Team"): on a live Api the page shows your teams (SELF-SERVE-TEAMS) where
// the design's team list sits, the people as a table, "Who can say yes" beside them and the helpers below. Nothing
// is shown that the server did not send: no backups, no usage counts, no invented names.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, makeApp, renderTeam } from "../../../../test-support/park/teamHarness";
import { createLiveApi } from "../../api/liveApi";

afterEach(() => {
  teamsBody = { you: "u_self", teams: [] };
  cleanup();
});

const people = {
  you: "u_self",
  people: [
    { id: "u_self", display_name: "Maya Rao", org_role: "owner", memberships: [] },
    { id: "u_peer", display_name: "Jo Park", org_role: "member", memberships: [{ team: "t_ops" }] },
  ],
};
let teamsBody: unknown = { you: "u_self", teams: [] };
const liveApi = () =>
  createLiveApi({
    baseUrl: "https://api.example.test",
    fetch: vi.fn<typeof fetch>(async (url) => {
      const path = new URL(String(url)).pathname;
      const body =
        path === "/v1/teams"
          ? teamsBody
          : path.startsWith("/v1/teams/")
            ? { members: [{ id: "u_self", display_name: "Maya Rao", lead: true }] }
            : people;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  });

describe("STUDIO_5 Team live layout", () => {
  it("STUDIO_5 team people are a table with the server's names, roles and teams", async () => {
    const { root } = await renderTeam(makeApp(), liveApi());
    const table = root.querySelector('[data-testid="live-team"] table');
    expect(table).not.toBeNull();
    const heads = [...(table?.querySelectorAll("th") ?? [])].map((th) => th.textContent);
    expect(heads).toEqual(["Person", "Role", "Teams"]);
    const rows = [...(table?.querySelectorAll("tbody tr") ?? [])].map((r) => r.textContent ?? "");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain("Maya Rao");
    expect(rows[1]).toContain("t_ops");
  });

  it("STUDIO_5 team your teams panel sits in the main column above the people", async () => {
    teamsBody = { you: "u_self", teams: [{ team: "tm_1", lead: true, state: "member" }] };
    const { root } = await renderTeam(makeApp(), liveApi());
    const main = root.querySelector(".park-team-main");
    const panel = main?.querySelector('[data-testid="self-serve-teams"]');
    const people = main?.querySelector('[data-testid="live-team"]');
    expect(panel, "Your teams is in the main column").toBeTruthy();
    expect(people).toBeTruthy();
    expect(
      (panel as Node).compareDocumentPosition(people as Node) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(panel?.textContent).toContain("Create a team");
  });

  it("STUDIO_5 team who can say yes and helpers invent no backups, counts or people", async () => {
    const { root } = await renderTeam(makeApp(), liveApi());
    const side = root.querySelector('[aria-label="Who can say yes"]');
    expect(side?.textContent).toContain("Spending money");
    expect(side?.textContent).not.toContain("not available yet");
    expect(root.querySelector('[aria-label="Who helped Tilo learn"]')).toBeNull();
    const helpers = root.querySelectorAll('[aria-label="Your helpers"] li');
    expect(helpers).toHaveLength(6);
    expect(root.textContent).not.toMatch(/In \d+ worlds|Away ·|Ravi|Oskar/);
    expect(root.querySelectorAll("button.park-btn--primary").length).toBeLessThanOrEqual(1);
  });

  it("STUDIO_5 team the owner's settings stay behind one disclosure, read only when opened", async () => {
    const { root } = await renderTeam(makeApp(), liveApi());
    const details = root.querySelectorAll("details");
    expect(details).toHaveLength(1);
    expect(details[0]?.querySelector("summary")?.textContent).toBe("Manage team settings");
    expect(details[0]?.open).toBe(false);
  });
});
