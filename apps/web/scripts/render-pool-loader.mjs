// Render the existing Tilo T Buddy and Pool CSS once, then ship pixels instead of animating the live DOM.
// Requires the repository's Playwright install and an ffmpeg binary on PATH.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

// The canvas holds the whole pool with room above for Tilo's leap (scale capped at 2, so nothing is cropped) and the
// pool's centre on the canvas centre, so a centred image is a centred pool. Sizes are CSS pixels (stage 380x280).
const PAD_X = 40;
const PAD_TOP = 200;
const CANVAS_W = 460;
const CANVAS_H = 2 * (PAD_TOP + 103);
const FPS = 15;
const OUT_W = 552;
const OUT_H = Math.round((OUT_W * CANVAS_H) / CANVAS_W);
const LEAP_KEYFRAMES =
  "@keyframes tLeap{0%{transform:translateY(70px) scale(.62);opacity:0}10%{opacity:1;transform:translateY(40px) scale(.66)}24%{transform:translateY(-30px) scale(1.05) rotate(-3deg)}48%{transform:translateY(-70px) scale(1.9) rotate(-5deg)}56%{transform:translateY(-62px) scale(2) rotate(-3deg)}80%{transform:translateY(10px) scale(.8) rotate(7deg)}88%{transform:translateY(44px) scale(.62) rotate(4deg);opacity:1}90%,100%{transform:translateY(44px) scale(.62);opacity:0}}";
