import { expect, it } from "vitest";
import { isKeptPath } from "../../keptPaths";
import { adminRedirect } from "./adminRedirect";
import { isParkPath, parseParkPath } from "./router";

it.each([
  "/autonomy",
  "/channels",
  "/settings",
  "/estimate",
  "/pilot",
  "/mail",
  "/team/console",
  "/connections",
  "/more",
])("OLD-UI-OUT-4 %s belongs to Park, never the old shell", (path) => {
  expect(isParkPath(path)).toBe(true);
  expect(isKeptPath(path)).toBe(false);
});
it.each([
  ["/autonomy", "/settings?section=autonomy"],
  ["/channels", "/settings?section=channels"],
  ["/mail", "/settings?section=mail"],
  ["/estimate", "/settings?section=estimate"],
  ["/pilot", "/settings?section=pilot"],
  ["/connections", "/connectors"],
  ["/team/console", "/team?focus=console"],
])("OLD-UI-OUT-4 %s redirects to its exact Park home with run context", (path, target) => {
  expect(adminRedirect(`${path}/`)).toBe(target);
  expect(adminRedirect(path, "?world=owned&unexpected=drop")).toBe(
    `${target}${target.includes("?") ? "&" : "?"}world=owned`,
  );
  expect(adminRedirect(`${path}/extra`)).toBeNull();
});
it("OLD-UI-OUT-4 settings section and world context survive routing", () => {
  expect(parseParkPath("/settings", "?section=mail&world=owned")).toEqual({
    page: "settings",
    params: { section: "mail", world: "owned" },
  });
});
