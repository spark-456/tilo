import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.TILO_WEB_URL || "http://127.0.0.1:5678";
const EVIDENCE_DIR = "C:/dev/Tilo/agy-bridge/evidence/QA-DEMO";
mkdirSync(EVIDENCE_DIR, { recursive: true });

let browser;
try {
  browser = await chromium.launch({ headless: true, channel: "msedge" });
} catch (e) {
  try {
    browser = await chromium.launch({ headless: true, channel: "chrome" });
  } catch (e2) {
    browser = await chromium.launch({ headless: true });
  }
}

const rawIdRegex = /\b(tm_[a-zA-Z0-9_-]+|w_[a-zA-Z0-9_-]+|world_[a-zA-Z0-9_-]+|sk_[a-zA-Z0-9_-]+|conn_[a-zA-Z0-9_-]+|usr_[a-zA-Z0-9_-]+|user_[a-zA-Z0-9_-]+|u_owner|org_[a-zA-Z0-9_-]+|sub_[a-zA-Z0-9_-]+|demo_runs_busy)\b/;

async function analyzePage(page, name, width, theme) {
  const issues = [];

  // Check horizontal scroll
  const scrollInfo = await page.evaluate(() => {
    const doc = document.documentElement;
    const body = document.body;
    const scrollW = Math.max(doc.scrollWidth, body.scrollWidth);
    const clientW = window.innerWidth;
    const overflowing = [];
    if (scrollW > clientW + 1) {
      const all = document.querySelectorAll("*");
      for (const el of all) {
        const r = el.getBoundingClientRect();
        if (r.right > clientW + 1 && r.width > 0 && r.height > 0) {
          const cls = el.className ? String(el.className).slice(0, 80) : "";
          overflowing.push(`${el.tagName.toLowerCase()}.${cls} (right: ${Math.round(r.right)} > ${clientW})`);
          if (overflowing.length > 5) break;
        }
      }
    }
    return { hasScroll: scrollW > clientW + 1, scrollW, clientW, overflowing };
  });

  if (scrollInfo.hasScroll) {
    issues.push({
      type: "horizontal-scroll",
      detail: `Page has horizontal scroll: scrollWidth ${scrollInfo.scrollW} > clientWidth ${scrollInfo.clientW}. Overflow elements: ${scrollInfo.overflowing.join("; ")}`,
    });
  }

  // Check raw IDs in DOM text
  const rawIds = await page.evaluate((patternStr) => {
    const regex = new RegExp(patternStr, "g");
    const found = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent) continue;
      const tag = parent.tagName.toLowerCase();
      if (tag === "script" || tag === "style" || tag === "noscript") continue;
      if (parent.offsetParent === null && parent.offsetWidth === 0 && parent.offsetHeight === 0) continue;
      const text = node.textContent || "";
      const matches = text.match(regex);
      if (matches) {
        for (const m of matches) {
          found.push({ id: m, context: text.trim().slice(0, 100), tag, class: parent.className });
        }
      }
    }
    return found;
  }, rawIdRegex.source);

  if (rawIds.length > 0) {
    const uniq = [...new Set(rawIds.map((r) => r.id))];
    issues.push({
      type: "raw-ids",
      detail: `Raw IDs visible in UI: ${uniq.join(", ")} (contexts: ${rawIds.slice(0, 3).map((r) => `"${r.context}" in <${r.tag}>`).join("; ")})`,
    });
  }

  // Check dead buttons and links
  const deadElements = await page.evaluate(() => {
    const dead = [];
    const links = document.querySelectorAll("a");
    for (const a of links) {
      if (a.offsetParent === null && a.offsetWidth === 0 && a.offsetHeight === 0) continue;
      const href = a.getAttribute("href");
      const role = a.getAttribute("role");
      if ((!href || href === "#" || href === "") && role !== "tab" && role !== "button") {
        dead.push({ tag: "a", text: a.textContent?.trim().slice(0, 40), class: a.className, reason: `href is "${href}" without role=button/tab` });
      }
    }
    const buttons = document.querySelectorAll("button");
    for (const b of buttons) {
      if (b.offsetParent === null && b.offsetWidth === 0 && b.offsetHeight === 0) continue;
      const text = b.textContent?.trim() || "";
      const aria = b.getAttribute("aria-label") || b.getAttribute("title") || "";
      const hasSvg = b.querySelector("svg") !== null;
      if (!text && !aria && !hasSvg) {
        dead.push({ tag: "button", class: b.className, reason: "button has no text, no aria-label, no icon" });
      }
    }
    return dead;
  });

  if (deadElements.length > 0) {
    issues.push({
      type: "dead-elements",
      detail: deadElements.map((d) => `<${d.tag} class="${d.class}">: ${d.reason} (text: "${d.text || ''}")`).join("; "),
    });
  }

  // Check plain div with aria-label (rule violation)
  const plainDivAria = await page.evaluate(() => {
    const divs = document.querySelectorAll("div[aria-label]");
    const found = [];
    for (const d of divs) {
      const role = d.getAttribute("role");
      if (!role) {
        found.push({ class: d.className, label: d.getAttribute("aria-label") });
      }
    }
    return found;
  });

  if (plainDivAria.length > 0) {
    issues.push({
      type: "plain-div-aria-label",
      detail: `Found plain div with aria-label and no role: ${plainDivAria.map((d) => `div.${d.class} ("${d.label}")`).join(", ")}`,
    });
  }

  return issues;
}

