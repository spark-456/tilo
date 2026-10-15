// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { makeApp, renderPage, textOf } from "../../../../test-support/park/connectorsDom";
import { createLiveApi } from "../../api/liveApi";

afterEach(cleanup);
it("FR_UX_18_registered_catalogue_cards_show_owner_setup_without_fake_connections_or_passwords", async () => {
  const names = [
    "Slack",
    "Notion",
    "GitHub",
    "Xero",
    "HubSpot",
    "Stripe",
    "Microsoft 365",
    "Jira",
    "BambooHR",
  ];
  const fetch = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          connectors: names.map((name, i) => ({
            id: `service_${i}`,
            name,
            state: "available",
            state_known: false,
            scopes: [],
            expires_at: null,
          })),
        }),
      ),
  );
  const { container } = await renderPage(
    makeApp(),
    createLiveApi({ baseUrl: "https://api.test", fetch }),
  );
  const cards = [...container.querySelectorAll("article")];
  expect(cards).toHaveLength(9);
  for (const [index, card] of cards.entries()) {
    expect(textOf(card)).toContain(names[index]);
    expect(textOf(card)).toContain("Needs setup by the workspace owner");
    expect(textOf(card)).not.toMatch(/Connected|Healthy|Synced/);
  }
  expect(container.querySelector('input[type="password"]')).toBeNull();
  const labels = [...container.querySelectorAll("button")].map((b) => b.getAttribute("aria-label"));
  expect(labels).toEqual(names.map((n) => `Manage ${n}`)); // no Connect or Sign in button
  expect((fetch.mock.calls as unknown[][]).map(([u]) => new URL(String(u)).pathname)).toEqual([
    "/v1/connectors",
    "/v1/people",
  ]);
});
