import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { canvasSnapshot, fixtureUrl, stageCanvas, stageSeq } from "./support/world";

// P2 / FR-WLD-04 (e2e half — the reducer/frame purity half is in
// apps/web/src/world/{reducer,frame}.test.ts and reducer.property.test.ts): "two fresh pages at
// /?fixture=village-basic&seq=N render pixel-identical canvases for several N." ?seq=N (P8) is a
// static, non-animated frame, so a raw canvas.toDataURL() comparison across two independent
// browser contexts is meaningful (no camera easing or agent-walk animation mid-flight to race).

test.use({ viewport: DESKTOP });

const SEQS_TO_CHECK = [1, 5, 20, 44];

for (const seq of SEQS_TO_CHECK) {
  test(`FR-WLD-04 determinism: two fresh pages at seq=${seq} render pixel-identical canvases`, async ({
    browser,
  }) => {
    const contextA = await browser.newContext({ viewport: DESKTOP });
    const contextB = await browser.newContext({ viewport: DESKTOP });
    try {
      const pageA = await contextA.newPage();
      const pageB = await contextB.newPage();

      await pageA.goto(fixtureUrl("village-basic", { seq }));
      await pageB.goto(fixtureUrl("village-basic", { seq }));

      await expect(stageCanvas(pageA)).toBeVisible();
      await expect(stageCanvas(pageB)).toBeVisible();
      await expect.poll(() => stageSeq(pageA)).toBe(seq);
      await expect.poll(() => stageSeq(pageB)).toBe(seq);

      const snapshotA = await canvasSnapshot(pageA);
      const snapshotB = await canvasSnapshot(pageB);
      expect(
        snapshotA,
        `seq=${seq}: two independent pages rendered different pixels for the same layout+events`,
      ).toBe(snapshotB);
    } finally {
      await contextA.close();
      await contextB.close();
    }
  });
}
