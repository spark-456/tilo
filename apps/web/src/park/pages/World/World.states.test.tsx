// @vitest-environment happy-dom
// WEB-6 acceptance: where the World page gets its data and what it shows when there is none (plan sections 6
// and 10: "Read data only through the Api via useParkApi(); render an EmptyState 'World data is unavailable' on
// NotBuilt"; "Fixtures never pass as live"; "No scenario-specific code"). The page reads the worlds, the plans
// (its art), the decisions, the skills and the connectors, and nothing else; it never calls fetch itself.
// The scenario's words (which world a decision belongs to, the K1 hero tag, the spend note) are DATA: the
// generic rules are pinned here by moving them to another world through the Api.
// Pinned additive fixture fields (the builder adds them, see the WEB-6 report):
//   World.heroTag?: string                      (K1: "Level 3 of 6 · Prototypes and suppliers")
//   DecisionFacts.spendNote?: { waiting: string; decided: string }   (on `depot`)
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../../test-support/park/componentsHarness";
import { ALL, DECISIONS, HIRES, K1, SAMPLE_ONLY } from "../../../../test-support/park/worldCopy";
import {
  type SpiedApi,
  climb,
  control,
  elWithText,
  hasControl,
  mountWorld,
  pageText,
  pendingApi,
  spiedApi,
  textOf,
} from "../../../../test-support/park/worldHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import { createLiveApi } from "../../api/liveApi";
import type { ApiResult, Decision, DecisionFacts, World } from "../../api/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const rewrite = <T,>(r: ApiResult<T>, data: T): ApiResult<T> => ({ ...r, data });

/** The fixture Api whose decisions are changed by `f` (a copy is changed, never the shared fixture). */
function withDecisions(f: (d: Decision[]) => Decision[]): Api {
  const base = createFixtureApi();
  return {
    ...base,
    getDecisions: async () => {
      const r = await base.getDecisions();
      return rewrite(r, f(r.data));
    },
  };
}
function withWorlds(f: (w: World[]) => World[]): Api {
  const base = createFixtureApi();
  return {
    ...base,
    getWorlds: async (...a: Parameters<Api["getWorlds"]>) => {
      const r = await base.getWorlds(...a);
      return rewrite(r, f(r.data));
    },
  };
}

describe("WEB_6_world_states: the data comes through the Api", () => {
  it("WEB_6_world_states_reads_worlds_plans_decisions_skills_and_connectors", async () => {
    const api = spiedApi();
    await mountWorld({ api, dec: { depot: true }, added: [] });
    for (const call of [
      api.getWorlds,
      api.getPlans,
      api.getDecisions,
      api.getSkills,
      api.getConnectors,
    ]) {
      expect(call).toHaveBeenCalled();
    }
    expect(api.getWorlds.mock.calls.at(-1)?.[0], "worlds for the app's decisions").toEqual({
      depot: true,
    });
    expect(api.getWorlds.mock.calls.at(-1)?.[1]).toEqual([]);
    expect(api.getPlans.mock.calls.at(-1)?.[0], "plans for the app's decisions").toEqual({
      depot: true,
    });
  });

  it("WEB_6_world_states_reads_nothing_else_and_never_calls_fetch_itself", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("no network"));
    const api = spiedApi();
    const others = (
      ["getUser", "getToday", "getLedger", "getAgenda", "getTeam", "getNotifications"] as const
    ).map((m) => [m, vi.spyOn(api as unknown as Record<string, () => unknown>, m)] as const);
    await mountWorld({ api });
    expect(fetchSpy).not.toHaveBeenCalled();
    for (const [m, spy] of others) expect(spy, m).not.toHaveBeenCalled();
  });

  it("WEB_6_world_states_a_change_of_decisions_after_mount_re_reads_the_worlds_and_plans", async () => {
    const rig = await mountWorld();
    const api = rig.api as SpiedApi;
    await rig.setDec({ depot: true });
    expect(api.getWorlds.mock.calls.at(-1)?.[0]).toEqual({ depot: true });
    expect(api.getPlans.mock.calls.at(-1)?.[0]).toEqual({ depot: true });
    // the district rows are the new ones at once
    expect(pageText(rig.el)).toContain("Laptop Depot is building");
  });

  it("WEB_6_world_states_started_worlds_are_read_with_the_app_added_list", async () => {
    const { makeWorld } = await import("../../api/fixtures");
    const added = [makeWorld("quick", "Compare three suppliers", 1)];
    const api = spiedApi();
    await mountWorld({ id: "new1", api, added });
    expect(api.getWorlds.mock.calls.at(-1)?.[1]).toEqual(added);
  });

  it("WEB_6_world_states_every_name_and_number_shown_is_what_the_Api_returned", async () => {
    const api = withWorlds((ws) =>
      ws.map((w) =>
        w.id === "hires"
          ? { ...w, name: "Zed project", owner: "Zoe Fox", agents: 3, spend: "£17" }
          : w,
      ),
    );
    const { el } = await mountWorld({ id: "hires", api });
    expect(textOf(q(el, "h1"))).toBe("Zed project");
    expect(elWithText(el, "Owned by Zoe Fox · started 14 Sep · 3 agents")).toBeTruthy();
    expect(elWithText(el, "4 districts · 3 agents")).toBeTruthy();
    expect(pageText(el)).toContain("£17");
    expect(pageText(el)).not.toContain(HIRES.name);
    expect(pageText(el)).not.toContain("Alex Morgan");
  });
});

