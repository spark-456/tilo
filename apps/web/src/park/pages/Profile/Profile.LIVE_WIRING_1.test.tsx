// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import { createFixtureApi } from "../../api/fixtureApi";
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

it("LIVE_WIRING_1 signed-in profile uses identity and local toggles with costs and on-demand team read", async () => {
  const fetch = vi.fn(
    async (url: RequestInfo | URL) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/v1/people")
            ? {
                you: "u_ana",
                people: [{ id: "u_ana", display_name: "Ana Silva", org_role: "owner" }],
              }
            : { totals: { usd: 18 }, by_profile: [], by_task_type: [] },
        ),
      ),
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
  expect(text(root)).toContain("1 seat");
  expect(text(root)).not.toContain("£18");
  await openTab(root, "Notifications");
  expect(switchNamed(root, "Quiet hours").getAttribute("aria-checked")).toBe("false");
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(String(fetch.mock.calls[0]?.[0])).toBe("https://api.example/costs");
  expect(String(fetch.mock.calls[1]?.[0])).toBe("https://api.example/v1/people");
});
