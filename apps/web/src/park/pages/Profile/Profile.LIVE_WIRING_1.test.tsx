// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import { createFixtureApi } from "../../api/fixtureApi";
import { userSettings } from "../../api/fixtures";
import { createLiveApi } from "../../api/liveApi";
import { withSession } from "../../api/select";
import {
  cleanup,
  clickAndSettle,
  fieldInput,
  openTab,
  renderProfile,
  switchNamed,
  text,
} from "./testApp";

afterEach(cleanup);

it("LIVE_WIRING_1 null billing and sessions show unavailable panels without actions", async () => {
  const api = createFixtureApi();
  const settings = (await api.getProfileSettings()).data;
  const { root } = await renderProfile(makeApp(), {
    ...api,
    getProfileSettings: async () => ({
      data: { ...settings, sessions: null, invoices: null, payment: null, plan: null },
      source: "live",
    }),
  });
  await openTab(root, "Plan and billing");
  expect(text(root)).toContain("Not available yet");
  expect(root.querySelectorAll(".park-profile-unavailable")).toHaveLength(3);
  expect(text(root)).not.toContain("0 seats");
  expect(text(root)).not.toContain("4242");
  await openTab(root, "Security");
  expect(text(root)).toContain("Not available yet");
  expect(
    [...root.querySelectorAll("button")].filter((b) => text(b).startsWith("Sign out")),
  ).toHaveLength(0);
  await openTab(root, "Notifications");
  await clickAndSettle(switchNamed(root, "A decision needs you by Phone"));
  await clickAndSettle(switchNamed(root, "A decision needs you by Email"));
  const last = switchNamed(root, "A decision needs you by Slack");
  await clickAndSettle(last);
  expect(last.getAttribute("aria-checked")).toBe("true");
});

it("LIVE_WIRING_1 signed-in profile uses identity and draft toggles with only the costs and settings read", async () => {
  // FR-SET-01: nothing saved yet (version 0), so the form starts from the sign-in identity.
  const unsaved = { ...userSettings, version: 0, updated_at: null };
  const costs = { totals: { usd: 18 }, by_profile: [], by_task_type: [] };
  const fetch = vi.fn(
    async (url: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify(String(url).endsWith("/v1/me/settings") ? unsaved : costs)),
  );
  const api = withSession(createLiveApi({ baseUrl: "https://api.example", fetch }), {
    demo: () => false,
    identity: () => ({ name: "Ana Silva", email: "ana@example.test" }),
    now: () => new Date("2026-10-09T00:00:00Z"),
  });
  const { root } = await renderProfile(makeApp(), api);
  expect(fieldInput(root, "Full name").value).toBe("Ana Silva");
  expect(fieldInput(root, "Work email").value).toBe("ana@example.test");
  expect(text(root)).not.toContain("Owner on the  plan");
  await openTab(root, "Notifications");
  expect(text(root)).toContain("Decision threshold: Not available yet");
  expect(text(root)).not.toContain("£1,000");
  await clickAndSettle(switchNamed(root, "Quiet hours"));
  await openTab(root, "Plan and billing");
  expect(text(root)).toContain("$18");
  expect(text(root)).not.toContain("£18");
  await openTab(root, "Notifications");
  expect(switchNamed(root, "Quiet hours").getAttribute("aria-checked")).toBe("false");
  expect(fetch.mock.calls.map((c) => String(c[0])).sort()).toEqual([
    "https://api.example/costs",
    "https://api.example/v1/me/settings",
  ]);
  const verbs = fetch.mock.calls.map((c) => (c[1] as RequestInit | undefined)?.method ?? "GET");
  expect(verbs, "reads only: no PUT").toEqual(["GET", "GET"]);
});