describe("WEB_6_world_states: which world opens", () => {
  it("WEB_6_world_states_an_unknown_id_is_page_not_found_never_another_world", async () => {
    // QA-DEMO-1 M2: the reference falls back to K1, which showed another job (with Approve buttons) under a stale link.
    const { el } = await mountWorld({ id: "nope" });
    expect(textOf(q(el, "h1"))).toBe("Page not found");
    expect(el.querySelector('[data-testid="park-page-world"]')).toBeNull();
  });

  it("WEB_6_world_states_no_id_in_params_falls_back_the_same_way", async () => {
    const { el } = await mountWorld({ id: null });
    expect(textOf(q(el, "h1"))).toBe(K1.name);
  });

  it("WEB_6_world_states_each_known_id_opens_its_own_world", async () => {
    for (const c of ALL) {
      const { el } = await mountWorld({ id: c.id });
      expect(textOf(q(el, "h1")), c.id).toBe(c.name);
      cleanup();
    }
  });

  it("WEB_6_world_states_the_route_id_can_change_in_the_mounted_page", async () => {
    const rig = await mountWorld();
    await rig.open("northline");
    expect(textOf(q(rig.el, "h1"))).toBe("Supplier onboarding · Northline");
    expect(qa(rig.el, 'section[aria-label="Run history"]')).toHaveLength(1);
    expect(qa(rig.el, 'section[aria-label="Districts"]')).toHaveLength(0);
    await rig.open("calls");
    expect(qa(rig.el, 'section[aria-label="Result"]')).toHaveLength(1);
    expect(qa(rig.el, 'section[aria-label="Run history"]')).toHaveLength(0);
    expect(qa(rig.el, "h1")).toHaveLength(1);
  });
});

