import { expect, it } from "vitest";
import { adminRedirect } from "./adminRedirect";
import { isParkPath, parkPath, parseParkPath } from "./router";

it.each(["/mail", "/team/console", "/connections", "/more"])(
  "OLD-UI-OUT-4b %s belongs to Park",
  (path) => {
    expect(isParkPath(path)).toBe(true);
  },
);
it.each([
  ["/mail", "/team?focus=mail"],
  ["/team/console", "/team?focus=console"],
  ["/connections", "/connectors"],
])("OLD-UI-OUT-4b %s replaces the bookmark, keeping its run", (path, target) => {
  expect(adminRedirect(path)).toBe(target);
  expect(adminRedirect(`${path}/`, "?world=owned&private=drop")).toBe(
    `${target}${target.includes("?") ? "&" : "?"}world=owned`,
  );
  expect(adminRedirect(`${path}/extra`)).toBeNull();
});
it("OLD-UI-OUT-4b Team sections preserve the selected world on navigation", () => {
  expect(parseParkPath("/mail", "?world=owned")).toEqual({
    page: "team",
    params: { focus: "mail", world: "owned" },
  });
  expect(parkPath("team", { focus: "console", world: "owned" })).toBe(
    "/team?focus=console&world=owned",
  );
  expect(parseParkPath("/more", "")).toEqual({ page: "more", params: {} });
});
