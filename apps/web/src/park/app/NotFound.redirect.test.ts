import { describe, expect, it } from "vitest";
import { adminRedirect } from "./adminRedirect";

describe("M1_NOTFOUND_1 canonical addresses", () => {
  it.each([
    ["/index.html", "?task=keep", "/?task=keep"],
    ["/index.html/", "", "/"],
    ["/worlds/", "?q=plan", "/worlds?q=plan"],
    ["/world/owned/stage/", "", "/world/owned/stage"],
    ["/park/worlds/", "", "/park/worlds"],
    ["/no-such-page/", "", "/no-such-page"],
    ["/worlds", "", null],
    ["/", "", null],
  ])("canonicalizes %s", (path, search, expected) => {
    expect(adminRedirect(path, search)).toBe(expected);
  });
});
