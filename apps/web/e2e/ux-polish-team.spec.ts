import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "UX-POLISH-TEAM",
);

const api = "http://127.0.0.1:59999";

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`UX-POLISH-TEAM ${width} ${theme} has polished controls and no overlap`, async ({
      page,
    }) => {
      mkdirSync(evidence, { recursive: true });
      await page.route(`${api}/**`, async (route) => {
        const path = new URL(route.request().url()).pathname;
        const body =
          path === "/v1/people"
            ? {
                you: "u_me",
                people: [
                  { id: "u_me", display_name: "Mina Shah", org_role: "owner" },
                  { id: "u_ben", display_name: "Ben Ortiz", org_role: "member" },
                ],
              }
            : path === "/v1/teams"
              ? {
                  you: "u_me",
                  teams: [
                    { team: "tm_launch", name: "Launch crew", lead: true, state: "member" },
                    { team: "tm_finance", name: "Finance", lead: false, state: "member" },
                  ],
                }
              : path === "/v1/teams/tm_launch"
                ? {
                    members: [
                      { id: "u_me", display_name: "Mina Shah", lead: true, role: "owner" },
                      { id: "u_ben", display_name: "Ben Ortiz", lead: false, role: "editor" },
                    ],
                  }
                : {
                    members: [{ id: "u_lee", display_name: "Lee Chen", lead: true, role: "owner" }],
                  };
        await route.fulfill({ json: body });
      });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/team");
      await expect(page.getByRole("heading", { name: "Team", exact: true })).toBeVisible({
        timeout: 10_000,
      });
      if (theme === "dark")
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      await expect(page.getByRole("navigation", { name: "Choose a team" })).toBeVisible();
      await expect(page.getByTestId("team-member-u_ben")).toContainText("Editor");
      await expect(
        page.getByText("The invitation waits for your approval before it is sent."),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}-Team.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
