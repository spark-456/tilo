// WEB-CUTOVER: S-01 is replaced by the Park Home (its composer is covered in park-home.spec.ts). What stays is the
// intake itself, FR-INT-01 (up to 10 files, one submit, the server's wording), because the Home composer is not
// wired to it yet (plan WEB-13): it runs on INTAKE_PATH (support/intake.ts). The S-01 layout tests (one primary,
// chips, the preview scene, tag sizes, slow-client shifts) are removed with the screen.
import { type Page, expect, test } from "@playwright/test";
import { INTAKE_PATH } from "../support/intake";
import { DESKTOP, MOBILE } from "../support/viewports";

const pdf = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4 fixture"),
});

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") errors.push(msg.text());
  });
  return errors;
}

for (const viewport of [DESKTOP, MOBILE]) {
  const size = `${viewport.width}x${viewport.height}`;

  test(`FR-INT-01 S_01: text plus 3 files submits once and lands on Understanding at ${size}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const errors = watchConsole(page);
    await page.goto(INTAKE_PATH);
    await page.getByLabel("Describe your task").fill("Compare the three supplier quotes");
    await page
      .locator('input[type="file"]')
      .setInputFiles([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")]);
    await expect(
      page.getByRole("list", { name: "Attached files" }).getByRole("listitem"),
    ).toHaveCount(3);
    await page.getByRole("button", { name: "Start task", exact: true }).dblclick(); // one submit
    await expect(page.getByRole("heading", { level: 1, name: "Understanding" })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/task/task_fixture_1/understanding");
    expect(errors).toEqual([]);
  });

  test(`FR-INT-01 S_01: an 11th file shows the server's wording and blocks Start at ${size}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto(INTAKE_PATH);
    await page.getByLabel("Describe your task").fill("task");
    const eleven = Array.from({ length: 11 }, (_, i) => pdf(`f${i}.pdf`));
    await page.locator('input[type="file"]').setInputFiles(eleven);
    await expect(page.getByRole("alert").first()).toHaveText("11 files attached; the limit is 10.");
    await expect(page.getByRole("button", { name: "Start task", exact: true })).toBeDisabled();
  });
}
