import { readFileSync } from "node:fs";
import { type Page, expect, test } from "@playwright/test";
import { isHostNoiseStack, isHostNoiseUrl } from "./support/console";

// UX-AUDIT (21 Oct): on every Park page, each visible control in the page itself (the shell is checked on Home) is
// clicked once in a fresh load of the fixture app, and it must respond: the address changes, the page changes, a
// request goes out, or a file or tab opens. A control already in the state it selects (aria-pressed, -checked,
// -selected, -current, or an "--on" class) may do nothing. No click may log a console error or throw. Text fields
// and selects are typed into elsewhere; a disabled control is skipped but must say why (a title, or a described-by
// line) unless it is a step control at its end (Previous at the first item, Zoom at its limit).
//
// Run on a production preview (each fresh load is ~30x faster than on the dev server; about 1 min per page):
//   TILO_WEB_PROD=1 TILO_WEB_PORT=<own port> pnpm exec playwright test e2e/ux-audit.every-control.spec.ts
//   --project=chromium --no-deps --workers=1

const PAGES = [
  "/",
  "/chat",
  "/worlds",
  "/world/k1",
  "/skills",
  "/needs",
  "/ledger",
  "/agenda",
  "/team",
  "/connectors",
  "/profile",
  "/settings",
  "/library",
  "/more",
] as const;

/** At most this many distinct controls per page, so one page stays under a minute on a busy laptop. */
const PER_PAGE = 24;
const CONTROLS =
  'button, a[href], [role="button"], [role="tab"], [role="menuitem"], [role="switch"], [role="checkbox"], [role="radio"], summary, input[type="checkbox"], input[type="radio"]';

/** Step controls that are disabled at their end of a range: their state is the explanation. */
const AT_LIMIT = /^(Previous|Next) (decision|week|day|month)$|^Zoom (in|out)$/;
/** Controls that rightly do nothing in a fresh load: already there (Today), nothing to reset (New chat, Cancel). */
const NOTHING_TO_DO = /^(Today|New chat|Cancel)$/;
const DOWNLOADS = /^(Export CSV|Download)$/;

interface Control {
  path: string;
  name: string;
  disabled: boolean;
  why: boolean;
  selected: boolean;
}

/** Paths already loaded once: later loads come from the cache and only need a short settle. */
const warm = new Set<string>();

async function freshPage(page: Page, path: string) {
  await page.goto(path);
  await page.locator("main").first().waitFor();
  if (!warm.has(path)) {
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
    warm.add(path);
  }
  await page.waitForTimeout(300);
}