describe("WEB_6_world_states: the scenario is data, not logic", () => {
  it("WEB_6_world_states_a_decision_shows_on_the_world_it_names_and_only_there", async () => {
    const api = withDecisions((ds) =>
      ds.map((d) => (d.k === "depot" ? { ...d, world: "hires" } : d)),
    );
    const hires = await mountWorld({ id: "hires", api });
    expect(elWithText(hires.el, "WAITING FOR YOU")).toBeTruthy();
    expect(elWithText(hires.el, "1 decision before agents continue")).toBeTruthy();
    expect(hasControl(hires.el, DECISIONS.depot.yes)).toBe(true);
    expect(hasControl(hires.el, DECISIONS.mail.yes)).toBe(false);
    cleanup();
    const k1 = await mountWorld({ id: "k1", api });
    expect(elWithText(k1.el, "1 decision before agents continue")).toBeTruthy();
    expect(hasControl(k1.el, DECISIONS.mail.yes)).toBe(true);
    expect(hasControl(k1.el, DECISIONS.depot.yes)).toBe(false);
  });

  it("WEB_6_world_states_a_decision_of_a_world_that_is_not_shown_does_not_show_anywhere", async () => {
    const api = withDecisions((ds) => ds.map((d) => ({ ...d, world: "elsewhere" })));
    const { el } = await mountWorld({ id: "k1", api });
    expect(pageText(el)).not.toContain("WAITING FOR YOU");
    expect(hasControl(el, DECISIONS.depot.yes)).toBe(false);
  });

  it("WEB_6_world_states_the_decision_texts_are_the_ones_the_Api_returned", async () => {
    const api = withDecisions((ds) =>
      ds.map((d) =>
        d.k === "depot"
          ? { ...d, title: "Title-X", body: "Body-X", yes: "Yes-X", done: "Done-X" }
          : d,
      ),
    );
    const rig = await mountWorld({ api });
    expect(elWithText(rig.el, "Title-X")).toBeTruthy();
    expect(elWithText(rig.el, "Body-X")).toBeTruthy();
    expect(hasControl(rig.el, "Yes-X")).toBe(true);
    await rig.setDec({ depot: true });
    expect(pageText(rig.el)).toContain("Done-X");
  });

  it("WEB_6_world_states_the_spend_note_follows_the_decision_facts_of_the_world", async () => {
    const note = { waiting: "WAIT-X", decided: "DONE-X" };
    const move = (ds: Decision[]) =>
      ds.map((d) =>
        d.k === "depot"
          ? {
              ...d,
              world: "hires",
              facts: { ...(d.facts as DecisionFacts), spendNote: note } as DecisionFacts,
            }
          : d,
      );
    const api = withDecisions(move);
    const hires = await mountWorld({ id: "hires", api });
    expect(pageText(hires.el)).toContain("WAIT-X");
    await hires.setDec({ depot: true });
    expect(pageText(hires.el)).toContain("DONE-X");
    expect(pageText(hires.el)).not.toContain("WAIT-X");
    cleanup();
    // K1 no longer owns that decision: its note is the generic budget line
    const k1 = await mountWorld({ id: "k1", api });
    expect(elWithText(k1.el, "35% of budget used. Forecast within budget.")).toBeTruthy();
    expect(pageText(k1.el)).not.toContain("WAIT-X");
  });

  it("WEB_6_world_states_without_any_spend_note_the_budget_line_is_computed_from_the_numbers", async () => {
    const api = withDecisions((ds) =>
      ds.map((d) => ({
        ...d,
        facts: { ...(d.facts as DecisionFacts), spendNote: undefined } as unknown as DecisionFacts,
      })),
    );
    const { el } = await mountWorld({ id: "k1", api });
    expect(elWithText(el, "35% of budget used. Forecast within budget.")).toBeTruthy();
  });

  it("WEB_6_world_states_the_hero_tag_is_a_field_of_the_world_else_derived_from_its_tier", async () => {
    const api = withWorlds((ws) =>
      ws.map((w) => {
        if (w.id === "hires") return { ...w, heroTag: "Tag-X" } as World;
        if (w.id === "k1") return { ...w, heroTag: undefined } as unknown as World;
        return w;
      }),
    );
    const hires = await mountWorld({ id: "hires", api });
    expect(elWithText(hires.el, "Tag-X")).toBeTruthy();
    expect(pageText(hires.el)).not.toContain(HIRES.heroTag);
    cleanup();
    const k1 = await mountWorld({ id: "k1", api });
    expect(
      elWithText(k1.el, "5 districts · 38 agents"),
      "City default: districts and agents",
    ).toBeTruthy();
    expect(pageText(k1.el)).not.toContain(K1.heroTag);
  });

  it("WEB_6_world_states_skills_and_tools_come_from_the_Api_skills_and_connectors", async () => {
    const base = createFixtureApi();
    const api: Api = {
      ...base,
      getSkills: async () => {
        const r = await base.getSkills();
        return rewrite(
          r,
          r.data.map((s) =>
            s.id === "fw"
              ? { ...s, name: "Skill-X", tools: [["Slack", 1]] as [string, number][] }
              : { ...s, used: s.used.filter((u) => u !== "k1") },
          ),
        );
      },
      getConnectors: async () => {
        const r = await base.getConnectors();
        return rewrite(
          r,
          r.data.map((c) => (c.name === "Slack" ? { ...c, mono: "Q" } : c)),
        );
      },
    };
    const { el } = await mountWorld({ api });
    const card = climb(elWithText(el, "Owner"), (n) => textOf(n).includes("Tools"));
    expect(hasControl(card, "Skill-X")).toBe(true);
    expect(hasControl(card, "Draft a supplier brief")).toBe(false);
    expect(textOf(card)).toContain("QSlack");
    expect(textOf(card)).not.toContain("Google Drive");
  });

  it("WEB_6_world_states_a_world_used_by_no_skill_says_so_and_lists_Gmail_and_Google_Drive", async () => {
    const { el } = await mountWorld({ id: "venues" });
    const card = climb(elWithText(el, "Owner"), (n) => textOf(n).includes("Tools"));
    expect(textOf(card)).toContain("Uses Tilo’s general skills");
    expect(control(card, "GGmail")).toBeTruthy();
    expect(control(card, "DGoogle Drive")).toBeTruthy();
  });
});

