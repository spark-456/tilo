// Pre-render the existing Tilo T thinking Buddy at 2x; ffmpeg and Chrome must be available locally.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const web = fileURLToPath(new URL("..", import.meta.url));
const frames = await mkdtemp(join(tmpdir(), "thinking-tilo-"));
const server = await createServer({
  root: web,
  optimizeDeps: { noDiscovery: true },
  server: { middlewareMode: true },
  appType: "custom",
});
let browser;
try {
  const { Buddy } = await server.ssrLoadModule("/src/design/tilo-t/Buddy.tsx");
  const buddy = renderToStaticMarkup(createElement(Buddy, { size: 56, mood: "think" }));
  const motion = await readFile(join(web, "src/design/tilo-t/motion.css"), "utf8");
  const css = `${motion}\n@keyframes rubHead{0%,100%{transform:rotate(-118deg)}50%{transform:rotate(-103deg)}}.tt-bd[data-mood="think"] .tt-bd__armR{animation:rubHead 1.2s ease-in-out infinite!important}body{margin:0;background:transparent}`;
  browser = await chromium.launch({ headless: true, channel: "chrome" });
  const page = await browser.newPage({ viewport: { width: 48, height: 58 }, deviceScaleFactor: 2 });
  await page.setContent(`<style>${css}</style>${buddy}`);
  for (let i = 0; i < 12; i++) {
    await page.evaluate((ms) => {
      for (const animation of document.getAnimations()) {
        animation.pause();
        animation.currentTime = ms;
      }
    }, i * 100);
    await page.screenshot({
      path: join(frames, `${String(i).padStart(3, "0")}.png`),
      omitBackground: true,
    });
  }
  const still = await readFile(join(frames, "000.png"));
  const webpPath = join(frames, "thinking.webp");
  const ffmpeg = spawnSync(
    "ffmpeg",
    [
      "-hide_banner",
      "-loglevel",
      "error",
      "-y",
      "-framerate",
      "10",
      "-i",
      join(frames, "%03d.png"),
      "-c:v",
      "libwebp_anim",
      "-lossless",
      "0",
      "-q:v",
      "50",
      "-loop",
      "0",
      webpPath,
    ],
    { encoding: "utf8" },
  );
  if (ffmpeg.status !== 0) throw new Error(`ffmpeg: ${ffmpeg.stderr || ffmpeg.error}`);
  const animated = await readFile(webpPath);
  if (animated.length > 40_000)
    throw new Error(`Thinking Tilo is ${animated.length} bytes (> 40 KB)`);
  const hash = (bytes) => createHash("sha256").update(bytes).digest("hex").slice(0, 12);
  const out = join(web, "public/loader");
  await mkdir(out, { recursive: true });
  await writeFile(join(out, `thinking-${hash(animated)}.webp`), animated);
  await writeFile(join(out, `thinking-${hash(still)}.png`), still);
  console.log(
    `thinking-${hash(animated)}.webp ${animated.length} bytes; thinking-${hash(still)}.png ${still.length} bytes`,
  );
} finally {
  await browser?.close();
  await server.close();
  await rm(frames, { recursive: true, force: true });
}
