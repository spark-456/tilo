import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { fixtureUrl, stageFrame, traceRows } from "./support/world";

// P1 / P10 regression: a stream with a duplicated event or a swapped pair (seq <= the highest
// applied) must not log anything, must never lower data-seq ("the highest seq applied") and must
// keep one Trace row per seq. The village-basic stream is served under a name that doesn't exist
// on disk via page.route, reshaped in the test.

const CONTRACT_FIXTURES = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../contracts/fixtures",
);
const LAYOUT = fs.readFileSync(
  path.join(CONTRACT_FIXTURES, "layout/valid/village_basic.json"),
  "utf8",
);
const EVENTS = fs
  .readFileSync(path.join(CONTRACT_FIXTURES, "streams/village-basic.jsonl"), "utf8")
  .split("\n")
  .filter((line) => line.trim().length > 0);
const LAST_SEQ = EVENTS.length;

const at = (i: number) => EVENTS[i] as string;
const STREAMS = {
  duplicate: { lines: [...EVENTS.slice(0, 6), at(5), ...EVENTS.slice(6)], rows: LAST_SEQ },
  swapped: {
    lines: [...EVENTS.slice(0, 10), at(11), at(10), ...EVENTS.slice(12)],
    rows: LAST_SEQ - 1,
  },
} as const;

test.use({ viewport: DESKTOP });

for (const [name, { lines, rows }] of Object.entries(STREAMS)) {
  test(`FR-WLD-04 seq order: a ${name} event is ignored, data-seq never drops, no console output`, async ({
    page,
  }) => {
    const messages: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" || msg.type() === "warning") {
        messages.push(`[${msg.type()}] ${msg.text()}`);
      }
    });
    page.on("pageerror", (err) => messages.push(`[pageerror] ${err.message}`));
    await page.route("**/fixtures/seq-order.layout.json", (route) =>
      route.fulfill({ contentType: "application/json", body: LAYOUT }),
    );
    await page.route("**/fixtures/seq-order.events.jsonl", (route) =>
      route.fulfill({ contentType: "text/plain", body: `${lines.join("\n")}\n` }),
    );
    await page.addInitScript(() => {
      const seen: number[] = [];
      (window as unknown as { __seqs: number[] }).__seqs = seen;
      new MutationObserver((records) => {
        for (const r of records) {
          const v = (r.target as Element).getAttribute("data-seq");
          if (v !== null) seen.push(Number(v));
        }
      }).observe(document, { attributes: true, attributeFilter: ["data-seq"], subtree: true });
    });

    await page.goto(fixtureUrl("seq-order", { speed: 1000 }));
    await expect(stageFrame(page)).toHaveAttribute("data-seq", String(LAST_SEQ), {
      timeout: 15_000,
    });
    await page.waitForTimeout(300);

    const seqs = await page.evaluate(() => (window as unknown as { __seqs: number[] }).__seqs);
    for (let i = 1; i < seqs.length; i++) {
      expect(seqs[i], `data-seq went down: ${seqs.join(",")}`).toBeGreaterThanOrEqual(
        seqs[i - 1] as number,
      );
    }
    await expect(traceRows(page)).toHaveCount(rows);
    const rowSeqs = await traceRows(page).evaluateAll((els) =>
      els.map((e) => e.getAttribute("data-seq")),
    );
    expect(new Set(rowSeqs).size).toBe(rowSeqs.length);
    expect(messages, messages.join("\n")).toEqual([]);
  });
}
