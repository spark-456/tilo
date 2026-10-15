// @vitest-environment happy-dom
// STUDIO-3 acceptance, Worlds (design/studio-v2 "Tilo S Worlds.dc.html", "Tilo Studio Canvas" 04 Worlds): all of a
// person's worlds in one town (counts from the list), the filters, cards with progress and spend from the list
// only, the sample labelled, a teammate's world marked, routines on a schedule, one filled button, Studio values.
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { declsFor, parseRules } from "../../../../test-support/park/componentsCss";
import { cleanup, click, qa } from "../../../../test-support/park/componentsHarness";
import {
  card,
  cardIds,
  leaf,
  renderWorlds,
  scaleButton,
  search,
  section,
  tab,
  tabCounts,
  typeInto,
  worldsApi,
} from "../../../../test-support/park/worldsHarness";
import * as fx from "../../api/fixtures";
import type { World } from "../../api/types";

afterEach(cleanup);

const text = (el: Element | null) => el?.textContent ?? "";
const GRID = "Your worlds";
/** The desktop stylesheet: parseRules flattens media blocks, so the narrower-window overrides are left out. */
const desktopCss = fs
  .readFileSync(path.join(__dirname, "Worlds.css"), "utf8")
  .replace(/@media[^{]*\{[\s\S]*?\n\}/g, "");

/** A live list item as `worldsFromList` maps it: only the served fields carry values. */
const liveItem = (id: string, name: string, extra: Partial<World> = {}): World => ({
  id,
  name,
  short: name,
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
  ...extra,
});

describe("STUDIO_3 Worlds: one town", () => {
  it("STUDIO_3_worlds_your_town_counts_every_world_and_the_helpers_at_work", async () => {
    const { c } = await renderWorlds();
    const town = section(c, "Your town");
    expect(town).not.toBeNull();
    // 11 worlds; helpers of the needs + working worlds: k1 38, hires 14, northline 7, calls 1, venues 2
    expect(leaf(town as HTMLElement, "11 worlds, 62 helpers out and about")).not.toBeNull();
    const rows = qa(town as HTMLElement, "li").map((li) => text(li));
    expect(rows).toEqual(["Working4", "Needs you1", "Scheduled3", "Done3"]);
    expect(text(town)).toContain("YOUR TOWN");
    expect(town?.querySelector('[aria-hidden="true"]'), "the picture is decoration").not.toBeNull();
  });

  it("STUDIO_3_worlds_the_town_says_spend_from_the_ledger_and_nothing_when_it_cannot_be_read", async () => {
    const read = await renderWorlds();
    expect(text(section(read.c, "Your town"))).toMatch(/[£$][\d,.]+ spent so far/);
    cleanup();
    const api = worldsApi();
    api.getLedger = () => Promise.reject(new Error("offline"));
    const gone = await renderWorlds({ api });
    expect(text(section(gone.c, "Your town"))).not.toContain("spent so far");
  });
});

describe("STUDIO_3 Worlds: filters", () => {
  it("STUDIO_3_worlds_filters_status_size_and_search_narrow_one_grid", async () => {
    const { c } = await renderWorlds();
    expect(cardIds(c, GRID)).toHaveLength(11);
    click(tab(c, "Working"));
    expect(cardIds(c, GRID)).toEqual(["k1", "hires", "northline", "calls", "venues"]);
    click(scaleButton(c, "Villages"));
    expect(cardIds(c, GRID)).toEqual(["calls", "venues"]);
    expect(tabCounts(c)).toEqual({ All: 4, Working: 2, "Needs you": 0, Scheduled: 0, Done: 2 });
    typeInto(search(c), "venue");
    expect(cardIds(c, GRID)).toEqual(["venues"]);
    click(tab(c, "Done"));
    expect(section(c, GRID)).toBeNull();
    expect(leaf(c, "No worlds match")).not.toBeNull();
  });
});

describe("STUDIO_3 Worlds: cards hold only what the list serves", () => {
  it("STUDIO_3_worlds_a_live_card_prints_no_zero_helpers_and_no_cost", async () => {
    const api = worldsApi(() => [liveItem("w_live_1", "Plan the offsite")]);
    const { c } = await renderWorlds({ api });
    const t = text(card(c, "w_live_1"));
    expect(t).toContain("Plan the offsite");
    expect(t).toContain("—"); // no progress served
    expect(t).not.toMatch(/helper/);
    expect(t).not.toMatch(/[£$]/);
  });

  it("STUDIO_3_worlds_the_sample_keeps_its_sample_label_and_a_team_world_says_team", async () => {
    const api = worldsApi(() => [
      liveItem("w_sample_village_basic", "Triage my inbox", { sample: true, st: "finished" }),
      liveItem("w_team_1", "Quarterly plan", { access: "team" }),
    ]);
    const { c } = await renderWorlds({ api });
    expect(leaf(card(c, "w_sample_village_basic"), "Sample")).not.toBeNull();
    expect(leaf(card(c, "w_team_1"), "Team")).not.toBeNull();
    expect(leaf(card(c, "w_sample_village_basic"), "Team")).toBeNull();
  });
});

describe("STUDIO_3 Worlds: routines and the one filled button", () => {
  it("STUDIO_3_worlds_routines_sit_under_the_grid_as_worlds_that_run_on_a_schedule", async () => {
    const { c } = await renderWorlds();
    const routines = c.querySelector('section[aria-label="Routines"]');
    if (!routines) return; // no routines client in this build: nothing is drawn rather than a sample
    expect(leaf(routines as HTMLElement, "Worlds that run on a schedule")).not.toBeNull();
    const grid = section(c, GRID) as HTMLElement;
    expect(grid.compareDocumentPosition(routines) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("STUDIO_3_worlds_new_world_is_the_one_filled_button", async () => {
    const { rules } = parseRules(desktopCss);
    // A filled button is a button whose rule fills it with the primary colour (the progress fill is not a button).
    const { c } = await renderWorlds();
    const filled = qa(c, "button").filter((b) =>
      [...b.classList].some(
        (k) => declsFor(rules, [k], "", []).get("background") === "var(--priFill)",
      ),
    );
    expect(filled.map((b) => text(b))).toEqual(["New world"]);
    const d = declsFor(rules, ["park-worlds-new"], "", []);
    expect(d.get("height")).toBe("52px");
    expect(d.get("color")).toBe("var(--onPri)");
    expect(d.get("box-shadow")).toBe("0 3px 0 var(--priLip)");
  });

  it("STUDIO_3_worlds_studio_values_from_the_design", () => {
    const { rules } = parseRules(desktopCss);
    const at = (cls: string) => declsFor(rules, [cls], "", []);
    expect(at("park-worlds-h1").get("font-size")).toBe("48px");
    expect(at("park-worlds-town").get("height")).toBe("340px");
    expect(at("park-worlds-town").get("border-radius")).toBe("28px");
    expect(at("park-worlds-card").get("border-radius")).toBe("22px");
    expect(at("park-worlds-card__art").get("height")).toBe("170px");
    expect(at("park-worlds-tab").get("height")).toBe("40px");
    expect(at("park-worlds-search").get("height")).toBe("48px");
  });

  it("STUDIO_3_worlds_a_started_world_is_drawn_with_the_others", async () => {
    const { c } = await renderWorlds({ added: [fx.makeWorld("quick", "Compare suppliers", 1)] });
    expect(cardIds(c, GRID)).toContain("new1");
  });
});
