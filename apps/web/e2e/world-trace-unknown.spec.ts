import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { canvasSnapshot, fixtureUrl, stageCanvas, traceRows } from "./support/world";

// P5 / HR-5: "An event whose type is not in contracts/events/registry.yaml leaves world state
// and frame deep-equal to the stream without it and appears only in a Trace list
// (data-testid="trace-list", one row per applied event with seq and type; for now the Trace
// list shows every applied event)."
//
// apps/web/fixtures/village-basic-unknown.events.jsonl is the village-basic stream (44 known
// events) plus one extra event at seq 45 of type "alert.batched" — one of the four types BQ-07
// found used by design/source/worlds/k1-generator.js but never registered in
// contracts/events/registry.yaml, so it is guaranteed unknown by construction (see
// apps/web/src/world/registry.test.ts, which asserts this directly against the registry).

test.use({ viewport: DESKTOP });

test("HR-5 trace: an unknown event type still gets exactly one Trace row, seq and type included", async ({
  page,
}) => {
  await page.goto(fixtureUrl("village-basic-unknown", { seq: 45 }));
  await expect(stageCanvas(page)).toBeVisible();

  const rows = traceRows(page);
  await expect(rows).toHaveCount(45); // one row per applied event, known or unknown (HR-5)

  const unknownRow = page.locator('[data-testid="trace-row"][data-event-type="alert.batched"]');
  await expect(unknownRow).toHaveCount(1);
  await expect(unknownRow).toHaveAttribute("data-seq", "45");
  await expect(unknownRow).toContainText("45");
  await expect(unknownRow).toContainText("alert.batched");
});

test("HR-5 trace: the unknown event does not change what the world renders — canvas is pixel-identical to the plain stream", async ({
  page,
  browser,
}) => {
  await page.goto(fixtureUrl("village-basic-unknown", { seq: 45 }));
  await expect(stageCanvas(page)).toBeVisible();
  const withUnknown = await canvasSnapshot(page);

  const plainContext = await browser.newContext({ viewport: DESKTOP });
  try {
    const plainPage = await plainContext.newPage();
    await plainPage.goto(fixtureUrl("village-basic", { seq: 44 }));
    await expect(stageCanvas(plainPage)).toBeVisible();
    const plain = await canvasSnapshot(plainPage);

    expect(
      withUnknown,
      "applying the unknown alert.batched event changed the rendered frame — HR-5 forbids that",
    ).toBe(plain);
  } finally {
    await plainContext.close();
  }
});
