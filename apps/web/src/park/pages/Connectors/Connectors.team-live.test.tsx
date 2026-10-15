// @vitest-environment happy-dom
// TEAM-WEB (FR-ACC-01): on a live Api the Connectors page shows the team's tool levels from GET /v1/team and
// changes one with PUT /v1/team/tools/{connector}. The connector catalogue itself has no route, so no sample
// connector appears; the per-skill saved level (FR-ACC-02) and Disconnect/Connect stay not built.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  flush,
  labelled,
  makeApp,
  renderPage,
  textOf,
} from "../../../../test-support/park/connectorsDom";
import { TiloApiError } from "../../../api/http";
import type { Api } from "../../api";
import type { TeamOp, TeamView } from "../../api/live/teamLive";
import { createLiveApi } from "../../api/liveApi";

afterEach(cleanup);

const view = (role = "Owner"): TeamView => ({
  version: 2,
  me: { id: "u1", role },
  members: [{ id: "u1", role, limit_minor: null }],
  switches: [],
  tools: [
    { connector: "gmail", level: "act" },
    { connector: "calendar", level: "read" },
  ],
  capabilities: [],
  invites: [],
});
const apiOf = (read: () => Promise<TeamView>, write?: (op: TeamOp) => Promise<TeamView>) => {
  const getTeamLive = vi.fn(async () => ({ data: await read(), source: "live" as const }));
  const writeTeam = vi.fn(async (op: TeamOp) => ({
    data: await (write ?? (() => Promise.reject(new Error("no write"))))(op),
    source: "live" as const,
  }));
  return {
    api: { ...createLiveApi(), getTeamLive, writeTeam } as unknown as Api,
    writeTeam,
    getTeamLive,
  };
};
// UI-STUDIO-5: each app's level is a radio group (Always, Ask me, Read only, Never), not a select.
const level = (root: ParentNode, id: string) => {
  const set = root.querySelector<HTMLFieldSetElement>(
    `fieldset[aria-label="Access level for ${id}"]`,
  );
  if (!set) return null;
  return {
    set,
    value: set.querySelector<HTMLInputElement>("input:checked")?.value,
    disabled: set.disabled,
  };
};
const pick = async (sel: { set: HTMLFieldSetElement } | null, value: string) => {
  const { act } = await import("react");
  await act(async () => {
    const radio = sel?.set.querySelector<HTMLInputElement>(`input[value="${value}"]`);
    if (!radio) throw new Error("no radio");
    radio.click();
  });
  await flush();
};
const status = (root: ParentNode) => root.querySelector("output")?.textContent?.trim() ?? "";

describe("TEAM_WEB_connectors_live: tool levels from the server", () => {
  it("TEAM_WEB_connectors_live_lists_the_servers_tools_with_their_levels_and_no_sample_connector", async () => {
    const { api } = apiOf(async () => view());
    const m = await renderPage(makeApp(), api);
    expect(level(m.container, "gmail")?.value).toBe("act");
    expect(level(m.container, "calendar")?.value).toBe("read");
    expect(textOf(m.container)).not.toContain("HubSpot");
    expect(textOf(m.container)).not.toContain("Not connected yet");
    expect(labelled(m.container, "Tool access")).not.toBeNull();
  });

  it("TEAM_WEB_connectors_live_owner_changes_a_level_with_one_write_and_it_sticks", async () => {
    const after: TeamView = {
      ...view(),
      tools: [
        { connector: "gmail", level: "draft" },
        { connector: "calendar", level: "read" },
      ],
    };
    const { api, writeTeam } = apiOf(
      async () => view(),
      async () => after,
    );
    const m = await renderPage(makeApp(), api);
    await pick(level(m.container, "gmail"), "draft");
    expect(writeTeam).toHaveBeenCalledTimes(1);
    expect(writeTeam).toHaveBeenCalledWith({ kind: "tool", connector: "gmail", level: "draft" });
    expect(level(m.container, "gmail")?.value).toBe("draft");
  });

  it("TEAM_WEB_connectors_live_failed_write_rolls_back_with_a_plain_message", async () => {
    const { api } = apiOf(
      async () => view(),
      async () => Promise.reject(new TiloApiError("x", 403, false, true)),
    );
    const m = await renderPage(makeApp(), api);
    await pick(level(m.container, "gmail"), "off");
    expect(level(m.container, "gmail")?.value).toBe("act");
    expect(status(m.container)).toBe("Only an Owner signed in on the web can change this.");
  });

  it("TEAM_WEB_connectors_live_non_owner_cannot_change_a_level", async () => {
    const { api, writeTeam } = apiOf(async () => view("Member"));
    const m = await renderPage(makeApp(), api);
    expect(level(m.container, "gmail")?.disabled).toBe(true);
    expect(status(m.container)).toBe("Only an Owner can change tool access. You can look at it.");
    expect(writeTeam).not.toHaveBeenCalled();
  });

  it("TEAM_WEB_connectors_live_503_says_team_controls_are_not_set_up_and_does_not_crash", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { api } = apiOf(async () => Promise.reject(new TiloApiError("x", 503, true)));
    const m = await renderPage(makeApp(), api);
    expect(textOf(m.container)).toContain("Team controls are not set up on this install yet.");
    expect(m.container.querySelector("fieldset")).toBeNull();
    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });

  it("TEAM_WEB_connectors_live_off_copy_does_not_overpromise_beyond_the_run_path", async () => {
    const off: TeamView = { ...view(), tools: [{ connector: "gmail", level: "off" }] };
    const { api } = apiOf(async () => off);
    const m = await renderPage(makeApp(), api);
    expect(textOf(m.container)).not.toContain("Agents cannot use this tool.");
    expect(textOf(m.container)).toMatch(/runs/i);
    expect(textOf(m.container)).toMatch(/Email Autopilot|calendar sync/i);
  });

  it("TEAM_WEB_connectors_live_names_the_per_skill_level_as_not_built", async () => {
    const { api } = apiOf(async () => view());
    const m = await renderPage(makeApp(), api);
    expect(textOf(m.container)).toContain("A saved level for each skill is not built yet.");
  });
});
