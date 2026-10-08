// @vitest-environment happy-dom
// FR-HIL-12 wiring: /share/<token> is a kept address with its own screen, and while the page is open no request
// it makes may carry the address as a Referer (the token is in the path).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../test-support/park/componentsHarness";
import { isKeptPath } from "../keptPaths";
import { matchScreen } from "../screens/routes";
import { SharePage } from "./SharePage";

afterEach(cleanup);

const TOKEN = "Ab_1-".repeat(9);
const http = { getJson: vi.fn(async () => Promise.reject(new Error("x"))), postJson: vi.fn() };

describe("FR_HIL_12 wiring", () => {
  it("FR_HIL_12 /share/<token> is owned by the old app and has a screen; /share alone, a longer path and Park paths are not", () => {
    expect(isKeptPath(`/share/${TOKEN}`)).toBe(true);
    expect(isKeptPath(`/share/${TOKEN}/`)).toBe(true);
    for (const p of ["/share", "/share/", `/share/${TOKEN}/answer`, "/shared/x", "/worlds"])
      expect(isKeptPath(p), p).toBe(false);
    expect(matchScreen(`/share/${TOKEN}`)?.id).toBe("share");
    expect(matchScreen("/share")).toBeNull();
    expect(matchScreen(`/share/${TOKEN}/answer`)).toBeNull();
  });

  it("FR_HIL_12 while the page is open the document asks for no referrer, and the ask goes with the page", () => {
    const metas = () => document.head.querySelectorAll('meta[name="referrer"]');
    expect(metas()).toHaveLength(0);
    mount(<SharePage http={http} token={TOKEN} />);
    expect(metas()).toHaveLength(1);
    expect(metas()[0]?.getAttribute("content")).toBe("no-referrer");
    cleanup();
    expect(metas()).toHaveLength(0);
  });
});

describe("FR_HIL_12 the assistant never gets the token", () => {
  it("FR_HIL_12 the assistant context for a shared link has a plain label and no token in the route", async () => {
    const { contextOf } = await import("../assistant/context");
    const ctx = contextOf(`/share/${TOKEN}`, null);
    expect(ctx.label).toBe("Shared request");
    expect(ctx.route).toBe("/share");
    expect(JSON.stringify(ctx)).not.toContain(TOKEN);
  });
});
