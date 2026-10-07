// @vitest-environment happy-dom
// WEB-6 acceptance: what the controls of the World page do. Pinned to the reference
// (design_handoff_tilo_web_app/design/Tilo App World.dc.html: togglePause, share, runNow, goAgenda, openOut,
// sendSlack, goLedger, the decision cards' approve and later, the skill and tool chips, the breadcrumb) and to
// README "Interactions and motion" ("Approve: decide(key) -> toast with Undo; everything bound to dec updates
// at once": the toast belongs to the store, so the page calls `app.decide(key)` and nothing else).
// Links that stay in the Park app are real addresses whose plain click goes through `app.go` (as Home's
// GoLink); a modified or non-primary click is the browser's. The links to the stage (S-04) and its lenses
// (S-05, S-10, S-11, S-12) leave the Park app: they are real hrefs, and the page never calls `app.go` for them
// (park/ may not import src/router, WEB_1a static; the browser follows the address).
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, qa } from "../../../../test-support/park/componentsHarness";
import { DECISIONS, K1, TOASTS } from "../../../../test-support/park/worldCopy";
import {
  MODIFIED,
  type SpiedApi,
  breadcrumb,
  clickEl,
  climb,
  control,
  controlFlat,
  controls,
  decideCalls,
  elWithText,
  goCalls,
  hasControl,
  lastGo,
  mapBlock,
  mountWorld,
  pageText,
  region,
  settle,
  stubClipboard,
  textOf,
  toastCalls,
} from "../../../../test-support/park/worldHarness";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
});

const waiting = (el: HTMLElement) =>
  climb(elWithText(el, "WAITING FOR YOU"), (n) => textOf(n).includes("Ask me later"));
const cardOf = (el: HTMLElement, title: string) =>
  climb(
    elWithText(el, title),
    (n) => textOf(n).includes("Ask me later") || textOf(n).includes("just now"),
  );

describe("WEB_6_world_interactions: Approve and Ask me later", () => {
  it("WEB_6_world_interactions_Approve_calls_app_decide_with_the_key_and_nothing_else", async () => {
    const rig = await mountWorld();
    click(control(rig.el, DECISIONS.depot.yes));
    expect(decideCalls(rig.app)).toEqual([["depot"]]);
    click(control(rig.el, DECISIONS.mail.yes));
    expect(decideCalls(rig.app)).toEqual([["depot"], ["mail"]]);
    // the toast with Undo is the store's; the page adds none, and makes no write of its own
    expect(toastCalls(rig.app)).toEqual([]);
    const api = rig.api as SpiedApi;
    expect(api.decide).not.toHaveBeenCalled();
    expect(api.undo).not.toHaveBeenCalled();
    expect(goCalls(rig.app)).toBe(0);
  });

  it("WEB_6_world_interactions_the_page_keeps_no_copy_of_the_decision_it_follows_app_dec", async () => {
    const rig = await mountWorld();
    click(control(rig.el, DECISIONS.depot.yes));
    // `decide` of the stub does not change `dec`: nothing is shown as approved until the store says so
    expect(hasControl(rig.el, DECISIONS.depot.yes)).toBe(true);
    expect(pageText(rig.el)).not.toContain(DECISIONS.depot.done);
  });

  it("WEB_6_world_interactions_an_approved_decision_shows_its_done_line_and_loses_its_buttons", async () => {
    const rig = await mountWorld();
    await rig.setDec({ depot: true });
    const depot = cardOf(rig.el, DECISIONS.depot.title);
    expect(textOf(depot)).toContain(DECISIONS.depot.body);
    expect(textOf(depot)).toContain(DECISIONS.depot.done);
    expect(depot.querySelector("svg"), "the check icon before the done line").not.toBeNull();
    expect(hasControl(rig.el, DECISIONS.depot.yes)).toBe(false);
    // the other decision is untouched
    expect(hasControl(rig.el, DECISIONS.mail.yes)).toBe(true);
    expect(controls(rig.el).filter((e) => textOf(e) === "Ask me later")).toHaveLength(1);
    expect(elWithText(rig.el, "1 decision before agents continue")).toBeTruthy();
    expect(elWithText(rig.el, "1 decision"), "the status chip").toBeTruthy();
  });

  it("WEB_6_world_interactions_both_taken_removes_the_card_and_Undo_brings_it_back", async () => {
    const rig = await mountWorld();
    await rig.setDec({ depot: true, mail: true });
    expect(pageText(rig.el)).not.toContain("WAITING FOR YOU");
    expect(elWithText(rig.el, "Running")).toBeTruthy();
    await rig.setDec({ mail: true }); // Undo on the toast
    expect(elWithText(rig.el, "WAITING FOR YOU")).toBeTruthy();
    expect(hasControl(rig.el, DECISIONS.depot.yes)).toBe(true);
    expect(textOf(waiting(rig.el))).toContain(DECISIONS.mail.done);
    expect(elWithText(rig.el, "1 decision before agents continue")).toBeTruthy();
  });

  it("WEB_6_world_interactions_Ask_me_later_toasts_16_00_and_decides_nothing", async () => {
    const rig = await mountWorld();
    const later = controls(rig.el).filter((e) => textOf(e) === "Ask me later");
    click(later[0] as HTMLElement);
    expect(toastCalls(rig.app)).toEqual([[TOASTS.later]]);
    click(later[1] as HTMLElement);
    expect(toastCalls(rig.app)).toEqual([[TOASTS.later], [TOASTS.later]]);
    expect(decideCalls(rig.app)).toEqual([]);
    expect(goCalls(rig.app)).toBe(0);
    expect(hasControl(rig.el, DECISIONS.depot.yes)).toBe(true); // the card is unchanged
  });

  it("WEB_6_world_interactions_the_approvals_are_real_buttons_in_the_decision_cards", async () => {
    const { el } = await mountWorld();
    for (const d of Object.values(DECISIONS)) {
      const yes = control(el, d.yes);
      expect(yes.tagName).toBe("BUTTON");
      expect(yes.getAttribute("type")).toBe("button");
      expect(cardOf(el, d.title).contains(yes)).toBe(true);
    }
  });
});