function controlsOf(page: Page, withShell: boolean): Promise<Control[]> {
  return page.evaluate(
    ({ sel, withShell }) => {
      const pathOf = (el: Element): string => {
        const parts: string[] = [];
        let e: Element | null = el;
        while (e && e !== document.body && e.parentElement) {
          const parent: Element = e.parentElement;
          const tag = e.tagName;
          const same = [...parent.children].filter((c) => c.tagName === tag);
          parts.unshift(`${tag.toLowerCase()}:nth-of-type(${same.indexOf(e) + 1})`);
          e = parent;
        }
        return `body > ${parts.join(" > ")}`;
      };
      const out: Control[] = [];
      const names = new Set<string>();
      for (const el of document.querySelectorAll<HTMLElement>(sel)) {
        if (!el.checkVisibility({ visibilityProperty: true } as CheckVisibilityOptions)) continue;
        if (el.closest('[aria-hidden="true"], [inert]')) continue;
        const shell = el.closest(".park-shell__nav, .park-bubble, .park-bubble__panel") !== null;
        if (shell && !withShell) continue;
        const label = el instanceof HTMLInputElement ? (el.labels?.[0]?.innerText ?? "") : "";
        const name = (el.getAttribute("aria-label") || el.innerText || label || el.title || "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 80);
        const key = `${el.tagName}|${name}`;
        if (names.has(key)) continue;
        names.add(key);
        const disabled =
          (el as HTMLButtonElement).disabled === true ||
          el.getAttribute("aria-disabled") === "true";
        out.push({
          path: pathOf(el),
          name,
          disabled,
          why: Boolean(el.title || el.getAttribute("aria-describedby")),
          selected:
            ["aria-pressed", "aria-checked", "aria-selected"].some(
              (a) => el.getAttribute(a) === "true",
            ) ||
            el.hasAttribute("aria-current") ||
            (el instanceof HTMLInputElement && el.checked) ||
            (el instanceof HTMLAnchorElement && el.href === location.href) ||
            /(--on|--active|is-active)\b/.test(String(el.className)),
        });
      }
      return out;
    },
    { sel: CONTROLS, withShell },
  );
}

for (const path of PAGES) {
  test(`UX_AUDIT every control on ${path} responds without a console error`, async ({ page }) => {
    test.setTimeout(360_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript(() => {
      try {
        sessionStorage.setItem("tilo-boot-seen", "1");
      } catch {
        // storage blocked: the boot cover plays, the page still loads
      }
    });
    const errors: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error" && !isHostNoiseUrl(m.location().url)) errors.push(m.text());
    });
    page.on("pageerror", (e) => {
      if (!isHostNoiseStack(e.stack)) errors.push(e.message);
    });
    page.on("dialog", (d) => void d.dismiss());

    await freshPage(page, path);
    const controls = (await controlsOf(page, path === "/")).slice(0, PER_PAGE);
    expect(controls.length, `${path} has controls`).toBeGreaterThan(0);
    const problems: string[] = [];
    for (const c of controls) {
      if (c.disabled) {
        if (!c.why && !AT_LIMIT.test(c.name))
          problems.push(`"${c.name}" is disabled and says nothing`);
        continue;
      }
      if (!c.name) problems.push(`a control at ${c.path} has no name`);
      // A file download is checked by its own test below: an unfinished download holds the next navigation.
      if (DOWNLOADS.test(c.name)) continue;
      await freshPage(page, path);
      const target = page.locator(c.path);
      if ((await target.count()) !== 1) continue; // laid out differently after a fresh load
      const before = page.url();
      await page.evaluate(() => {
        const w = window as unknown as { __uxMut: number; __uxFocus: Element | null };
        w.__uxMut = 0;
        w.__uxFocus = document.activeElement;
        // A native radio or checkbox changes a property, not an attribute: its change event counts as a response.
        for (const type of ["change", "input"])
          document.addEventListener(type, () => {
            w.__uxMut += 1;
          });
        new MutationObserver((list) => {
          w.__uxMut += list.length;
        }).observe(document.body, {
          subtree: true,
          childList: true,
          attributes: true,
          characterData: true,
        });
      });
      let requests = 0;
      const onRequest = () => {
        requests += 1;
      };
      page.on("request", onRequest);
      const opened = page
        .context()
        .waitForEvent("page", { timeout: 900 })
        .catch(() => null);
      const saved = page.waitForEvent("download", { timeout: 900 }).catch(() => null);
      const seen = errors.length;
      try {
        await target.click({ timeout: 3_000 });
      } catch (e) {
        problems.push(`"${c.name}" cannot be clicked: ${String(e).split("\n")[0]}`);
        page.off("request", onRequest);
        continue;
      }
      const [tab, file] = await Promise.all([opened, saved]);
      await page.waitForTimeout(400);
      page.off("request", onRequest);
      await tab?.close();
      const changed = await page
        .evaluate((self) => {
          const w = window as unknown as { __uxMut?: number; __uxFocus?: Element | null };
          // Focus moved to another control (Review brings the waiting card into view and focuses it); a click
          // focusing the clicked control itself is not a response.
          const at = document.activeElement;
          const moved =
            w.__uxFocus !== undefined &&
            at !== w.__uxFocus &&
            at !== document.body &&
            at !== document.querySelector(self)
              ? 1
              : 0;
          return (w.__uxMut ?? 1) + moved;
        }, c.path)
        .catch(() => 1); // the page navigated away: that is a response
      const responded = page.url() !== before || changed > 0 || requests > 0 || tab || file;
      if (!responded && !c.selected && !NOTHING_TO_DO.test(c.name))
        problems.push(`"${c.name}" does nothing`);
      for (const e of errors.slice(seen)) problems.push(`"${c.name}" logged: ${e.slice(0, 160)}`);
    }
    expect(problems, problems.join("\n")).toEqual([]);
  });
}

test("UX_AUDIT the skill drawer opens below the nav and its close button closes it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => sessionStorage.setItem("tilo-boot-seen", "1"));
  await freshPage(page, "/skills");
  await page.locator(".park-skills-card2").first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  const nav = await page.locator(".park-shell__nav").boundingBox();
  const head = await drawer.locator("h2").boundingBox();
  expect(head && nav && head.y >= nav.y + nav.height, "the title is not under the nav").toBe(true);
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("UX_AUDIT Ledger Export CSV saves a real CSV file", async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("tilo-boot-seen", "1"));
  await freshPage(page, "/ledger");
  const saving = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await saving;
  expect(file.suggestedFilename()).toMatch(/\.csv$/);
  expect(await file.failure()).toBeNull();
  const text = readFileSync(await file.path(), "utf8");
  expect(text.split("\n")[0]).toContain("Date,Time,Type,Entry");
});

test("UX_AUDIT a page drawer's buttons are not covered by the Tilo bubble", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.addInitScript(() => sessionStorage.setItem("tilo-boot-seen", "1"));
  await freshPage(page, "/connectors");
  await page.locator(".park-connectors-tile").first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  await expect(page.locator(".park-bubble")).toBeHidden();
  const covered = await drawer.evaluate((root) =>
    [...root.querySelectorAll("button")]
      .filter((b) => {
        const r = b.getBoundingClientRect();
        if (r.width === 0 || r.bottom > innerHeight || r.top < 0) return false;
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        // Rows scrolled under the drawer's own sticky footer are fine; anything outside the drawer on top is not.
        return top !== null && !root.contains(top);
      })
      .map((b) => b.textContent?.trim()),
  );
  expect(covered, "buttons under something else").toEqual([]);
});
