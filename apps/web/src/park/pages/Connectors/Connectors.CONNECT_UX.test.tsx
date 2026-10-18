// @vitest-environment happy-dom
// CONNECT-UX: The Connectors page: only Gmail, Google Drive and Google Calendar as real connected cards with logo,
// status, and a clear Connect or Reconnect button; everything else as one calm "Coming later" row of greyed items
// (never Canva). Clear plain-language errors, no raw status codes, an empty state, good layout at 1440 and 390 in
// light and dark. Do not change how connecting works.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  connectedTiles,
  makeApp,
  renderPage,
  spyApi,
  textOf,
  typeInto,
  waitFor,
} from "../../../../test-support/park/connectorsDom";
import { createLiveApi } from "../../api/liveApi";
import type { Connector } from "../../api/types";

afterEach(cleanup);

const GOOGLE_IDS = ["gmail", "google_drive", "google_calendar", "gdrive", "gcal"];

describe("CONNECT-UX: Connectors page redesign", () => {
  it("CONNECT_UX_only_gmail_drive_and_calendar_are_real_cards_with_status_and_action", async () => {
    const app = makeApp();
    const api = spyApi();
    const m = await renderPage(app, api);
    await waitFor(
      () =>
        m.container.querySelectorAll(
          ".park-connectors-card, .park-connectors-tile, [data-connector-card]",
        ).length > 0,
      "connector cards",
    );

    const root = m.container;
    const cards = [
      ...root.querySelectorAll<HTMLElement>(
        "[data-connector-card], .park-connectors-card, .park-connectors-tile",
      ),
    ];

    // Extract names or ids of the real connector cards
    const cardNames = cards.map((c) => textOf(c));

    // Only Gmail, Google Drive, Google Calendar should be rendered as real cards
    for (const name of cardNames) {
      const isAllowed = /gmail|google drive|drive|google calendar|calendar/i.test(name);
      expect(isAllowed, `Unexpected full card rendered: ${name}`).toBe(true);
    }

    // Must have cards for Gmail, Drive, Calendar
    const fullText = textOf(root);
    expect(fullText).toMatch(/Gmail/i);
    expect(fullText).toMatch(/Google Drive|Drive/i);
    expect(fullText).toMatch(/Google Calendar|Calendar/i);

    // Each real card must have a logo, status, and a clear Connect or Reconnect or Connected button
    for (const card of cards) {
      const hasLogo = card.querySelector(".park-connectors-brand, svg, img") !== null;
      expect(hasLogo, "Card must have a logo").toBe(true);
      const cardText = textOf(card);
      const hasStatus = /connected|attention|needs attention|not connected|available/i.test(
        cardText,
      );
      expect(hasStatus, "Card must have a status").toBe(true);
      const hasAction =
        card.querySelector("button") !== null ||
        /connect|reconnect|connected|manage/i.test(cardText);
      expect(hasAction, "Card must have a clear Connect or Reconnect button").toBe(true);
    }
  });

  it("CONNECT_UX_coming_later_row_shows_greyed_items_and_never_canva", async () => {
    const app = makeApp();
    const api = spyApi();
    const m = await renderPage(app, api);
    await waitFor(
      () =>
        m.container.querySelector(".park-connectors-coming-later, [data-coming-later]") !== null,
      "Coming later section",
    );

    const root = m.container;
    const comingLater = root.querySelector(".park-connectors-coming-later, [data-coming-later]");
    expect(comingLater).not.toBeNull();
    const comingText = textOf(comingLater as Element);
    expect(comingText).toContain("Coming later");

    // Must NOT contain Canva under any circumstance
    const fullPageText = textOf(root);
    expect(fullPageText.toLowerCase()).not.toContain("canva");

    // Other services (Slack, Notion, GitHub, Jira, etc.) should be in coming later, greyed out
    expect(comingText).toMatch(/Slack|Notion|GitHub|HubSpot|Jira|Xero|Stripe/i);
  });

  it("CONNECT_UX_empty_state_shown_when_no_connectors_match", async () => {
    const app = makeApp();
    const api = spyApi();
    const m = await renderPage(app, api);
    await waitFor(
      () => m.container.querySelector('input[aria-label="Search connectors"]') !== null,
      "Search input",
    );

    const root = m.container;
    const search = root.querySelector<HTMLInputElement>('input[aria-label="Search connectors"]');
    expect(search).not.toBeNull();
    typeInto(search as HTMLInputElement, "NonExistentAppXYZ");

    const empty = root.querySelector('[data-testid="connectors-empty"], .park-connectors-empty');
    expect(empty).not.toBeNull();
    expect(textOf(empty as Element)).toMatch(/no matching connectors/i);
  });

  it("CONNECT_UX_plain_language_errors_no_raw_status_codes", async () => {
    const fetch = vi.fn(async () => new Response("Internal Server Error", { status: 500 }));
    const api = createLiveApi({ baseUrl: "https://api.test", fetch });
    const app = makeApp();
    const { container: root } = await renderPage(app, api);
    await waitFor(
      () => root.querySelector(".park-connectors-empty, [role=alert]") !== null,
      "Error display",
    );

    const text = textOf(root);
    expect(text).not.toContain("500");
    expect(text).not.toMatch(/status\s*(?:code)?\s*500/i);
    expect(text).toMatch(/unavailable|problem|try again/i);
  });
});