describe("WEB_6_world_interactions: Pause and Resume", () => {
  it("WEB_6_world_interactions_Pause_toasts_shows_the_overlay_the_chip_and_turns_into_Resume", async () => {
    const rig = await mountWorld();
    click(control(rig.el, "Pause"));
    expect(toastCalls(rig.app)).toEqual([[TOASTS.paused]]);
    expect(hasControl(rig.el, "Pause")).toBe(false);
    expect(hasControl(rig.el, "Resume")).toBe(true);
    const overlay = elWithText(rig.el, "Paused · agents are waiting");
    expect(overlay, "the overlay on the map").toBeTruthy();
    expect(mapBlock(rig.el, K1.heroTag).contains(overlay ?? null)).toBe(true);
    expect(
      overlay?.querySelector("svg") ?? overlay?.parentElement?.querySelector("svg"),
    ).not.toBeNull();
    expect(elWithText(rig.el, "Paused"), "the status chip").toBeTruthy();
    expect(elWithText(rig.el, "2 decisions"), "replaced by Paused while paused").toBeUndefined();
    // the world's decisions are still there to take
    expect(hasControl(rig.el, DECISIONS.depot.yes)).toBe(true);
    expect(decideCalls(rig.app)).toEqual([]);
  });

  it("WEB_6_world_interactions_Resume_toasts_and_puts_everything_back", async () => {
    const rig = await mountWorld();
    click(control(rig.el, "Pause"));
    click(control(rig.el, "Resume"));
    expect(toastCalls(rig.app)).toEqual([[TOASTS.paused], [TOASTS.resumed]]);
    expect(hasControl(rig.el, "Pause")).toBe(true);
    expect(hasControl(rig.el, "Resume")).toBe(false);
    expect(pageText(rig.el)).not.toContain("Paused · agents are waiting");
    expect(elWithText(rig.el, "2 decisions")).toBeTruthy();
  });

  it("WEB_6_world_interactions_a_running_world_shows_Paused_then_Running_again", async () => {
    const rig = await mountWorld({ id: "calls" });
    expect(elWithText(rig.el, "Running")).toBeTruthy();
    click(control(rig.el, "Pause"));
    expect(elWithText(rig.el, "Paused")).toBeTruthy();
    expect(elWithText(rig.el, "Running")).toBeUndefined();
    click(control(rig.el, "Resume"));
    expect(elWithText(rig.el, "Running")).toBeTruthy();
  });

  it("WEB_6_world_interactions_the_paused_state_is_per_world_in_one_mounted_page", async () => {
    // Reference: state.paused is a map keyed by the world id.
    const rig = await mountWorld();
    click(control(rig.el, "Pause"));
    await rig.open("hires");
    expect(hasControl(rig.el, "Pause"), "another world is not paused").toBe(true);
    expect(pageText(rig.el)).not.toContain("Paused · agents are waiting");
    await rig.open("k1");
    expect(hasControl(rig.el, "Resume"), "the first world is still paused").toBe(true);
  });

  it("WEB_6_world_interactions_Pause_and_Share_are_real_buttons_with_an_icon", async () => {
    const { el } = await mountWorld();
    for (const label of ["Pause", "Share"]) {
      const b = control(el, label);
      expect(b.tagName).toBe("BUTTON");
      expect(b.getAttribute("type")).toBe("button");
      expect(b.querySelector("svg"), `${label} icon`).not.toBeNull();
    }
  });

  it("WEB_6_world_interactions_pausing_writes_nothing_to_the_Api", async () => {
    const rig = await mountWorld();
    click(control(rig.el, "Pause"));
    const api = rig.api as SpiedApi;
    for (const w of [api.decide, api.undo, api.startWorld, api.setPref]) {
      expect(w).not.toHaveBeenCalled();
    }
  });
});

