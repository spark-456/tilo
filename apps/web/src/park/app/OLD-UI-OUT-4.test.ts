import { expect, it } from "vitest";
import { adminRedirect } from "./adminRedirect";
import { isParkPath, parseParkPath } from "./router";

it.each(["/autonomy", "/channels", "/settings", "/estimate", "/pilot"])(
  "OLD-UI-OUT-4a %s belongs to Park",
  (path) => {
    expect(isParkPath(path)).toBe(true);
  },
);
it.each([
  ["/autonomy", "/settings?section=autonomy"],
  ["/channels", "/settings?section=channels"],
  ["/estimate", "/settings?section=estimate"],
  ["/pilot", "/settings?section=pilot"],
])("OLD-UI-OUT-4a %s redirects to its exact Park home with run context", (path, target) => {
  expect(adminRedirect(`${path}/`)).toBe(target);
  expect(adminRedirect(path, "?world=owned&unexpected=drop")).toBe(
    `${target}${target.includes("?") ? "&" : "?"}world=owned`,
  );
  expect(adminRedirect(`${path}/extra`)).toBeNull();
});
it("OLD-UI-OUT-4a settings section and world context survive routing", () => {
  expect(parseParkPath("/settings", "?section=autonomy&world=owned")).toEqual({
    page: "settings",
    params: { section: "autonomy", world: "owned" },
  });
});
