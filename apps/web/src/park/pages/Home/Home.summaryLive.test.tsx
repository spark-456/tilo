// @vitest-environment happy-dom
// HOME_SUMMARY_LIVE (PRD 9.4: sample data is never shown as live; numbers come only from served data). On the
// live path the greeting summary and the Today panel may say only what the served worlds and served decisions
// say. The fixture sentence "38 agents are at work across 4 worlds" and the fixed "Nothing needs you right now"
// belong to the fixture path, which stays unchanged.
//
// The live Api here is the fixture Api with every result marked live (`liveSourced`), plus served worlds (the
// shape `GET /worlds` makes: no agent count, no progress) and served decisions.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { mountHome, settle, textOf, todayRegion } from "../../../../test-support/park/homeHarness";
import { liveSourced, mountLiveHome } from "../../../../test-support/park/liveHomeHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import { type WorldListItem, worldsFromList } from "../../api/live/worldsFromList";
import type { Decision } from "../../api/types";

afterEach(cleanup);

const item = (id: string, status: WorldListItem["status"]): WorldListItem => ({
  world_id: id,
  title: `Served ${id}`,
  status,
  created_at: null,
  last_seq: 1,
});

const servedWorlds = (...items: WorldListItem[]) => ({
  data: worldsFromList(items),
  source: "live" as const,
});

async function twoDecisions(): Promise<Decision[]> {
  return (await createFixtureApi().getDecisions()).data.slice(0, 2);
}

const live = (over: Partial<Api>): Api => liveSourced(over);
const summaryOf = (el: HTMLElement): string | null => {
  const node = el.querySelector(".park-home-summary");
  return node ? textOf(node) : null;
};
// UI-STUDIO-2: the world cards are their own section, titled "Your worlds" live and "Sample worlds" on fixtures.
const worldsText = (el: HTMLElement): string =>
  textOf(el.querySelector(".park-home-grid .park-home-section") as Element);
const heroOf = (el: HTMLElement): string => textOf(el.querySelector(".park-home-hero") as Element);

describe("HOME_SUMMARY_LIVE: the summary is derived from served worlds and decisions", () => {
  it("HOME_SUMMARY_LIVE_served_worlds_and_no_open_decision_say_only_the_served_count", async () => {
    const rig = await mountLiveHome(
      live({
        getWorlds: async () =>
          servedWorlds(item("a", "started"), item("b", "started"), item("c", "idle")),
        getDecisions: async () => ({ data: [], source: "live" }),
      }),
    );
    expect(summaryOf(rig.el)).toBe("2 worlds are in progress. Nothing needs you right now.");
    expect(heroOf(rig.el)).not.toMatch(/38|agents/i);
    expect(heroOf(rig.el)).toContain("You’re all caught up");
  });

  it("HOME_SUMMARY_LIVE_one_served_world_and_served_decisions_count_the_decisions_served", async () => {
    const decided = await twoDecisions();
    const rig = await mountLiveHome(
      live({
        getWorlds: async () => servedWorlds(item("a", "started")),
        getDecisions: async () => ({ data: decided, source: "live" }),
      }),
    );
    expect(summaryOf(rig.el)).toBe("1 world is in progress. Two things need you.");
    expect(heroOf(rig.el)).toContain("2 decisions waiting");
    expect(heroOf(rig.el)).not.toMatch(/38|agents/i);
  });

  it("HOME_SUMMARY_LIVE_nothing_served_shows_no_invented_number_and_no_caught_up_claim", async () => {
    const rig = await mountLiveHome(
      live({
        getWorlds: async () => servedWorlds(),
        getDecisions: async () => {
          throw new Error("offline");
        },
      }),
    );
    const summary = summaryOf(rig.el);
    expect(summary ?? "").not.toMatch(/\d|agents|worlds|nothing needs you/i);
    expect(heroOf(rig.el)).not.toMatch(/38|agents|all caught up|nothing needs you/i);
    expect(textOf(todayRegion(rig.el))).not.toMatch(/38/);
  });

  it("HOME_SUMMARY_LIVE_a_served_running_world_shows_no_invented_progress_percent", async () => {
    const rig = await mountLiveHome(
      live({
        getWorlds: async () => servedWorlds(item("a", "started")),
        getDecisions: async () => ({ data: [], source: "live" }),
      }),
    );
    const worlds = worldsText(rig.el);
    expect(worlds).toContain("Served a");
    expect(worlds).not.toMatch(/Running · 0%|\b0%/);
  });

  it("CX_T_HOME_served_worlds_are_recent_and_the_fixture_panel_stays_sample", async () => {
    const rig = await mountLiveHome(
      live({
        getWorlds: async () => servedWorlds(item("a", "started")),
        getDecisions: async () => ({ data: [], source: "live" }),
      }),
    );
    const served = worldsText(rig.el);
    expect(served).toContain("Recent worlds");
    expect(served).not.toContain("Sample worlds");
    cleanup();
    const { el } = await mountHome();
    await settle();
    const sample = worldsText(el);
    expect(sample).toContain("Sample worlds");
    expect(sample).not.toContain("Your worlds"); // no recorded event stands behind sample data (HR-1)
  });
});

describe("HOME_SUMMARY_LIVE: the fixture path is unchanged", () => {
  it("HOME_SUMMARY_LIVE_fixture_keeps_the_reference_sentence", async () => {
    const { el } = await mountHome();
    await settle();
    expect(summaryOf(el)).toMatch(/^38 agents are at work across 4 worlds\. /);
  });
});