describe("WEB_6_world_interactions: Share", () => {
  it("WEB_6_world_interactions_Share_copies_the_address_and_toasts", async () => {
    window.history.pushState({}, "", "/park/world/k1");
    const write = vi.fn().mockResolvedValue(undefined);
    const restore = stubClipboard(write);
    try {
      const rig = await mountWorld();
      click(control(rig.el, "Share"));
      expect(write).toHaveBeenCalledTimes(1);
      expect(write).toHaveBeenCalledWith(window.location.href);
      expect(toastCalls(rig.app)).toEqual([[TOASTS.shared]]);
      expect(goCalls(rig.app)).toBe(0);
    } finally {
      restore();
    }
  });

  it("WEB_6_world_interactions_Share_still_toasts_when_the_clipboard_throws_or_is_missing", async () => {
    const throwing = vi.fn(() => {
      throw new Error("denied");
    });
    const restore = stubClipboard(throwing);
    try {
      const rig = await mountWorld();
      click(control(rig.el, "Share"));
      expect(toastCalls(rig.app)).toEqual([[TOASTS.shared]]);
    } finally {
      restore();
    }
    cleanup();
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    try {
      const rig = await mountWorld();
      click(control(rig.el, "Share"));
      expect(toastCalls(rig.app)).toEqual([[TOASTS.shared]]);
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
    }
  });

  it("WEB_6_world_interactions_a_rejected_copy_is_not_an_unhandled_rejection", async () => {
    const unhandled = vi.fn();
    process.on("unhandledRejection", unhandled);
    const restore = stubClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    try {
      const rig = await mountWorld();
      click(control(rig.el, "Share"));
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
      expect(unhandled).not.toHaveBeenCalled();
      expect(toastCalls(rig.app)).toEqual([[TOASTS.shared]]);
    } finally {
      process.off("unhandledRejection", unhandled);
      restore();
    }
  });
});

describe("WEB_6_world_interactions: Town and Village buttons", () => {
  it("WEB_6_world_interactions_Run_now_toasts_the_notification_line", async () => {
    const rig = await mountWorld({ id: "invoice" });
    click(control(rig.el, "Run now"));
    expect(toastCalls(rig.app)).toEqual([[TOASTS.run]]);
    expect(goCalls(rig.app)).toBe(0);
    const api = rig.api as SpiedApi;
    expect(api.startWorld).not.toHaveBeenCalled();
  });

  it("WEB_6_world_interactions_See_in_Agenda_goes_to_the_agenda_page", async () => {
    const rig = await mountWorld({ id: "invoice" });
    click(control(rig.el, "See in Agenda"));
    expect(lastGo(rig.app)).toEqual(["agenda", undefined]);
    expect(goCalls(rig.app)).toBe(1);
  });

  it("WEB_6_world_interactions_Open_result_and_Share_to_Slack_toast_their_lines", async () => {
    const rig = await mountWorld({ id: "comp" });
    click(control(rig.el, "Open result"));
    expect(toastCalls(rig.app)).toEqual([[TOASTS.open]]);
    click(control(rig.el, "Share to Slack"));
    expect(toastCalls(rig.app)).toEqual([[TOASTS.open], [TOASTS.slack]]);
    expect(goCalls(rig.app)).toBe(0);
  });
});

