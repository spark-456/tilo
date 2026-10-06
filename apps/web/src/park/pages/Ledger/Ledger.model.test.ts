// WEB-7 Ledger model: the reference's arithmetic (Tilo App Ledger.dc.html renderVals) as pure functions.
import { describe, expect, it } from "vitest";
import { decisions } from "../../api/fixtures";
import { ledger } from "../../api/fixtures/ledger";
import type { DecisionFacts } from "../../api/types";
import { activityGroups, chartGeometry, dayFromX, donut, gbp, kpis, waitingAmount } from "./model";

describe("WEB_7_ledger_model", () => {
  it("WEB_7_ledger_gbp_matches_the_prototype_formatter", () => {
    expect(gbp(0.4)).toBe("£0.40");
    expect(gbp(99.5)).toBe("£99.50");
    expect(gbp(100)).toBe("£100");
    expect(gbp(3420)).toBe("£3,420");
  });

  it("WEB_7_ledger_fixture_totals_agree_with_each_other", () => {
    expect(ledger.daily.reduce((a, v) => a + v, 0)).toBe(ledger.spent);
    expect(ledger.memory.reduce((a, v) => a + v, 0)).toBe(640);
    expect(ledger.hours.reduce((a, h) => a + h[1], 0)).toBe(46);
    expect(waitingAmount(ledger)).toBe(3420);
  });

  it("WEB_7_ledger_kpis_before_and_after_the_depot_decision", () => {
    const before = kpis(ledger, {}, decisions);
    expect(before.map((k) => [k.label, k.value, k.sub])).toEqual([
      ["Spent so far", "£2,412", "30% of £8,000"],
      ["Month-end forecast", "£6,300", "£1,700 under budget"],
      ["Waiting on you", "£3,420", "Laptop Depot sign-off"],
      ["Saved by memory", "£640", "Up £120 on August"],
      ["Hours handed back", "46 h", "About 6 working days"],
    ]);
    expect(before[2]?.tone).toBe("amber");
    expect(before[2]?.opensWorld).toBe("k1");
    const after = kpis(ledger, { depot: true }, decisions);
    expect(after[0]).toMatchObject({ value: "£5,832", sub: "73% of £8,000" });
    expect(after[2]).toMatchObject({ value: "£0", sub: "Laptop Depot approved today", tone: "ok" });
    expect(after[2]?.opensWorld).toBeUndefined();
  });

  it("WEB_7_ledger_chart_geometry_is_the_reference_geometry", () => {
    const c = chartGeometry(ledger, {}, null);
    expect(c.grid).toBe("M48 236.0 H700 M48 184.5 H700 M48 133.0 H700 M48 81.5 H700");
    expect(c.cap).toBe("M48 30.0 H700");
    expect(c.fcLabel).toBe("If you approve £3,420");
    expect(c.hOp).toBe("0");
    expect(c.xLabels.map((l) => l.t)).toEqual(["1 Sep", "8", "15", "Today", "30 Sep"]);
    expect(c.yLabels.map((l) => l.t)).toEqual(["£0", "£2k", "£4k", "£6k"]);
    // after the depot decision the forecast has two points and the label changes
    const d = chartGeometry(ledger, { depot: true }, 24);
    expect(d.fcLabel).toBe("Forecast £6,300");
    expect(d.fc.split("L")).toHaveLength(2);
    expect(c.fc.split("L")).toHaveLength(3);
    expect(d.tipA).toBe("Thu 24 Sep · £3,451");
    expect(d.tipB).toBe("Running total £5,832");
  });

  it("WEB_7_ledger_hover_day_comes_from_the_pointer_x", () => {
    expect(dayFromX(48 / 720)).toBe(1);
    expect(dayFromX((48 + 23 * (652 / 29)) / 720)).toBe(24);
    expect(dayFromX(1)).toBe(31); // the chart clamps to 1..24 when it draws
  });

  it("WEB_7_ledger_donut_stops_and_legend", () => {
    const d = donut(ledger, "world");
    expect(d.rows[0]).toEqual({
      name: "K1 electric scooter",
      amt: "£1,386",
      pct: "57%",
      c: "#5A3FE0",
    });
    expect(d.conic.startsWith("conic-gradient(#5A3FE0 0.00% ")).toBe(true);
    expect(d.rows).toHaveLength(5);
  });

  it("WEB_7_ledger_activity_filters_and_prepends_the_decisions", () => {
    const all = activityGroups(ledger, {}, "all", decisions);
    expect(all.waitN).toBe(2);
    expect(all.groups[0]?.day).toBe("Today · Thu 24 Sep");
    const done = activityGroups(ledger, { depot: true, mail: true }, "all", decisions);
    expect(done.waitN).toBe(0);
    expect(done.entries[0]?.what).toBe("You approved £3,420 for Laptop Depot");
    expect(done.entries[1]?.what).toBe("Sent the supplier brief to 3 battery suppliers");
    expect(
      activityGroups(ledger, { depot: true, mail: true }, "waiting", decisions).groups,
    ).toEqual([]);
  });

  it("WEB_7_ledger_words_and_world_come_from_the_decisions_not_the_page", () => {
    const other = decisions.map((d) => ({
      ...d,
      world: `${d.world}-other`,
      facts: {
        ...(d.facts as DecisionFacts),
        project: "Project P",
        approver: "Person Q",
        waiting: "Waiting S",
        decided: "Decided T",
        activity: `Activity of ${d.k}`,
      },
    }));
    const before = kpis(ledger, {}, other)[2];
    expect(before).toMatchObject({ sub: "Waiting S", opensWorld: "k1-other" });
    expect(kpis(ledger, { depot: true }, other)[2]?.sub).toBe("Decided T");
    const rows = activityGroups(ledger, { depot: true, mail: true }, "all", other).entries;
    expect(rows.slice(0, 2).map((e) => [e.world, e.what, e.sub])).toEqual([
      ["k1-other", "Activity of depot", "Project P · Person Q"],
      ["k1-other", "Activity of mail", "Project P · approved by you"],
    ]);
  });

  it("WEB_7_ledger_taken_rows_buttons_and_details_follow_the_facts", () => {
    // The decisions with some facts set and others removed.
    const vary = (set: Partial<DecisionFacts>, drop: (keyof DecisionFacts)[] = []) =>
      decisions.map((d) => {
        const facts: DecisionFacts = { ...(d.facts as DecisionFacts), ...set };
        for (const k of drop) delete facts[k];
        return { ...d, facts };
      });
    // Details come from the facts as given (rows, order, words), for both taken rows.
    const details: [string, string][] = [["Row A", "Value A"]];
    const taken = activityGroups(ledger, { depot: true, mail: true }, "all", vary({ details }));
    expect(taken.entries[0]?.detail).toEqual(details);
    expect(taken.entries[1]?.detail).toEqual(details);
    // No details given: an empty panel, never a made-up row.
    const bare = activityGroups(ledger, { depot: true, mail: true }, "all", vary({}, ["details"]));
    expect(bare.entries[0]?.detail).toEqual([]);
    // The amount of a taken row is the facts' own, a dash when they name none.
    expect(
      activityGroups(ledger, { depot: true }, "all", vary({ amount: 7 })).entries[0]?.amt,
    ).toBe("£7");
    expect(
      activityGroups(ledger, { depot: true }, "all", vary({}, ["amount"])).entries[0]?.amt,
    ).toBe("—");
    // The waiting rows' button: the facts' label, else "Approve" with an amount.
    const labels = (decs: ReturnType<typeof vary>) =>
      activityGroups(ledger, {}, "all", decs)
        .groups.flatMap((g) => g.rows)
        .filter((r) => r.waiting)
        .map((r) => r.approveLabel);
    expect(labels(vary({ approveLabel: "Do it" }))).toEqual(["Do it", "Do it"]);
    expect(labels(vary({ amount: 12 }, ["approveLabel"]))).toEqual(["Approve £12", "Approve £12"]);
    // Without decisions the amount the ledger's own transaction waits on is used.
    const alone = activityGroups(ledger, {}, "all").groups.flatMap((g) => g.rows);
    expect(alone.find((r) => r.decKey === "depot")?.approveLabel).toBe("Approve £3,420");
  });

  it("WEB_7_ledger_without_decisions_the_tile_has_no_world_link_and_no_scenario_words", () => {
    const tile = kpis(ledger, {})[2];
    expect(tile?.opensWorld).toBeUndefined();
    expect(tile?.sub).toBe("Needs your sign-off");
    // A taken decision the Api does not describe adds no row (the waiting rows still leave).
    expect(activityGroups(ledger, { depot: true, mail: true }, "all").entries).toEqual(
      ledger.activity.filter((e) => !e.dec),
    );
  });
});
