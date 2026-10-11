// @vitest-environment happy-dom
// FR-SPD-02, 03, 04, 05 and 06 on the Ledger page (docs/prd-supplement-design-2026-10-06.md section 1.3).
// Every figure is stated as a function of the ledger object the page was given; tests vary the ledger to prove
// it. Fixture mode keeps the design's strings (BQ-DSN-02); a ledger served in USD shows its own unit; a figure
// the ledger does not hold is never typed in (HR-1). Each test says GREEN (pins existing behaviour) or RED
// (a gap before this ticket) in its comment.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../../test-support/park/appHarness";
import { cleanup, click, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import { decisions, ledger as fixtureLedger } from "../../api/fixtures";
import { ledgerFromCosts } from "../../api/live/ledgerFromCosts";
import type { Decision, Ledger } from "../../api/types";
import { ParkProvider, useApp, useParkStore } from "../../app/context";
import type { ParkStore } from "../../app/store";
import { LedgerPage } from "./LedgerPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
});

const settle = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });

function Shell({ onStore }: { onStore: (s: ParkStore) => void }) {
  const app = useApp();
  onStore(useParkStore());
  return (
    <div data-park="" data-time={app.time}>
      <LedgerPage app={app} />
    </div>
  );
}

/** The Ledger route over an Api that serves exactly `ledger` and the fixture decisions. */
async function mountLedger(
  ledger: Ledger = fixtureLedger,
  servedDecisions: Decision[] = decisions,
) {
  window.history.pushState({}, "", "/park/ledger");
  const api = fakeApi();
  api.getDecisions = async () => ({ data: servedDecisions, source: "fixture" });
  api.getLedger = (() =>
    Promise.resolve({ data: ledger, source: "fixture" })) as typeof api.getLedger;
  const navigate = vi.fn();
  let held: ParkStore | undefined;
  const m = mount(
    <ParkProvider
      api={api}
      navigate={navigate}
      schedule={fakeScheduler().schedule}
      viewport={{ vw: 1440, vh: 900 }}
    >
      <Shell
        onStore={(s) => {
          held = s;
        }}
      />
    </ParkProvider>,
  );
  const store = held;
  if (!store) throw new Error("the shell did not mount");
  act(() => store.setDecisions(decisions));
  await settle();
  return { ...m, api, navigate, store };
}

const text = (root: ParentNode) => (root as HTMLElement).textContent ?? "";
const region = (root: ParentNode, name: string) => q(root, `section[aria-label="${name}"]`);
const radio = (root: ParentNode, name: string) =>
  qa<HTMLElement>(root, '[role="radio"]').find((e) => (e.textContent ?? "").trim() === name);
const sum = (xs: readonly number[]) => xs.reduce((a, v) => a + v, 0);
const num = (s: string) => Number(s.replace(/[^0-9.]/g, ""));

it("FR_SPD_04_recorded_runs_show_totals_and_completion_without_skill_navigation", async () => {
  const { container } = await mountLedger({
    ...fixtureLedger,
    runs: [],
    recordedRuns: [
      { id: "recorded-a", usd: 1.25, completed: true },
      { id: "recorded-b", usd: 0, completed: false },
    ],
    currency: "USD",
  });
  const card = region(container, "Recorded run costs");
  expect(text(card)).toContain("recorded-a");
  expect(text(card)).toContain("$1.25");
  expect(text(card)).toContain("Completed");
  expect(text(card)).toContain("Completion not recorded");
  expect(qa(card, "button")).toHaveLength(0);
});

it("FR_SPD_05_06_07_live_history_shows_only_recorded_waits_and_honest_unavailable_estimates", async () => {
  const L = ledgerFromCosts({
    totals: { usd: 0 },
    by_profile: [],
    by_task_type: [],
    approval_waits: [{ action_type: "send_email", seconds: 120 }],
    activity: [
      {
        world_id: "recorded-world",
        run_id: "run-a",
        card_id: "card-a",
        type: "approval.resolved",
        ts: "2026-10-11T09:02:00Z",
        summary: "Held for edits",
      },
    ],
  });
  const { container, navigate } = await mountLedger(L);
  expect(text(region(container, "Approval wait times"))).toContain("2.0 min");
  expect(text(container)).toContain(
    "Memory savings by week and hours handed back are not available yet.",
  );
  const activity = region(container, "Activity");
  expect(text(activity)).toContain("Held for edits");
  expect(text(activity)).toContain("Approval answered");
  const open = qa<HTMLButtonElement>(activity, "button").find((b) =>
    b.textContent?.includes("Open in world"),
  );
  if (!open) throw new Error("missing world navigation");
  click(open);
  expect(navigate).toHaveBeenCalledWith(expect.stringContaining("recorded-world"));
});

