// @vitest-environment happy-dom
// WEB-7 Ledger page: exact copy (inventory.md "Tilo App Ledger"), the interactions of the reference
// (Tilo App Ledger.dc.html) and the decide() effects, rendered on the fixture Api in happy-dom.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  click,
  countPrimary,
  q,
  qa,
} from "../../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import { NotBuilt } from "../../api/liveApi";
import { renderLedger, settle } from "./ledgerHarness";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const text = (root: ParentNode) => (root as HTMLElement).textContent ?? "";
const byText = <T extends Element>(root: ParentNode, sel: string, t: string): T => {
  const el = qa<T>(root, sel).find((e) => (e.textContent ?? "").trim() === t);
  if (!el) throw new Error(`no ${sel} with text "${t}"`);
  return el;
};
const rowWith = (root: ParentNode, t: string): HTMLElement => {
  const el = qa<HTMLElement>(root, "button[aria-expanded]").find((e) =>
    (e.textContent ?? "").includes(t),
  );
  if (!el) throw new Error(`no activity row with ${t}`);
  return el;
};
const region = (root: ParentNode, name: string) => q(root, `section[aria-label="${name}"]`);

describe("WEB_7_ledger_copy: the designed text, verbatim", () => {
  it("WEB_7_ledger_header_and_kpis", async () => {
    const { container } = await renderLedger();
    const t = text(container);
    expect(q(container, "h1").textContent).toBe("Ledger");
    for (const s of [
      "Every cost and every decision your agents make. September 2026 · 6 days left · budget £8,000.",
      "September 2026",
      "Export CSV",
      "Spent so far",
      "£2,412",
      "30% of £8,000",
      "Month-end forecast",
      "£6,300",
      "£1,700 under budget",
      "Waiting on you",
      "£3,420",
      "Laptop Depot sign-off",
      "Saved by memory",
      "£640",
      "Up £120 on August",
      "Hours handed back",
      "46 h",
      "About 6 working days",
    ])
      expect(t, s).toContain(s);
  });

  it("WEB_7_ledger_regions_and_static_copy", async () => {
    const { container } = await renderLedger();
    for (const name of [
      "Spend over the month",
      "Where it goes",
      "Cost per run",
      "Approval wait times",
      "What Tilo gave back",
      "Activity",
    ])
      region(container, name);
    q(container, '[role="radiogroup"][aria-label="Group by"]');
    q(container, '[role="radiogroup"][aria-label="Entry type"]');
    const t = text(container);
    for (const s of [
      "SPEND OVER TIME",
      "On track to finish £1,700 under budget",
      "Running total for September. Hover for daily spend.",
      "Spent",
      "Forecast",
      "Even pace",
      "Budget £8,000",
      "Motor dev kit £1,140",
      "If you approve £3,420",
      "WHERE IT GOES",
      "K1 electric scooter is 57% of this month",
      "Total",
      "COST PER RUN",
      "Repeat work gets cheaper. Invoice matching now costs 79% less.",
      "APPROVAL WAIT TIMES",
      "Most asks get a yes in 9 minutes. Sharing outside waits longest.",
      "Jin approves all outside sharing. A backup approver would cut the wait.",
      "Add a backup",
      "WHAT TILO GAVE BACK",
      "£640 saved by memory and 46 hours handed back to people",
      "Saved by memory, per week",
      "1–7 Sep",
      "8–14",
      "15–21",
      "22–24",
      "Hours handed back, by team",
      "Finance · 19 h",
      "Invoice matching and audit prep",
      "Today · Thu 24 Sep",
      "Waiting · 2",
    ])
      expect(t, s).toContain(s);
    expect(countPrimary(container), "UX-1: no filled primary on the Ledger").toBe(0);
  });
});