describe("WEB_6_world_interactions: links that stay in the Park app", () => {
  it("WEB_6_world_interactions_the_breadcrumb_Worlds_link_goes_to_worlds", async () => {
    const rig = await mountWorld();
    const link = control(breadcrumb(rig.el), "Worlds");
    expect(link.tagName).toBe("A");
    expect(clickEl(link)).toBe(false); // a plain click is handled in the page
    expect(lastGo(rig.app)).toEqual(["worlds", undefined]);
    expect(goCalls(rig.app)).toBe(1);
  });

  it("WEB_6_world_interactions_the_Spend_card_Ledger_link_goes_to_the_ledger", async () => {
    const rig = await mountWorld();
    const link = controlFlat(
      climb(elWithText(rig.el, "Spend"), (n) => textOf(n).includes("Ledger")),
      "Ledger",
    );
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBeTruthy();
    expect(clickEl(link)).toBe(false);
    expect(lastGo(rig.app)).toEqual(["ledger", undefined]);
  });

  it.each(MODIFIED)(
    "WEB_6_world_interactions_%s_click_on_a_link_is_left_to_the_browser",
    async (_n, init) => {
      const rig = await mountWorld();
      for (const link of [
        control(breadcrumb(rig.el), "Worlds"),
        control(
          climb(elWithText(rig.el, "Spend"), (n) => textOf(n).includes("Ledger")),
          "Ledger",
        ),
      ]) {
        expect(clickEl(link, init), textOf(link)).toBe(true);
      }
      expect(goCalls(rig.app)).toBe(0);
    },
  );

  it("WEB_6_world_interactions_a_skill_chip_opens_that_skill", async () => {
    const rig = await mountWorld();
    const facts = climb(elWithText(rig.el, "Owner"), (n) => textOf(n).includes("Tools"));
    click(control(facts, "Draft a supplier brief"));
    expect(lastGo(rig.app)).toEqual(["skills", { id: "brief" }]);
    click(control(facts, "Check firmware test results"));
    expect(lastGo(rig.app)).toEqual(["skills", { id: "fw" }]);
    expect(goCalls(rig.app)).toBe(2);
  });

  it("WEB_6_world_interactions_a_tool_chip_opens_connectors", async () => {
    const rig = await mountWorld();
    const facts = climb(elWithText(rig.el, "Owner"), (n) => textOf(n).includes("Tools"));
    for (const [m, n] of K1.tools) click(controlFlat(facts, `${m}${n}`));
    expect(goCalls(rig.app)).toBe(K1.tools.length);
    expect(lastGo(rig.app)).toEqual(["connectors", undefined]);
  });

  it("WEB_6_world_interactions_the_chips_are_buttons_with_an_icon_for_skills_and_a_monogram_for_tools", async () => {
    const { el } = await mountWorld();
    const facts = climb(elWithText(el, "Owner"), (n) => textOf(n).includes("Tools"));
    const skill = control(facts, "Draft a supplier brief");
    expect(skill.tagName).toBe("BUTTON");
    expect(skill.querySelector("svg"), "the bolt").not.toBeNull();
    const tool = controlFlat(facts, "DGoogle Drive");
    expect(tool.tagName).toBe("BUTTON");
    expect(tool.firstElementChild && textOf(tool.firstElementChild)).toBe("D");
  });
});

