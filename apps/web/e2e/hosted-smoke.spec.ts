// W22: the hosted release smoke. The 13 Oct hosting regression (a build with no Firebase web config showed
// "Sign-in is off") slipped past a smoke that said "signedin SKIP"; this spec looks at what a person sees on
// a deployed site: the signed-out gate, then a demo session through Home, Worlds, a world and Settings.
//
// It needs a real deployment, so it runs only when TILO_SMOKE_URL is set (skipped otherwise: dev and CI never
// reach the network) and only through its own config, which starts no dev server:
//   TILO_SMOKE_URL=https://<hosting origin> just smoke-hosted
// Optional: TILO_SMOKE_ALLOW=<regex,regex> adds URL patterns whose >=400 answers are expected.
// Nothing here signs in with a real account, sends anything or starts a run: the demo session replays records.
import { type Page, expect, test } from "@playwright/test";
import { isHostNoiseUrl } from "./support/console";

const URL_UNDER_TEST = process.env.TILO_SMOKE_URL ?? "";

/** Answers >= 400 a healthy deployment gives: the browser's own favicon probe and the signed-out session probes. */
const ALLOWED_STATUS_URLS: RegExp[] = [
  /\/favicon\.ico(\?|$)/,
  ...(process.env.TILO_SMOKE_ALLOW ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => new RegExp(s)),
];

interface Watch {
  problems: string[];
  messages: string[];
  failures: string[];
}

/** Everything the page logs and every request answered with >= 400 (outside the allowlist). */
function watch(page: Page): Watch {
  const w: Watch = { problems: [], messages: [], failures: [] };
  page.on("console", (m) => {
    if (isHostNoiseUrl(m.location().url)) return;
    w.messages.push(m.text());
    if (m.type() === "error" || m.type() === "warning")
      w.problems.push(`[${m.type()}] ${m.text()}`);
  });
  page.on("pageerror", (e) => w.problems.push(`[pageerror] ${e.message}`));
  page.on("response", (r) => {
    const url = r.url();
    if (r.status() >= 400 && !ALLOWED_STATUS_URLS.some((re) => re.test(url))) {
      w.failures.push(`${r.status()} ${r.request().method()} ${url}`);
    }
  });
  return w;
}

const noSignInOff = async (page: Page, w: Watch) => {
  expect(w.messages.filter((m) => /sign-in is off/i.test(m))).toEqual([]);
  await expect(page.getByText(/sign-in is off/i)).toHaveCount(0);
};

test.describe("hosted release smoke", () => {
  test.skip(!URL_UNDER_TEST, "TILO_SMOKE_URL is not set: the hosted smoke never runs by itself");
  test.use({ baseURL: URL_UNDER_TEST || undefined, viewport: { width: 1440, height: 900 } });

  test("hosted_smoke_signed_out_shows_google_and_demo_with_a_working_firebase_config", async ({
    page,
  }) => {
    const w = watch(page);
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Explore a demo session/ })).toBeVisible();
    await noSignInOff(page, w);
    expect(w.problems, w.problems.join("\n")).toEqual([]);
    expect(w.failures, w.failures.join("\n")).toEqual([]);
  });

  test("hosted_smoke_demo_session_home_worlds_world_and_settings_load", async ({ page }) => {
    const w = watch(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Explore a demo session/ }).click();

    // Home: the page, its composer and what is on it.
    const home = page.getByTestId("park-page-home");
    await expect(home).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Describe your task" })).toBeVisible();
    expect((await home.innerText()).trim().length, "Home has content").toBeGreaterThan(100);

    // Worlds list, then one world.
    await page.goto("/worlds");
    await expect(page.getByTestId("park-page-worlds")).toBeVisible();
    const cards = page.locator(".park-worlds-card");
    await expect(cards.first()).toBeVisible();
    await cards.first().click();
    await expect(page.getByTestId("park-page-world")).toBeVisible();

    // Settings is a page of the Park shell: the main navigation is there and the old shell's pill is not.
    await page.goto("/settings");
    await expect(page.getByRole("navigation", { name: "Main" }).first()).toBeVisible();
    await expect(page.getByText(/Fixture replay/)).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Settings" }).first()).toBeVisible();

    await noSignInOff(page, w);
    expect(w.problems, w.problems.join("\n")).toEqual([]);
    expect(w.failures, w.failures.join("\n")).toEqual([]);
  });
});