const web = fileURLToPath(new URL("..", import.meta.url));
const out = join(web, "public", "loader");
const frames = await mkdtemp(join(tmpdir(), "tilo-pool-"));
const server = await createServer({
  root: web,
  optimizeDeps: { noDiscovery: true },
  server: { middlewareMode: true },
  appType: "custom",
});
let browser;
try {
  const { Buddy } = await server.ssrLoadModule("/src/design/tilo-t/Buddy.tsx");
  const happy = renderToStaticMarkup(createElement(Buddy, { size: 120, mood: "happy" }));
  const swim = renderToStaticMarkup(createElement(Buddy, { size: 80, mood: "swim" }));
  const css = ["PoolLoader.css", "motion.css"].map((name) =>
    join(web, "src", "design", "tilo-t", name),
  );
  const style = (await Promise.all(css.map((path) => readFile(path, "utf8")))).join("\n");
  const drops = Array.from({ length: 12 }, (_, i) => {
    const angle = Math.PI * (1.05 + (i / 11) * 0.9);
    const radius = 70 + ((i * 29) % 60);
    const dx = Math.round(Math.cos(angle) * radius * 1.6);
    const dy = Math.round(Math.sin(angle) * radius * 1.2 - 30);
    return `<span class="tt-pool__drop" style="--dx:${dx}px;--dy:${dy}px;--tt-drop-delay:${2.236 + (i % 4) * 0.03}s;left:${50 + (i % 3) * 2}%;top:50%;width:${i % 3 ? 10 : 14}px;height:${i % 3 ? 13 : 18}px;background:${i % 4 ? "#9fcfe0" : "#fff"}"></span>`;
  }).join("");
  const water = `<div class="tt-pool__water"></div>`;
  const leap = `${water}<span class="tt-pool__shadow"></span><div class="tt-pool__buddy tt-pool__buddy--leap tt-pool__leap">${happy}</div><span class="tt-pool__lip" aria-hidden="true"></span><div class="tt-pool__drops">${drops}<span class="tt-pool__splash"></span></div>`;
  // The clip box stays put and only the Buddy inside it sinks, so he is hidden once under the water line.
  const sink = `${water}<span class="tt-pool__lip" aria-hidden="true"></span><div class="tt-pool__buddy tt-pool__buddy--sink"><div class="tt-pool__sink-buddy">${swim}</div></div><span class="tt-pool__sink-ripple"></span>`;
  browser = await chromium.launch({ headless: true, channel: "chrome" });
  const page = await browser.newPage({
    viewport: { width: CANVAS_W, height: CANVAS_H },
    deviceScaleFactor: 2,
  });
  await page.setContent(
    `<style>:root{--tt-ease-standard:cubic-bezier(.2,.7,.2,1);--tt-ease-leap:cubic-bezier(.4,0,.2,1)}body{margin:0;background:transparent}${style}.tt-pool__stage{transform:none;position:absolute;left:${PAD_X}px;top:${PAD_TOP}px}${LEAP_KEYFRAMES}</style><div class="tt-pool__stage">${leap}</div>`,
  );
  const STEP_MS = 1000 / FPS;
  const LEAP_FRAMES = Math.round(2600 / STEP_MS);
  const TOTAL_FRAMES = Math.round(4600 / STEP_MS);
  for (let i = 0; i < TOTAL_FRAMES; i++) {
    if (i === LEAP_FRAMES)
      await page.locator(".tt-pool__stage").evaluate((el, html) => {
        el.innerHTML = html;
      }, sink);
    await page.evaluate(
      (ms) => {
        for (const animation of document.getAnimations()) {
          animation.pause();
          animation.currentTime = animation.effect?.target?.matches?.(
            ".tt-pool__water, .tt-pool__lip",
          )
            ? 500
            : ms;
        }
      },
      (i < LEAP_FRAMES ? i : i - LEAP_FRAMES) * STEP_MS,
    );
    await page.screenshot({
      path: join(frames, `${String(i).padStart(3, "0")}.png`),
      omitBackground: true,
    });
    if (i === LEAP_FRAMES + Math.round(400 / STEP_MS)) {
      await page.screenshot({ path: join(frames, "still.png"), omitBackground: true });
      // the small planning card shows the pool alone, cropped to its water
      await page.screenshot({
        path: join(frames, "card.png"),
        omitBackground: true,
        clip: { x: PAD_X + 10, y: PAD_TOP + 20, width: 360, height: 140 },
      });
    }
  }
  const source = join(frames, "%03d.png");
  const target = join(frames, "pool.webp");
  const ffmpeg = spawnSync(
    "ffmpeg",
    [
      "-hide_banner",
      "-loglevel",
      "error",
      "-y",
      "-framerate",
      String(FPS),
      "-i",
      source,
      "-vf",
      `scale=${OUT_W}:${OUT_H}`,
      "-c:v",
      "libwebp_anim",
      "-lossless",
      "0",
      "-q:v",
      "20",
      "-compression_level",
      "6",
      "-loop",
      "0",
      target,
    ],
    { encoding: "utf8" },
  );
  if (ffmpeg.status !== 0) throw new Error(`ffmpeg: ${ffmpeg.stderr || ffmpeg.error}`);
  const bytes = await readFile(target);
  const hash = createHash("sha256").update(bytes).digest("hex").slice(0, 12);
  const stillBytes = await readFile(join(frames, "still.png"));
  const stillHash = createHash("sha256").update(stillBytes).digest("hex").slice(0, 12);
  const cardBytes = await readFile(join(frames, "card.png"));
  const cardHash = createHash("sha256").update(cardBytes).digest("hex").slice(0, 12);
  const { mkdir } = await import("node:fs/promises");
  await mkdir(out, { recursive: true });
  await writeFile(join(out, `pool-${hash}.webp`), bytes);
  await writeFile(join(out, `pool-${stillHash}.png`), stillBytes);
  await writeFile(join(out, `pool-card-${cardHash}.png`), cardBytes);
  console.log(
    `pool-${hash}.webp ${(await stat(join(out, `pool-${hash}.webp`))).size} bytes; pool-${stillHash}.png ${stillBytes.length} bytes; pool-card-${cardHash}.png ${cardBytes.length} bytes`,
  );
} finally {
  await browser?.close();
  await server.close();
  await rm(frames, { recursive: true, force: true });
}