describe("WEB_6_world_interactions: the live stage and its lenses (plan question A)", () => {
  const stageLinks = (el: HTMLElement) => qa<HTMLAnchorElement>(el, 'a[href^="/world/"]');

  it("WEB_6_world_interactions_a_City_opens_the_live_view_S_04_as_a_real_link", async () => {
    const { el } = await mountWorld();
    const live = control(el, "Open live view");
    expect(live.tagName).toBe("A");
    expect(live.getAttribute("href")).toBe("/world/k1/stage");
    expect(live.querySelector("svg"), "the play icon").not.toBeNull();
  });

  it("WEB_6_world_interactions_the_lenses_Story_Trace_Delivery_and_Inspect_are_linked_for_a_City", async () => {
    // S-04 /world/:id/stage (WEB-CUTOVER), S-10 /world/:id/story, S-11 /trace, S-12 /delivery, S-05 /world/:id/inspect/:building (screens/meta.ts).
    const { el } = await mountWorld();
    const hrefs = stageLinks(el).map((a) => a.getAttribute("href"));
    for (const want of [
      "/world/k1/stage",
      "/world/k1/story",
      "/world/k1/trace",
      "/world/k1/delivery",
    ]) {
      expect(hrefs, want).toContain(want);
    }
    expect(
      hrefs.some((h) => /^\/world\/k1\/inspect\/[^/]+$/.test(h ?? "")),
      "an Inspect link to a building",
    ).toBe(true);
    for (const a of stageLinks(el)) {
      expect(textOf(a) || a.getAttribute("aria-label"), a.getAttribute("href") ?? "").toBeTruthy();
    }
  });

  it("WEB_6_world_interactions_the_links_use_the_second_city_id", async () => {
    const { el } = await mountWorld({ id: "hires" });
    expect(control(el, "Open live view").getAttribute("href")).toBe("/world/hires/stage");
    const hrefs = stageLinks(el).map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("/world/hires/story");
    expect(hrefs.some((h) => h?.startsWith("/world/k1"))).toBe(false);
  });

  it("WEB_6_world_interactions_a_Town_and_a_Village_have_no_live_view", async () => {
    for (const id of ["northline", "invoice", "calls", "comp"]) {
      const { el } = await mountWorld({ id });
      expect(pageText(el), id).not.toContain("Open live view");
      expect(
        stageLinks(el).map((a) => a.getAttribute("href")),
        id,
      ).not.toContain(`/world/${id}/stage`);
      cleanup();
    }
  });

  it("WEB_6_world_interactions_the_stage_links_never_go_through_app_go", async () => {
    const rig = await mountWorld();
    for (const a of qa<HTMLAnchorElement>(rig.el, 'a[href^="/world/"]')) {
      clickEl(a);
      clickEl(a, { ctrlKey: true });
    }
    expect(goCalls(rig.app)).toBe(0);
  });

  it("WEB_6_world_interactions_a_modified_click_on_the_live_view_is_not_cancelled", async () => {
    const rig = await mountWorld();
    const live = control(rig.el, "Open live view");
    for (const [name, init] of MODIFIED) expect(clickEl(live, init), name).toBe(true);
  });

  it("WEB_6_world_interactions_the_world_id_is_encoded_in_the_address", async () => {
    // A world id is data: it can hold a space or a slash, and must not change the path it is put in.
    const { createFixtureApi } = await import("../../api/fixtureApi");
    const base = createFixtureApi();
    const odd = {
      ...base,
      getWorlds: async (...a: Parameters<typeof base.getWorlds>) => {
        const r = await base.getWorlds(...a);
        return { ...r, data: r.data.map((w) => (w.id === "hires" ? { ...w, id: "q 1/2" } : w)) };
      },
    };
    const { el } = await mountWorld({ id: "q 1/2", api: odd });
    expect(control(el, "Open live view").getAttribute("href")).toBe("/world/q%201%2F2/stage");
    await settle();
  });
});

describe("WEB_6_world_interactions: nothing happens by itself", () => {
  it("WEB_6_world_interactions_mounting_toasts_navigates_and_decides_nothing", async () => {
    const rig = await mountWorld();
    expect(toastCalls(rig.app)).toEqual([]);
    expect(goCalls(rig.app)).toBe(0);
    expect(decideCalls(rig.app)).toEqual([]);
    expect(rig.sch.timers, "no timer: the page has none of its own").toEqual([]);
    expect(region(rig.el, "Activity")).toBeTruthy();
  });
});