it("FR_SPD_07_recorded_pending_approval_uses_the_existing_decide_once", async () => {
  const L = ledgerFromCosts({
    totals: { usd: 0 },
    by_profile: [],
    by_task_type: [],
    activity: [
      {
        world_id: "w",
        run_id: "r",
        card_id: "c",
        type: "approval.requested",
        ts: "2026-10-11T09:00:00Z",
        summary: "Recorded request",
      },
    ],
  });
  const key = L.activity[0]?.dec;
  if (!key || !decisions[0]) throw new Error("missing recorded decision key");
  const { container, api } = await mountLedger(L, [{ ...decisions[0], k: key }]);
  const approve = qa<HTMLButtonElement>(region(container, "Activity"), "button").find((b) =>
    b.textContent?.includes("Approve"),
  );
  if (!approve) throw new Error("missing inline approval");
  click(approve);
  await settle();
  expect(api.decide).toHaveBeenCalledTimes(1);
  expect(api.decide).toHaveBeenCalledWith(key);
});

it("FR_SPD_07_a_recorded_request_without_a_current_card_is_history_only", async () => {
  const L = ledgerFromCosts({
    totals: { usd: 0 },
    by_profile: [],
    by_task_type: [],
    activity: [
      {
        world_id: "w",
        run_id: "r",
        card_id: "gone",
        type: "approval.requested",
        ts: "2026-10-11T09:00:00Z",
        summary: "Old request",
      },
    ],
  });
  const { container } = await mountLedger(L, []);
  const feed = region(container, "Activity");
  expect(text(feed)).toContain("Approval requested");
  expect(text(feed)).not.toContain("Waiting on you");
  expect(qa(feed, "button").some((b) => b.textContent?.includes("Approve"))).toBe(false);
});

/** The fixture ledger with the numbers the tests care about changed to ones it holds nowhere. */
function varied(patch: Partial<Ledger> = {}): Ledger {
  const L = structuredClone(fixtureLedger);
  L.budget = 9000;
  L.spent = 3100;
  L.forecast = 7200;
  const waiting = L.tx.find((t) => t.st === "waiting");
  if (waiting) waiting.amt = 910;
  // the designed copy the fixture carries is not part of a ledger that does not hold it
  const { spike: _spike, memoryWeeks: _weeks, runLabels: _labels, ...held } = L;
  return { ...held, ...patch };
}

