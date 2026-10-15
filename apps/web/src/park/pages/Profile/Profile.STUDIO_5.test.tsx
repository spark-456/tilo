// @vitest-environment happy-dom
// UI-STUDIO-5 Settings: the Studio sections. The scene is display state on this device (shared with Chat); Spending
// and limits and Ask before read the team's own rules from GET /v1/team, an Owner changes a switch with one write,
// a must-ask rule cannot be switched off, and nothing is shown that the server did not send.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import type { Api } from "../../api";
import type { TeamOp, TeamView } from "../../api/live/teamLive";
import { SCENE_KEY } from "../../studio/scenePref";
import {
  buttonNamed,
  buttonWith,
  cleanup,
  clickAndSettle,
  openTab,
  pressedOf,
  region,
  renderProfile,
  spyApi,
  switchNamed,
  text,
} from "./testApp";

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

const view = (role = "Owner"): TeamView => ({
  version: 3,
  me: { id: "u1", role },
  members: [{ id: "u1", role, limit_minor: 250000 }],
  switches: [
    { key: "spend", on: true, must_ask: true },
    { key: "weekend", on: false, must_ask: false },
  ],
  tools: [],
  capabilities: [],
  invites: [],
});
function teamApi(role = "Owner", write?: (op: TeamOp) => Promise<TeamView>) {
  const base = spyApi();
  const getTeamLive = vi.fn(async () => ({ data: view(role), source: "live" as const }));
  const writeTeam = vi.fn(async (op: TeamOp) => ({
    data: await (write ?? (async () => view(role)))(op),
    source: "live" as const,
  }));
  return { api: { ...base, getTeamLive, writeTeam } as unknown as Api, getTeamLive, writeTeam };
}

describe("STUDIO_5 Settings appearance: the scene behind the helper", () => {
  it("STUDIO_5 settings scene choice is pressed, remembered for Chat, and office by default", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Appearance");
    expect(pressedOf(buttonNamed(root, "Office"))).toBe("true");
    await clickAndSettle(buttonNamed(root, "Cosy room"));
    expect(pressedOf(buttonNamed(root, "Cosy room"))).toBe("true");
    expect(pressedOf(buttonNamed(root, "Office"))).toBe("false");
    // Chat (UI-STUDIO-2) reads the same key; its word for the cosy room is "room".
    expect(window.localStorage.getItem(SCENE_KEY)).toBe("room");
  });

  it("STUDIO_5 settings appearance keeps one theme control: Light, Dark and System", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Appearance");
    for (const sub of ["Bright lawns", "Lamps and glow", "Follows your device"])
      expect(buttonWith(root, sub).getAttribute("aria-pressed"), sub).not.toBeNull();
    await clickAndSettle(buttonWith(root, "Lamps and glow"));
    expect(app.setPref).toHaveBeenCalledWith("time", "night");
  });
});

describe("STUDIO_5 Settings: Spending and limits, Ask before", () => {
  it("STUDIO_5 settings limits show the server's own limit and say what is not kept", async () => {
    const { api, getTeamLive } = teamApi();
    const { root } = await renderProfile(makeApp(), api);
    expect(getTeamLive).not.toHaveBeenCalled(); // read only when the tab opens
    await openTab(root, "Spending and limits");
    const card = region(root, "Spending and limits");
    expect(text(card)).toContain("Up to ₹2,500");
    expect(text(card)).toContain("Daily and per-world caps are not kept yet");
    expect(card.querySelector(".park-btn--primary")).toBeNull();
  });

  it("STUDIO_5 settings ask before lists the server's switches and the owner flips one with one write", async () => {
    const { api, writeTeam } = teamApi();
    const { root } = await renderProfile(makeApp(), api);
    await openTab(root, "Ask before");
    const spend = switchNamed(root, "Spending money") as HTMLButtonElement;
    expect(spend.getAttribute("aria-checked")).toBe("true");
    expect(spend.disabled, "a must-ask rule cannot be switched off").toBe(true);
    await clickAndSettle(switchNamed(root, "Routines that fall on a weekend"));
    expect(writeTeam).toHaveBeenCalledTimes(1);
    expect(writeTeam).toHaveBeenCalledWith({ kind: "switch", key: "weekend", on: true });
  });

  it("STUDIO_5 settings ask before is read only for a member and says why", async () => {
    const { api, writeTeam } = teamApi("Member");
    const { root } = await renderProfile(makeApp(), api);
    await openTab(root, "Ask before");
    const weekend = switchNamed(root, "Routines that fall on a weekend") as HTMLButtonElement;
    expect(weekend.disabled).toBe(true);
    expect(text(region(root, "Ask before"))).toContain("Only an Owner can change the team.");
    expect(writeTeam).not.toHaveBeenCalled();
  });

  it("STUDIO_5 settings with no team rules on the fixture say not connected and invent none", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Ask before");
    const card = region(root, "Ask before");
    expect(text(card)).toContain("Not connected yet");
    expect(card.querySelectorAll('[role="switch"]')).toHaveLength(0);
  });
});
