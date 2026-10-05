// Issue #227 S-04 (PRD 18.3 HUD, 9.4 HR-1, FR-MTR-06): the HUD says what the run on screen says.
// Fixture mode reads the replay the stage shows (not the client's own, not-yet-started log); the
// meter carries the credits saved by memory; a phone shows the HUD at a glance while the status
// sheet is closed, and its World card no longer covers the stage. Zero layout shift across the
// whole route replay at 1440x900 and 390x844.
import { expect, test } from "@playwright/test";
import { readShifts, watchShifts } from "./support/shifts";
import { DESKTOP, MOBILE } from "./support/viewports";
import { stageSeq } from "./support/world";

const W = "/world/w_village_basic";
const AT = (seq: number) => `${W}?fixture=village-basic&seq=${seq}`;

test.describe("desktop", () => {
  test.use({ viewport: DESKTOP });

  test("#227 S-04 fixture replay: the meter follows the seq on the stage, not an idle log", async ({
    page,
  }) => {
    await page.goto(AT(8));
    await expect.poll(() => stageSeq(page)).toBe(8);
    await expect(page.getByTestId("hud-meter")).toContainText("The run has not started");
    await page.goto(AT(20));
    await expect.poll(() => stageSeq(page)).toBe(20);
    await expect(page.getByTestId("hud-meter")).toContainText("Working");
    await page.goto(AT(44));
    await expect.poll(() => stageSeq(page)).toBe(44);
    const meter = page.getByTestId("hud-meter");
    await expect(meter).toContainText("Done");
    await expect(meter).toContainText("credits of 40 approved");
    await expect(meter).not.toContainText("has not started");
  });

  test("FR-MTR-06 the meter shows credits saved by memory (0 when the run reused nothing)", async ({
    page,
  }) => {
    await page.goto(AT(44));
    await expect.poll(() => stageSeq(page)).toBe(44);
    await expect(page.getByTestId("memory-saved")).toContainText("0");
    await expect(page.getByTestId("memory-saved")).toContainText("credits saved by memory");
  });
});

test.describe("phone", () => {
  test.use({ viewport: MOBILE });

  test("#227 S-04 phone: the closed World status sheet shows status, credits and approvals", async ({
    page,
  }) => {
    await page.goto(AT(20));
    await expect.poll(() => stageSeq(page)).toBe(20);
    const glance = page.getByTestId("hud-glance");
    await expect(glance).toBeVisible();
    await expect(glance).toContainText("Working");
    await expect(glance).toContainText("credits");
    await expect(glance).toContainText("nothing waiting");
    // Still a 44 px target that opens the full panels.
    const box = await page.locator(".hud-sheet summary").boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    await page.getByText("World status").click();
    await expect(page.getByTestId("hud-meter")).toBeVisible();
  });

  test("#227 S-04 phone: the World card is a slim row and leaves the world in view", async ({
    page,
  }) => {
    await page.goto(`${W}?speed=1000`);
    await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBe(44);
    const card = await page.getByTestId("flow-shell").boundingBox();
    expect(card?.height ?? 999).toBeLessThanOrEqual(80);
    await expect(page.getByRole("button", { name: "View delivery" })).toBeVisible();
  });

  test("PRD 18.6 phone: zero layout shift across the route replay, the HUD line included", async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await watchShifts(page);
    await page.goto(`${W}?speed=100`);
    await expect.poll(() => stageSeq(page), { timeout: 30_000 }).toBe(44);
    await expect(page.getByTestId("hud-glance")).toContainText("Done");
    expect(await readShifts(page)).toEqual([]);
  });
});

test("PRD 18.6 desktop: zero layout shift across the route replay, the meter's third figure included", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize(DESKTOP);
  await watchShifts(page);
  await page.goto(`${W}?speed=100`);
  await expect.poll(() => stageSeq(page), { timeout: 30_000 }).toBe(44);
  await expect(page.getByTestId("hud-meter")).toContainText("Done");
  await expect(page.getByTestId("memory-saved")).toBeVisible();
  expect(await readShifts(page)).toEqual([]);
});