// ---------------------------------------------------------------------------------------------------------
describe("FR_SPD_02_ledger_spend_over_time", () => {
  const fcPath = (c: HTMLElement) => q(region(c, "Spend over the month"), ".park-ledger-p-fc");
  const fcNote = (c: HTMLElement) =>
    text(q(region(c, "Spend over the month"), ".park-ledger-note--fc"));

  // GREEN: pins that deciding the waiting approval changes the forecast line and its label, from the ledger given.
  it("FR_SPD_02_the_forecast_changes_when_the_waiting_approval_is_decided", async () => {
    const L = varied();
    const { container, store } = await mountLedger(L);
    const before = fcPath(container).getAttribute("d");
    expect(fcNote(container)).toBe("If you approve £910");
    act(() => store.decide("depot"));
    expect(fcNote(container)).toBe("Forecast £7,200");
    const after = fcPath(container).getAttribute("d");
    expect(after).not.toBe(before);
    // the forecast ends where the ledger's forecast is, before and after
    const end = q(region(container, "Spend over the month"), ".park-ledger-p-end");
    expect(end.getAttribute("cy")).toBe((236 - (7200 / 9000) * 206).toFixed(1));
  });

  // RED: the chart's budget, forecast and headline follow the ledger; the spike note is not typed in.
  it("FR_SPD_02_budget_line_headline_and_notes_follow_the_ledger_given", async () => {
    const { container } = await mountLedger(varied());
    const card = region(container, "Spend over the month");
    expect(text(card)).toContain("Budget £9,000");
    expect(text(card)).toContain("On track to finish £1,800 under budget");
    expect(text(card), "a spike the ledger does not hold").not.toContain("Motor dev kit");
    expect(card.querySelector(".park-ledger-note--spike")).toBeNull();
  });

  // RED: the headline never says "under budget" for a forecast above the budget.
  it("FR_SPD_02_a_forecast_above_the_budget_is_not_called_under_budget", async () => {
    const { container } = await mountLedger(varied({ forecast: 9500 }));
    const card = region(container, "Spend over the month");
    expect(text(card)).toContain("£500 over budget");
    expect(text(card)).not.toContain("under budget");
  });

  // RED: a spike the ledger names is drawn with its own label and amount.
  it("FR_SPD_02_a_spike_the_ledger_names_is_labelled_from_the_ledger", async () => {
    const L = varied({ spike: { day: 12, label: "Big purchase", amount: 140 } } as Partial<Ledger>);
    const { container } = await mountLedger(L);
    expect(text(region(container, "Spend over the month"))).toContain("Big purchase £140");
  });

  // RED: the today marker and label sit on the last day the ledger holds, and hovering past it shows that day.
  it("FR_SPD_02_today_marker_and_tooltip_use_the_last_day_the_ledger_holds", async () => {
    const daily = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
    const { container } = await mountLedger(varied({ daily }));
    const card = region(container, "Spend over the month");
    const x = 48 + 9 * (652 / 29);
    const label = qa<HTMLElement>(card, ".park-ledger-xlabel").find(
      (e) => e.textContent === "Today",
    );
    expect(label?.style.left).toBe(`${((x / 720) * 100).toFixed(2)}%`);
    expect(q(card, ".park-ledger-p-today").getAttribute("d")).toBe(`M${x.toFixed(1)} 24 V236`);
    const box = q(card, "[data-chart]");
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
    act(() => {
      box.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 700 }));
    });
    expect(text(q(box, "[data-tip]"))).toContain(`Running total £${sum(daily)}`);
  });
});

// ---------------------------------------------------------------------------------------------------------
describe("FR_SPD_03_ledger_where_it_goes", () => {
  const legendTotal = (root: HTMLElement) =>
    sum(
      qa(root, ".park-ledger-legendamt").map((e) => num((e.textContent ?? "").split("·")[0] ?? "")),
    );
  const holeTotal = (root: HTMLElement) => num(text(q(root, ".park-ledger-hole-value")));

  // GREEN: pins that world, tool and agent views show one total, and each legend adds up to it.
  it("FR_SPD_03_the_three_views_add_up_to_the_same_total", async () => {
    const { container } = await mountLedger();
    const where = region(container, "Where it goes");
    const totals: number[] = [];
    for (const view of ["World", "Tool", "Agent"]) {
      click(radio(where, view) as HTMLElement);
      totals.push(holeTotal(where));
      expect(legendTotal(where), `${view} legend adds up to its total`).toBe(holeTotal(where));
    }
    expect(new Set(totals).size, `totals ${totals}`).toBe(1);
    expect(totals[0]).toBe(fixtureLedger.spent);
  });

  // RED: the total in the ring is the sum of the rows being shown, not a second copy of the spent figure.
  it("FR_SPD_03_the_total_in_the_ring_is_the_sum_of_the_rows_of_the_view_shown", async () => {
    const L = varied();
    L.by = {
      world: {
        head: "A",
        rows: [
          ["One", 700],
          ["Two", 300],
        ],
      },
      tool: {
        head: "B",
        rows: [
          ["Three", 600],
          ["Four", 400],
        ],
      },
      role: { head: "C", rows: [["Five", 1000]] },
    };
    const { container } = await mountLedger(L);
    const where = region(container, "Where it goes");
    for (const view of ["World", "Tool", "Agent"]) {
      click(radio(where, view) as HTMLElement);
      expect(holeTotal(where)).toBe(1000);
      expect(legendTotal(where)).toBe(1000);
    }
  });
});

