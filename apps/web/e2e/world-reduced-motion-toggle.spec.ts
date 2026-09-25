import { expect, type Page, test } from "@playwright/test";
import { fixtureUrl, stageCanvas, stageSeq } from "./support/world";

// P4 / HR-3 (PRD 9.7): "with reduced motion movement becomes an instant change or a fade". A
// prefers-reduced-motion change during playback applies to every later movement, with no restart
// and no replay jump: after the toggle the canvas only changes when an event is applied (no
// interpolated in-between frames), and playback keeps going from where it was.

test.use({ viewport: { width: 1440, height: 900 }, reducedMotion: "no-preference" });

/** Distinct canvas images and distinct data-seq values seen per rAF over `ms`. */
function sample(page: Page, ms: number) {
  return page.evaluate((windowMs) => {
    const canvas = document.querySelector<HTMLCanvasElement>('[data-testid="stage-frame"] canvas');
    const frame = document.querySelector<HTMLElement>('[data-testid="stage-frame"]');
    // A small copy per frame keeps sampling cheap enough to see every rAF (a full-size PNG
    // encode per frame would itself drop most frames).
    const small = document.createElement("canvas");
    small.width = 480;
    small.height = 300;
    const ctx = small.getContext("2d");
    return new Promise<{ frames: number; seqs: number }>((resolve) => {
      const frames = new Set<string>();
      const seqs = new Set<string>();
      const start = performance.now();
      const tick = (now: number) => {
        if (canvas && ctx) {
          ctx.drawImage(canvas, 0, 0, small.width, small.height);
          frames.add(small.toDataURL());
        }
        seqs.add(frame?.dataset.seq ?? "");
        if (now - start < windowMs) requestAnimationFrame(tick);
        else resolve({ frames: frames.size, seqs: seqs.size });
      };
      requestAnimationFrame(tick);
    });
  }, ms);
}

test("P4 HR-3: turning on reduced motion mid-playback makes later movement instant", async ({
  page,
}) => {
  await page.goto(fixtureUrl("crowd-20"));
  await expect(stageCanvas(page)).toBeVisible();
  await expect.poll(() => stageSeq(page), { timeout: 15_000 }).toBeGreaterThan(25);

  const before = await sample(page, 1_500);
  expect(before.frames, "walks interpolate before the toggle").toBeGreaterThan(before.seqs + 5);

  const seqAtToggle = await stageSeq(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const after = await sample(page, 3_000);
  // One new image per applied event at most (plus the frame in flight at each window edge).
  expect(after.frames, "no interpolated frames after the toggle").toBeLessThanOrEqual(
    after.seqs + 2,
  );
  expect(await stageSeq(page), "playback continues, no restart").toBeGreaterThan(seqAtToggle);
});