describe("WEB_6_world_states: loading and not built", () => {
  it("WEB_6_world_states_while_loading_no_sample_value_shows", async () => {
    const { el } = await mountWorld({ api: pendingApi() });
    // The page root is there from the first render (the shell's tests look for it); only the data waits.
    expect(qa(el, '[data-testid="park-page-world"]')).toHaveLength(1);
    const text = pageText(el);
    for (const sample of SAMPLE_ONLY) expect(text, sample).not.toContain(sample);
    expect(text).not.toContain("World data is unavailable");
    expect(qa(el, "h1").length).toBeLessThanOrEqual(1);
    expect(qa(el, "main")).toHaveLength(0);
  });

  it("WEB_6_world_states_a_live_Api_that_is_not_built_shows_Not_connected_yet", async () => {
    const { el } = await mountWorld({ api: createLiveApi() });
    const text = pageText(el);
    expect(text).toContain("World data is unavailable");
    for (const sample of SAMPLE_ONLY) expect(text, sample).not.toContain(sample);
    expect(qa(el, '[data-testid="park-page-world"]')).toHaveLength(1);
    expect(qa(el, "h1").length).toBeLessThanOrEqual(1);
  });

  it("WEB_6_world_states_when_getWorlds_is_not_built_the_page_says_Not_connected_yet_and_shows_no_sample_value", async () => {
    const base = createFixtureApi();
    const { el } = await mountWorld({ api: { ...base, getWorlds: createLiveApi().getWorlds } });
    const text = pageText(el);
    expect(text).toContain("World data is unavailable");
    for (const sample of SAMPLE_ONLY) expect(text, sample).not.toContain(sample);
  });

  // LIVE-HOME: the world itself comes from the worlds; a side read that is not built or fails leaves a gap in its
  // own card, which says so, and the page still opens.
  it.each([
    ["getPlans", "City map: Not available yet"],
    ["getDecisions", "Waiting on you"],
    ["getSkills", "Skills"],
    ["getConnectors", "Tools"],
  ] as const)(
    "WEB_6_world_states_when_%s_is_not_built_only_its_card_says_Not_available_yet",
    async (method, title) => {
      const base = createFixtureApi();
      const live = createLiveApi();
      const { el } = await mountWorld({ api: { ...base, [method]: live[method] } as Api });
      const text = pageText(el);
      expect(text).not.toContain("World data is unavailable");
      expect(text).toContain("Not available yet");
      expect(text).toContain(title);
      expect(text).not.toMatch(/NotBuilt|not_built|getPlans|getDecisions|getSkills|getConnectors/);
      expect(qa(el, "h1")).toHaveLength(1);
    },
  );

  it("WEB_6_world_states_not_built_does_not_leak_the_error_or_the_method_name", async () => {
    const { el } = await mountWorld({ api: createLiveApi() });
    const text = pageText(el);
    expect(text).not.toMatch(
      /NotBuilt|not_built|getWorlds|getPlans|getDecisions|getSkills|getConnectors/,
    );
    expect(text).not.toContain("undefined");
  });

  it("WEB_6_world_states_an_Api_that_rejects_with_any_error_never_puts_its_message_on_screen", async () => {
    const base = createFixtureApi();
    const boom = () => Promise.reject(new Error("offline-7f3"));
    const { el } = await mountWorld({ api: { ...base, getWorlds: boom, getSkills: boom } });
    expect(el.isConnected).toBe(true);
    expect(pageText(el)).not.toContain("offline-7f3");
    expect(pageText(el)).toContain("World data is unavailable");
  });

  it("WEB_6_world_states_no_console_error_or_warning_for_any_world_loading_or_not_built", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    for (const c of ALL) {
      await mountWorld({ id: c.id });
      cleanup();
    }
    await mountWorld({ api: pendingApi() });
    cleanup();
    await mountWorld({ api: createLiveApi() });
    cleanup();
    await mountWorld({ id: "nope" });
    expect(error.mock.calls).toEqual([]);
    expect(warn.mock.calls).toEqual([]);
  });
});