const reportFindings = [];

async function captureStep(context, path, pageName, readySelector, actionFn, width, theme) {
  const page = await context.newPage();
  const consoleMessages = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") {
      consoleMessages.push(`[${m.type()}] ${m.text()}`);
    }
  });
  page.on("pageerror", (e) => {
    consoleMessages.push(`[pageerror] ${e.message}`);
  });

  try {
    await page.goto(`${BASE_URL}${path}`, { waitUntil: "domcontentloaded", timeout: 30000 });
    const bootCover = page.locator("#tilo-boot-cover");
    if ((await bootCover.count()) > 0) {
      await bootCover.waitFor({ state: "detached", timeout: 15000 }).catch(() => {});
    }
    await page.evaluate(() => document.fonts.ready.then(() => undefined)).catch(() => {});

    if (readySelector) {
      await page.locator(readySelector).first().waitFor({ state: "visible", timeout: 15000 }).catch(() => {});
    }
    await page.waitForTimeout(500);

    // Apply theme
    await page.locator("[data-park]").evaluate((node, t) => {
      node.setAttribute("data-time", t);
    }, theme).catch(() => {});
    await page.waitForTimeout(400);

    if (actionFn) {
      await actionFn(page);
      await page.waitForTimeout(500);
    }

    const shotName = `${pageName}-${width}-${theme}.png`;
    const shotPath = resolve(EVIDENCE_DIR, shotName);
    await page.screenshot({ path: shotPath, fullPage: true, animations: "disabled" });

    const issues = await analyzePage(page, pageName, width, theme);
    // filter host noise warnings from console
    const filteredConsole = consoleMessages.filter(msg => !msg.includes("nunito-sans") && !msg.includes("adblock360"));
    if (filteredConsole.length > 0) {
      issues.push({
        type: "console",
        detail: filteredConsole.join("\n"),
      });
    }

    reportFindings.push({
      pageName,
      path,
      width,
      theme,
      screenshot: shotName,
      issues,
    });
    console.log(`[DONE] ${pageName} (${width}px, ${theme}): ${issues.length} issue(s)`);
  } catch (err) {
    console.error(`[FAIL] ${pageName} (${width}px, ${theme}):`, err.message);
    reportFindings.push({
      pageName,
      path,
      width,
      theme,
      screenshot: "FAILED",
      issues: [{ type: "navigation-error", detail: err.message }],
    });
  } finally {
    await page.close();
  }
}

