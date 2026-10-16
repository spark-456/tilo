// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup, makeApp, renderTeam } from "../../../../test-support/park/teamHarness";
import { createLiveApi } from "../../api/liveApi";
import type { TeamView } from "../../api/live/teamLive";

afterEach(cleanup);

it("FR_TEAM_01_team_resources_show_real_shared_worlds_and_pins_with_honest_empty_states", async () => {
  const view: TeamView = {
    version: 4,
    me: { id: "u1", role: "Owner" },
    members: [{ id: "u1", role: "Owner", limit_minor: null }],
    switches: [],
    tools: [],
    capabilities: [],
    invites: [],
  };
  const api = {
    ...createLiveApi(),
    getTeamLive: async () => ({ data: view, source: "live" as const }),
    getWorlds: async () => ({
      data: [
        {
          id: "w_shared",
          name: "Q3 deck",
          short: "Q3 deck",
          tier: "Village",
          tool: "",
          st: "running",
          agents: 0,
          spend: "",
          spendV: 0,
          nextL: "",
          nextV: "",
          owner: "",
          started: "",
          access: "team",
        },
      ],
      source: "live" as const,
    }),
  };
  const { root } = await renderTeam(makeApp(), api as never);
  expect(root.textContent).toContain("Shared worlds");
  expect(root.textContent).toContain("Q3 deck");
  expect(root.textContent).toContain("Team pins");
  expect(root.textContent).toContain("Team pins are not connected on this install.");
});