// ---------------------------------------------------------------------------------------------------------
describe("FR_SPD_04_ledger_cost_per_run", () => {
  const runs: Ledger["runs"] = [
    ["Alpha job", [4, 2, 1], 9, "alpha"],
    ["Beta job", [1, 2], 3, "beta"],
  ];

  // GREEN: pins that each card's drop and ends come from its series and a click opens that card's skill.
  it("FR_SPD_04_cards_follow_the_series_and_a_click_opens_that_skill", async () => {
    const { container, navigate } = await mountLedger(varied({ runs }));
    const cards = qa<HTMLElement>(region(container, "Cost per run"), "button");
    expect(cards).toHaveLength(2);
    expect(text(cards[0] as HTMLElement)).toBe("Alpha job−75%£4.00 run 1£1.00 run 9");
    expect(cards[0]?.querySelector("svg path.park-ledger-spark-line")).not.toBeNull();
    click(cards[1] as HTMLElement);
    expect(navigate).toHaveBeenCalledWith("/skills?id=beta");
  });

  // RED: a cost that rose is shown as a rise, never as "−-100%".
  it("FR_SPD_04_a_cost_that_rose_is_shown_as_a_rise", async () => {
    const { container } = await mountLedger(varied({ runs }));
    const beta = qa<HTMLElement>(region(container, "Cost per run"), "button")[1];
    expect(text(beta as HTMLElement)).toContain("+100%");
    expect(text(beta as HTMLElement)).not.toContain("−-");
  });

  // RED: the headline names the biggest drop the ledger holds, not the fixture's invoice figure.
  it("FR_SPD_04_the_headline_states_the_drop_the_ledger_holds", async () => {
    const { container } = await mountLedger(varied({ runs }));
    const card = region(container, "Cost per run");
    expect(text(card)).toContain("75% less");
    expect(text(card)).not.toContain("79%");
    cleanup();
    const rising = await mountLedger(varied({ runs: [runs[1] as Ledger["runs"][number]] }));
    expect(text(region(rising.container, "Cost per run"))).not.toContain("cheaper");
  });

  // RED (BQ-DSN-02): a ledger served in dollars shows dollars on every card.
  it("FR_SPD_04_cards_use_the_ledgers_own_unit", async () => {
    const { container } = await mountLedger(varied({ currency: "USD" }));
    const card = region(container, "Cost per run");
    expect(text(card)).toContain("$2.80 run 1");
    expect(text(card)).not.toContain("£");
  });
});

// ---------------------------------------------------------------------------------------------------------
describe("FR_SPD_05_ledger_approval_wait_times", () => {
  const SHARE = "Sharing outside the company";
  const waits = (extra: Record<string, unknown> = {}): Ledger["waits"] =>
    ({
      buckets: [
        ["< 5 min", 4],
        ["5–15 min", 2],
      ],
      types: [
        ["Spend within limits", "6 min", "ok"],
        [SHARE, "3 h", "amber"],
      ],
      ...extra,
    }) as Ledger["waits"];

  // RED today (the 20 minutes is typed in the page): adding a backup shows the wait the ledger holds for one.
  it("FR_SPD_05_adding_a_backup_approver_changes_the_shown_wait_to_the_ledgers_figure", async () => {
    const L = varied({ waits: waits({ withBackup: { [SHARE]: "About 40 min with a backup" } }) });
    const { container, store } = await mountLedger(L);
    const card = region(container, "Approval wait times");
    expect(text(card)).toContain("3 h");
    act(() => store.setPref("backup", "p2"));
    expect(text(card)).toContain("About 40 min with a backup");
    expect(text(card)).not.toContain("About 20 min");
  });

  // RED today: with no figure for a backup in the ledger, none is invented; the recorded wait stays.
  it("FR_SPD_05_no_backup_wait_is_invented_when_the_ledger_holds_none", async () => {
    const { container, store } = await mountLedger(varied({ waits: waits() }));
    act(() => store.setPref("backup", "p2"));
    const card = region(container, "Approval wait times");
    expect(text(card)).toContain("3 h");
    expect(text(card)).not.toMatch(/About \d+ min/);
  });

  // GREEN: the histogram and the call to action come from the ledger and the backup preference.
  it("FR_SPD_05_histogram_follows_the_ledger_and_the_call_to_action_goes_when_a_backup_exists", async () => {
    const { container, store, navigate } = await mountLedger(varied({ waits: waits() }));
    const card = region(container, "Approval wait times");
    expect(qa(card, ".park-ledger-bucket")).toHaveLength(2);
    expect(text(card)).toContain("< 5 min");
    const add = qa<HTMLElement>(card, "button").find((b) => b.textContent === "Add a backup");
    click(add as HTMLElement);
    expect(navigate).toHaveBeenCalledWith("/team?focus=share");
    act(() => store.setPref("backup", "p2"));
    expect(qa(card, "button").some((b) => b.textContent === "Add a backup")).toBe(false);
  });

  // RED: the headline does not state a typical wait the ledger does not hold.
  it("FR_SPD_05_the_headline_states_no_typical_wait_the_ledger_does_not_hold", async () => {
    const { container } = await mountLedger(varied({ waits: waits() }));
    expect(text(region(container, "Approval wait times"))).not.toContain("9 minutes");
  });
});

