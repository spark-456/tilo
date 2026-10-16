// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, makeApp, renderTeam } from "../../../../test-support/park/teamHarness";
import { createLiveApi } from "../../api/liveApi";
import { ORGANISATION_SETUP } from "../../api/organisationSetup";

afterEach(cleanup);
const apiFor = (people: unknown[], status = 200) =>
  createLiveApi({
    baseUrl: "https://api.example.test",
    fetch: vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ you: "u_self", people }), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
    ),
  });

describe("FR_TEAM_01 live Team", () => {
  it("FR_TEAM_01 displays member names without waiting for unavailable policy reads", async () => {
    const { root } = await renderTeam(makeApp(), apiFor([{ id: "u_peer", display_name: "Peer" }]));
    expect(root.textContent).toContain("Peer");
    expect(root.querySelectorAll('[data-testid="live-team"]')).toHaveLength(1);
    expect(root.textContent).not.toContain("Not available");
    expect(root.textContent).not.toMatch(/null|undefined|No answers or fixes yet/);
    expect(root.querySelector('input[aria-label="Invite by email"]')).toBeNull();
    expect(root.querySelector("select")).toBeNull();
    expect(root.querySelector("button.park-team-btn--red")).toBeNull();
  });
  it("FR_TEAM_01 displays owner-visible memberships and distinguishes an empty list", async () => {
    const { root } = await renderTeam(
      makeApp(),
      apiFor([
        { id: "u_self", display_name: "Self", org_role: "owner", memberships: [] },
        {
          id: "u_peer",
          display_name: "Peer",
          org_role: "member",
          memberships: [{ team: "t_ops" }],
        },
      ]),
    );
    expect(root.textContent).toContain("Owner");
    expect(root.textContent).toContain("t_ops");
    expect(root.textContent).not.toContain("Not available");
  });
  it("LIVE_GAPS_1A shows an honest error instead of a fixture list", async () => {
    const { root } = await renderTeam(makeApp(), apiFor([], 503));
    expect(root.textContent).toContain("Team data is unavailable");
    expect(root.querySelector('[data-testid="live-team"]')).toBeNull();
  });
});

it("LIVE-PEOPLE FR-TEAM-01 absent person shows organisation setup without member controls", async () => {
  const { root } = await renderTeam(makeApp(), apiFor([], 404));
  expect(root.textContent).toContain(ORGANISATION_SETUP);
  expect(root.textContent).not.toContain("Team data is unavailable");
  expect(root.textContent).not.toContain("0 people");
  expect(root.querySelector('input[aria-label="Invite by email"]')).toBeNull();
});
