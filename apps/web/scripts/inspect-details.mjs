import { chromium } from "@playwright/test";

const BASE_URL = process.env.TILO_WEB_URL || "http://127.0.0.1:5678";

let browser;
try {
  browser = await chromium.launch({ headless: true, channel: "msedge" });
} catch (e) {
  browser = await chromium.launch({ headless: true });
}

const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
});
await context.addInitScript(() => {
  localStorage.setItem("tilo.time", "day");
  sessionStorage.setItem("tilo-boot-seen", "1");
});

const pagesToCheck = [
  { name: "Home", path: "/" },
  { name: "Worlds", path: "/worlds" },
  { name: "World k1", path: "/world/k1" },
  { name: "World w_village_basic", path: "/world/w_village_basic" },
  { name: "World w_sample_village_basic", path: "/world/w_sample_village_basic" },
  { name: "World Trace", path: "/world/w_village_basic/trace" },
  { name: "Skills", path: "/skills" },
  { name: "Chat", path: "/chat" },
  { name: "Agenda", path: "/agenda" },
  { name: "Needs", path: "/needs" },
  { name: "Ledger", path: "/ledger" },
  { name: "Team", path: "/team" },
  { name: "Connectors", path: "/connectors" },
  { name: "Settings", path: "/settings" },
];

for (const p of pagesToCheck) {
  const page = await context.newPage();
  try {
    await page.goto(`${BASE_URL}${p.path}`, { waitUntil: "domcontentloaded", timeout: 15000 });
    const bootCover = page.locator("#tilo-boot-cover");
    if ((await bootCover.count()) > 0) {
      await bootCover.waitFor({ state: "detached", timeout: 10000 }).catch(() => {});
    }
    await page.waitForTimeout(500);

    const data = await page.evaluate(() => {
      const text = document.body.innerText;
      // raw ids
      const idMatches = text.match(/\b([a-z]{1,4}_[a-zA-Z0-9_-]{3,})\b/g) || [];
      // filter out common harmless words like console_error etc if any
      const rawIds = [...new Set(idMatches)].filter(id => /^(tm_|w_|world_|sk_|conn_|usr_|user_|org_|sub_|sec_|err_)/.test(id));
      
      // empty states or broken text
      const emptyMatches = text.match(/(no\s+[a-z]+|nothing\s+[a-z]+|empty|coming\s+soon|not\s+found)/gi) || [];

      // buttons
      const buttons = Array.from(document.querySelectorAll("button, a")).map(el => ({
        tag: el.tagName.toLowerCase(),
        text: el.innerText.trim(),
        role: el.getAttribute("role"),
        href: el.getAttribute("href"),
        class: el.className,
      })).filter(b => !b.text && !b.href);

      return { rawIds, emptyMatches: [...new Set(emptyMatches)], suspiciousButtons: buttons };
    });

    console.log(`\n--- ${p.name} (${p.path}) ---`);
    if (data.rawIds.length) console.log("Raw IDs found:", data.rawIds);
    if (data.suspiciousButtons.length) console.log("Suspicious buttons:", data.suspiciousButtons);
  } catch (err) {
    console.log(`Error on ${p.name}:`, err.message);
  } finally {
    await page.close();
  }
}

await browser.close();
