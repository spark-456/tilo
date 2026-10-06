// FR-CHN-01 (PRD 10.3): web and mobile web draw every card with the full card structure. The six
// contract card fixtures (contracts/fixtures/card/valid, read from disk here, never retyped) are
// drawn on the dev gallery at 1440x900 and 390x844; each shows what_happened, why_it_matters,
// every option (the suggested one marked), the add-context field iff the card has it, and the same
// Show me / Snooze / Delegate actions, and the two viewports show the same thing.
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import type { Card } from "@tilo/contracts";
import { DESKTOP, MOBILE } from "../support/viewports";

const DIR = fileURLToPath(new URL("../../../../contracts/fixtures/card/valid/", import.meta.url));
const CARDS: Card[] = readdirSync(DIR)
  .filter((f) => f.endsWith(".json"))
  .sort()
  .map((f) => JSON.parse(readFileSync(`${DIR}${f}`, "utf8")) as Card);
const ACTION = { show_me: "Show me", snooze: "Snooze", delegate: "Delegate to Director" } as const;

test("FR_CHN_01 the contract has every card kind this parity test draws", () => {
  expect(new Set(CARDS.map((c) => c.rung))).toEqual(
    new Set(["needs_you", "blocked", "meeting", "gate", "consent"]),
  );
});

for (const viewport of [DESKTOP, MOBILE]) {
  test(`FR_CHN_01 every contract card kind renders in full at ${viewport.width}x${viewport.height} with the same actions`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/screens/cards");
    await expect(page.getByRole("heading", { level: 1, name: "Card fixtures" })).toBeVisible();
    for (const card of CARDS) {
      const el = page
        .locator(".need-card, .gate-sheet")
        .filter({ hasText: card.what_happened })
        .first();
      await expect(el, `${card.rung} card is drawn`).toBeVisible();
      await expect(el).toContainText(card.why_it_matters);
      // The options, in the card's order, by their own labels.
      await expect(el.locator(".need-option b")).toHaveText(card.options.map((o) => o.label));
      // Exactly one option is marked Suggested, by a word, not colour alone.
      const suggested = card.options.find((o) => o.suggested);
      await expect(el.getByText("Suggested", { exact: true })).toHaveCount(suggested ? 1 : 0);
      // Add-context field iff the card carries it.
      await expect(el.getByLabel("Add context (optional)")).toHaveCount(card.add_context ? 1 : 0);
      // Secondary actions: exactly those the card lists, and the rest absent.
      for (const [id, label] of Object.entries(ACTION)) {
        await expect(el.getByText(label, { exact: true }), `${card.rung} ${label}`).toHaveCount(
          card.actions.includes(id as keyof typeof ACTION) ? 1 : 0,
        );
      }
    }
  });
}