describe("WEB_7_ledger_interactions", () => {
  it("WEB_7_ledger_waiting_kpi_opens_k1_and_header_buttons_toast", async () => {
    const { container, calls } = await renderLedger();
    click(byText(container, "button", "Waiting on you£3,420Laptop Depot sign-off"));
    expect(calls.go).toHaveBeenCalledWith("world", { id: "k1" });
    click(byText(container, "button", "September 2026"));
    expect(calls.toast).toHaveBeenCalledWith(
      "August and earlier months live here",
      undefined,
      undefined,
    );
    click(byText(container, "button", "Export CSV"));
    expect(calls.toast).toHaveBeenCalledWith(
      "Exported september-2026.csv · also synced to Xero",
      undefined,
      undefined,
    );
  });

  it("WEB_7_ledger_chart_hover_shows_the_day_and_leaves", async () => {
    const { container } = await renderLedger();
    const box = q(region(container, "Spend over the month"), "[data-chart]");
    vi.spyOn(box, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      right: 720,
      bottom: 270,
      width: 720,
      height: 270,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    const tip = q(box, "[data-tip]");
    expect(tip.style.opacity).toBe("0");
    const { act } = await import("react");
    act(() => {
      box.dispatchEvent(
        new MouseEvent("mousemove", { bubbles: true, clientX: 48 + 23 * (652 / 29) }),
      );
    });
    expect(tip.style.opacity).toBe("1");
    expect(tip.textContent).toBe("Thu 24 Sep · £31Running total £2,412");
    act(() => {
      box.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true }));
    });
    expect(tip.style.opacity).toBe("0");
  });

  it("WEB_7_ledger_group_by_switches_head_legend_and_donut", async () => {
    const { container } = await renderLedger();
    const where = region(container, "Where it goes");
    const donut = q(where, "[data-donut]");
    const before = donut.style.background;
    expect(text(where)).toContain("K1 electric scooter");
    expect(text(where)).toContain("£1,386 · 57%");
    click(byText(where, '[role="radio"]', "Tool"));
    expect(text(where)).toContain("Workspaces carry most of the spend");
    expect(text(where)).toContain("£1,956 · 81%");
    expect(q(where, "[data-donut]").style.background).not.toBe(before);
    click(byText(where, '[role="radio"]', "Agent"));
    expect(text(where)).toContain("Builders spend most, mainly on parts");
    expect(qa(where, "[data-legend-row]")).toHaveLength(6);
  });

  it("WEB_7_ledger_cost_cards_open_the_skill", async () => {
    const { container, calls } = await renderLedger();
    const cards = qa(region(container, "Cost per run"), "button");
    expect(cards).toHaveLength(4);
    expect(text(cards[0] as HTMLElement)).toBe("Match invoices to POs−79%£2.80 run 1£0.60 run 142");
    click(cards[0] as HTMLElement);
    expect(calls.go).toHaveBeenCalledWith("skills", { id: "invoice" });
  });

  it("WEB_7_ledger_add_a_backup_goes_to_team_and_prefs_backup_changes_the_wait", async () => {
    const first = await renderLedger();
    click(byText(first.container, "button", "Add a backup"));
    expect(first.calls.go).toHaveBeenCalledWith("team", { focus: "share" });
    expect(text(first.container)).toContain("2 h 10 min");
    cleanup();
    const { container } = await renderLedger({ prefs: { backup: "priya" } });
    expect(text(container)).toContain("About 20 min with a backup");
    expect(text(container)).not.toContain("Jin approves all outside sharing");
    expect(qa(container, "button").some((b) => b.textContent === "Add a backup")).toBe(false);
  });

  it("WEB_7_ledger_wait_buckets_and_give_back_bars", async () => {
    const { container } = await renderLedger();
    const t = text(region(container, "Approval wait times"));
    for (const s of [
      "< 5 min",
      "5–15 min",
      "15–60 min",
      "1–4 hours",
      "> 4 hours",
      "Spend within limits",
      "6 min",
    ])
      expect(t, s).toContain(s);
    const g = text(region(container, "What Tilo gave back"));
    for (const s of [
      "£120",
      "£150",
      "£170",
      "£200",
      "Operations · 14 h",
      "Sales · 9 h",
      "Supply chain · 4 h",
    ])
      expect(g, s).toContain(s);
  });

  it("WEB_7_ledger_narrow_width_stacks_the_chart_and_donut", async () => {
    const wide = await renderLedger({ vw: 1440 });
    const cols = (c: HTMLElement) => q(c, "[data-chart-row]").style.gridTemplateColumns;
    expect(cols(wide.container)).toBe("minmax(0,1.65fr) minmax(320px,1fr)");
    cleanup();
    const narrow = await renderLedger({ vw: 900 });
    expect(cols(narrow.container)).toBe("minmax(0,1fr)");
  });
});

