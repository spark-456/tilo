import { expect, test } from "@playwright/test";

// Serve only a test document: renders the real components without Google credentials or API calls.
for (const width of [1440, 390]) {
  for (const time of ["day", "night"]) {
    test(`SEC-15 Park access ${width} ${time}: layout, native radio keys and visitor notice`, async ({
      page,
    }, info) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.route("**/access-qa", (route) =>
        route.fulfill({
          contentType: "text/html",
          body: `<html><body><div id="root"></div><script type="module">
          import React from '/node_modules/.vite/deps/react.js';
          import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
          import RefreshRuntime from '/@react-refresh';
          RefreshRuntime.injectIntoGlobalHook(window);
          window.$RefreshReg$ = () => {};
          window.$RefreshSig$ = () => type => type;
          window.__vite_plugin_react_preamble_installed__ = true;
          const { SignUpDeclaration } = await import('/src/access/SignUpDeclaration.tsx');
          const { UnderConstruction } = await import('/src/access/UnderConstruction.tsx');
          const root = ReactDOM.createRoot(document.getElementById('root'));
          root.render(React.createElement(SignUpDeclaration, {onSubmit: d => {
            window.answer = d; root.render(React.createElement(UnderConstruction));
          }}));
        </script></body></html>`,
        }),
      );
      await page.goto("/access-qa");
      const screen = page.locator("main.park-access");
      await expect(page.getByRole("heading", { name: "One quick question" })).toBeVisible();
      if (time === "night")
        await page.getByRole("button", { name: "Switch to the night city" }).click();
      await expect(screen).toHaveAttribute("data-time", time);
      await expect(page.locator(".park-shell__scene")).toBeVisible();
      const submit = page.getByRole("button", { name: "Continue", exact: true });
      await expect(submit).toBeDisabled();
      const visitor = page.getByRole("radio", { name: /^I am a visitor/ });
      const judge = page.getByRole("radio", { name: /^I am a Google AI Builder Cup judge/ });
      await visitor.focus();
      await expect(visitor).toBeFocused();
      await page.keyboard.press("Space");
      await page.keyboard.press("ArrowDown");
      await expect(judge).toBeChecked();
      await expect(judge).toBeFocused();
      await page.keyboard.press("ArrowUp");
      await expect(visitor).toBeChecked();
      await expect(submit).toBeEnabled();
      expect(
        await page
          .locator(".park-access__choice")
          .first()
          .evaluate((el) => getComputedStyle(el).outlineStyle),
      ).toBe("solid");
      const bounds = await page.locator(".park-access__card").boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds?.x).toBeGreaterThanOrEqual(0);
      expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(width);
      expect(await screen.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
      expect(
        await screen.evaluate((el) => getComputedStyle(el).getPropertyValue("--ink").trim()),
      ).toBe(time === "day" ? "#1F1D2B" : "#F4F2FA");
      await page.screenshot({ path: info.outputPath(`declaration-${width}-${time}.png`) });
      await page.keyboard.press("Tab");
      await expect(submit).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("under-construction")).toBeVisible();
      expect(await page.evaluate(() => Reflect.get(window, "answer"))).toBe("visitor");
      if (time === "night" && (await screen.getAttribute("data-time")) !== "night") {
        await page.getByRole("button", { name: "Switch to the night city" }).click();
      }
      await expect(page.getByRole("radio")).toHaveCount(0);
      await expect(page.locator("a, input, textarea, button[type=submit]")).toHaveCount(0);
      expect(await screen.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath(`notice-${width}-${time}.png`) });
      expect(errors).toEqual([]);
    });
  }
}
