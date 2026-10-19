// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import type { Api } from "../../api";
import { createFixtureApi } from "../../api/fixtureApi";
import { cleanup, openTab, renderProfile, text } from "./testApp";

afterEach(cleanup);

async function livePlan(getTeam: Api["getTeam"]) {
  const api = createFixtureApi();
  const defaults = (await api.getProfileSettings()).data;
  return renderProfile(makeApp(), {
    ...api,
    getTeam,
    getProfileSettings: async () => ({
      data: { ...defaults, plan: null, invoices: null, payment: null },
      source: "live",
    }),
  });
}

it("FR_SET_05_beta_plan_uses_real_visible_team_count_and_has_no_billing_actions", async () => {
  const base = createFixtureApi();
  const team = (await base.getTeam()).data;
  const read = vi.fn(async () => ({
    data: { ...team, people: team.people.slice(0, 3) },
    source: "live" as const,
  }));
  const { root } = await livePlan(read);
  expect(read).not.toHaveBeenCalled();
  await openTab(root, "Plan and billing");
  expect(text(root)).toContain("Beta, no billing");
  expect(text(root)).toContain("3 seats");
  expect(text(root)).toContain("Based on team members visible to you");
  expect(text(root)).toContain("No renewal date during beta");
  expect(text(root)).toContain("No invoices during beta");
  expect(root.querySelector('button[aria-label="Download"]')).toBeNull();
  expect(text(root)).not.toContain("Compare plans");
  expect(text(root)).not.toContain("4242");
  expect(read).toHaveBeenCalledTimes(1);
});

it.each(["failed", "fixture"])(
  "FR_SET_05_%s_team_read_never_becomes_an_invented_seat_count",
  async (mode) => {
    const base = createFixtureApi();
    const { root } = await livePlan(
      mode === "failed"
        ? async () => {
            throw new Error("private failure");
          }
        : base.getTeam,
    );
    await openTab(root, "Plan and billing");
    expect(text(root)).toContain("Beta, no billing");
    expect(text(root)).toContain("Team seats unavailable");
    expect(text(root)).not.toMatch(/\d+ seats/);
    expect(text(root)).not.toContain("private failure");
  },
);