describe("WEB_7_ledger_decide: every approval goes through app.decide(key)", () => {
  it("WEB_7_ledger_the_first_waiting_row_is_open_and_approves_the_depot", async () => {
    const { container, calls } = await renderLedger();
    const act = region(container, "Activity");
    expect(text(act)).toContain("Above the £2,500 district limit");
    click(byText(act, "button", "Approve £3,420"));
    expect(calls.decide).toHaveBeenCalledWith("depot");
    // Everything bound to dec updates at once.
    const t = text(container);
    expect(t).toContain("£5,832");
    expect(t).toContain("73% of £8,000");
    expect(t).toContain("Laptop Depot approved today");
    expect(t).toContain("Forecast £6,300");
    expect(t).not.toContain("If you approve £3,420");
    expect(t).toContain("You approved £3,420 for Laptop Depot");
    expect(t).not.toContain("Laptop Depot asked for sign-off");
    expect(t).toContain("Waiting · 1");
    expect(
      qa(container, "button").some((b) => (b.textContent ?? "").startsWith("Waiting on you")),
    ).toBe(true);
  });

  it("WEB_7_ledger_waiting_filter_lists_the_two_asks_and_the_mail_row_sends_the_brief", async () => {
    const { container, calls } = await renderLedger();
    const act = region(container, "Activity");
    click(byText(act, '[role="radio"]', "Waiting · 2"));
    expect(text(act)).toContain("Laptop Depot asked for sign-off");
    expect(text(act)).toContain("Supplier brief waiting at the Mail Room gate");
    expect(text(act)).not.toContain("Battery cell samples");
    expect(qa(act, "button").some((b) => b.textContent === "Send brief")).toBe(false);
    click(rowWith(act, "Supplier brief waiting"));
    click(byText(act, "button", "Send brief"));
    expect(calls.decide).toHaveBeenCalledWith("mail");
  });

  it("WEB_7_ledger_after_both_decisions_waiting_is_empty", async () => {
    const { container, calls } = await renderLedger();
    const act = region(container, "Activity");
    click(byText(act, "button", "Approve £3,420"));
    click(rowWith(act, "Supplier brief waiting"));
    click(byText(act, "button", "Send brief"));
    expect(calls.decide.mock.calls.map((c) => c[0])).toEqual(["depot", "mail"]);
    click(byText(act, '[role="radio"]', "Waiting"));
    expect(text(act)).toContain("Nothing here this month.");
    click(byText(act, '[role="radio"]', "All"));
    expect(text(act)).toContain("Sent the supplier brief to 3 battery suppliers");
  });

  it("WEB_7_ledger_open_in_world_goes_to_the_row_world", async () => {
    const { container, calls } = await renderLedger();
    click(byText(region(container, "Activity"), "button", "Open in world"));
    expect(calls.go).toHaveBeenCalledWith("world", { id: "k1" });
  });
});

describe("WEB_7_ledger_honesty_and_states", () => {
  it("WEB_7_ledger_marks_fixture_data_and_never_hides_it", async () => {
    const { container } = await renderLedger();
    expect(q(container, "[data-park-ledger]").getAttribute("data-source")).toBe("fixture");
  });

  it("WEB_7_ledger_not_built_shows_not_connected_yet_and_no_numbers", async () => {
    const api = {
      ...createFixtureApi(),
      getLedger: () => Promise.reject(new NotBuilt("getLedger")),
    };
    const { container } = await renderLedger({ api });
    expect(text(container)).toContain("Not connected yet");
    expect(text(container)).not.toContain("£2,412");
    expect(container.querySelector("svg")).toBeNull();
  });

  it("WEB_7_ledger_logs_nothing_to_the_console_in_day_or_night", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    for (const time of ["day", "night"] as const) {
      const { container } = await renderLedger({ time });
      expect(container.querySelector('[data-time="' + time + '"]')).not.toBeNull();
      click(byText(container, '[role="radio"]', "Tool"));
      click(byText(container, '[role="radio"]', "Spend"));
      await settle();
      cleanup();
    }
    expect(err).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });
});
