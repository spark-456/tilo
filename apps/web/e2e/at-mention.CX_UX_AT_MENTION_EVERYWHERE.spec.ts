import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { expect, test } from "@playwright/test";

const screenshot = resolve(
  process.cwd(),
  "../../agy-bridge/evidence/AT-MENTION-EVERYWHERE/chat-picker.png",
);

test("CX_UX_AT_MENTION_EVERYWHERE Chat opens the grouped fixture skill picker", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/v1/skills/catalog", (route) =>
    route.fulfill({
      json: {
        skills: [
          {
            id: "mine-notes",
            kind: "taught",
            scope: "mine",
            name: "Meeting notes",
            purpose: "Turn a conversation into clear notes.",
            inputs: [],
            tools: ["calendar"],
            version: 1,
          },
          {
            id: "team-brief",
            kind: "taught",
            scope: "team",
            name: "Team brief",
            purpose: "Summarize work for your team.",
            inputs: [],
            tools: ["write_document"],
            version: 1,
          },
          {
            id: "library-research",
            kind: "library",
            scope: "library",
            name: "Research brief",
            purpose: "Research and summarize public sources.",
            inputs: [],
            tools: ["browser"],
            version: "1.0.0",
          },
        ],
      },
    }),
  );

  await page.goto("/chat");
  await page.getByRole("combobox", { name: "Ask a question" }).fill("@");
  const list = page.getByRole("listbox", { name: "Skills" });
  await expect(list).toBeVisible();
  await expect(list.getByRole("group", { name: "Mine" })).toBeVisible();
  await expect(list.getByRole("group", { name: "Team" })).toBeVisible();
  await expect(list.getByRole("group", { name: "Library" })).toBeVisible();
  await expect(list.getByRole("option")).toHaveCount(3);
  await expect(list.locator("img")).toHaveCount(3);

  mkdirSync(dirname(screenshot), { recursive: true });
  await page.screenshot({ path: screenshot });
});