const steps = [
  // 1. Home
  { name: "home", path: "/", ready: ".park-home-root, .park-home-top", action: null },
  // 1b. Home with plan
  {
    name: "home-plan",
    path: "/",
    ready: ".park-home-root, .park-home-top",
    action: async (page) => {
      const makeWorldBtn = page.getByRole("button", { name: "Make a world" });
      if (await makeWorldBtn.count()) {
        await makeWorldBtn.click();
        await page.waitForTimeout(300);
      }
      const input = page.getByRole("textbox", { name: "Describe your task" });
      if (await input.count()) {
        await input.fill("Prepare Q4 revenue projection summary and slide deck");
        const btn = page.getByRole("button", { name: "Start task" });
        if (await btn.count()) {
          await btn.click();
          await page.locator(".park-home-plan").waitFor({ state: "visible", timeout: 8000 }).catch(() => {});
        }
      }
    },
  },
  // 2. World (Story tab)
  { name: "world-story", path: "/world/k1", ready: ".park-world-root", action: async (page) => {
    const tab = page.locator("#park-world-tab-story");
    if (await tab.count()) await tab.click();
  }},
  // 2b. World (Steps tab)
  { name: "world-steps", path: "/world/k1", ready: ".park-world-root", action: async (page) => {
    const tab = page.locator("#park-world-tab-steps");
    await tab.waitFor({ state: "visible", timeout: 8000 }).catch(() => {});
    if (await tab.count()) {
      await tab.click();
      await page.locator("#park-world-panel-steps").waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
    }
  }},
  // 2c. World (Result tab)
  { name: "world-result", path: "/world/k1", ready: ".park-world-root", action: async (page) => {
    const tab = page.locator("#park-world-tab-result");
    await tab.waitFor({ state: "visible", timeout: 8000 }).catch(() => {});
    if (await tab.count()) {
      await tab.click();
      await page.locator("#park-world-panel-result").waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
    }
  }},
  // 2d. World (Trace tab / lens)
  { name: "world-trace", path: "/world/w_village_basic/trace", ready: "[data-testid='trace-lens']", action: null },
  // 2e. World (Tilo browser panel)
  { name: "world-browser-panel", path: "/world/k1", ready: ".park-world-root", action: async (page) => {
    // Check if browser panel trigger exists
    const b = page.locator(".park-browser-panel, [data-testid='browser-panel']");
    if (await b.count() === 0) {
      // Look for button or check
    }
  }},
  // 3. Worlds
  { name: "worlds", path: "/worlds", ready: ".park-worlds-root", action: null },
  // 4. Skills list
  { name: "skills-list", path: "/skills", ready: ".park-skills-root", action: null },
  // 4b. Skills - a skill
  { name: "skills-skill", path: "/skills", ready: ".park-skills-root", action: async (page) => {
    const skillBtn = page.locator(".park-skills-card2").first();
    await skillBtn.waitFor({ state: "visible", timeout: 8000 }).catch(() => {});
    if (await skillBtn.count()) {
      await skillBtn.click();
      await page.locator(".park-skill-drawer, .park-sheet").last().waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
    }
  }},
  // 4c. Skills - Teach Tilo
  { name: "skills-teach", path: "/skills", ready: ".park-skills-root", action: async (page) => {
    const teachBtn = page.getByRole("button", { name: "+ Teach Tilo a skill" });
    await teachBtn.waitFor({ state: "visible", timeout: 8000 }).catch(() => {});
    if (await teachBtn.count()) {
      await teachBtn.click();
      await page.waitForTimeout(600);
    }
  }},
  // 5. Chat
  { name: "chat", path: "/chat", ready: ".park-chat-page, [data-testid='park-page-chat']", action: null },
  // 6. Agenda
  { name: "agenda", path: "/agenda", ready: ".park-agenda-root, .park-agenda-head", action: null },
  // 7. Needs you
  { name: "needs", path: "/needs", ready: ".park-needs-root, [data-testid='park-page-needs']", action: null },
  // 8. Ledger
  { name: "ledger", path: "/ledger", ready: ".park-ledger-root, [data-testid='park-page-ledger']", action: null },
  // 9. Team
  { name: "team", path: "/team", ready: ".park-team-root, [data-testid='park-page-team']", action: null },
  // 10. Connectors
  { name: "connectors", path: "/connectors", ready: ".park-connectors-root, [data-testid='park-page-connectors']", action: null },
  // 11. Settings
  { name: "settings", path: "/settings", ready: ".park-settings-root, [data-testid='park-page-settings']", action: null },
];

for (const width of [1440, 390]) {
  for (const theme of ["light", "dark"]) {
    console.log(`\n=== Running viewport ${width}px, theme: ${theme} ===`);
    const context = await browser.newContext({
      viewport: { width, height: width === 390 ? 844 : 900 },
      deviceScaleFactor: 1,
    });
    await context.addInitScript((t) => {
      localStorage.setItem("tilo.time", t === "dark" ? "night" : "day");
      sessionStorage.setItem("tilo-boot-seen", "1");
    }, theme);

    for (const step of steps) {
      await captureStep(context, step.path, step.name, step.ready, step.action, width, theme);
    }
    await context.close();
  }
}

await browser.close();

writeFileSync(resolve(EVIDENCE_DIR, "findings.json"), JSON.stringify(reportFindings, null, 2));
console.log("\nSweep complete! Findings written to findings.json");