// ---------------------------------------------------------------------------------------------------------
describe("FR_SPD_06_ledger_what_tilo_gave_back", () => {
  const give = () =>
    varied({
      memory: [10, 20, 30, 40],
      hours: [
        ["Finance", 5, "#5A3FE0", "Invoices"],
        ["Ops", 4, "#0E7C79", "Rota"],
      ],
    });

  // RED: both figures are labelled estimates and each links to its method, which opens in place.
  it("FR_SPD_06_estimates_are_labelled_and_link_to_their_method", async () => {
    const { container } = await mountLedger(give());
    const card = region(container, "What Tilo gave back");
    const labels = qa(card, "[data-estimate]");
    expect(labels).toHaveLength(2);
    for (const l of labels) expect(l.textContent).toMatch(/estimate/i);
    const links = qa<HTMLElement>(card, "button").filter((b) =>
      (b.textContent ?? "").includes("How this is counted"),
    );
    expect(links).toHaveLength(2);
    const seen: string[] = [];
    for (const link of links) {
      expect(link.getAttribute("aria-expanded")).toBe("false");
      click(link);
      expect(link.getAttribute("aria-expanded")).toBe("true");
      const method = document.getElementById(link.getAttribute("aria-controls") ?? "");
      expect(
        (method?.textContent ?? "").length,
        "the method is stated in a sentence",
      ).toBeGreaterThan(40);
      seen.push(method?.textContent ?? "");
    }
    expect(new Set(seen).size, "each figure has its own method").toBe(2);
  });

  // RED: bars scale to the ledger's own largest week and total hours, and week names are not typed in.
  it("FR_SPD_06_bars_and_week_labels_follow_the_ledger_given", async () => {
    const { container } = await mountLedger(give());
    const card = region(container, "What Tilo gave back");
    const bars = qa<HTMLElement>(card, ".park-ledger-bar-col");
    expect(bars.map((b) => b.style.height)).toEqual(["30px", "60px", "90px", "120px"]);
    expect(text(card)).not.toContain("22–24");
    const widths = qa<HTMLElement>(card, ".park-ledger-stacked span").map((s) =>
      Number.parseFloat(s.style.width),
    );
    expect(widths[0]).toBeCloseTo((5 / 9) * 100, 1);
    expect(widths[1]).toBeCloseTo((4 / 9) * 100, 1);
  });

  // RED: a ledger that names its weeks gets those names.
  it("FR_SPD_06_week_labels_come_from_the_ledger_when_it_names_them", async () => {
    const weeks = ["W1", "W2", "W3", "W4"];
    const { container } = await mountLedger({ ...give(), memoryWeeks: weeks } as Ledger);
    const card = text(region(container, "What Tilo gave back"));
    for (const w of weeks) expect(card).toContain(w);
  });
});
