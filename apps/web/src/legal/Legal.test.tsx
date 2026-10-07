// @vitest-environment happy-dom
// WEB-LEGAL: /privacy and /terms render through Root without sign-in, without the Park or old app and without a
// network call; headings, the contact address, the Limited Use sentence and the scopes are on the page.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q, qa } from "../../test-support/park/componentsHarness";
import { LIMITED_USE, SCOPES } from "./content";
import { legalKind } from "./legalPaths";

const loaded = vi.hoisted(() => ({ park: 0, old: 0 }));
vi.mock("../App", () => {
  loaded.old += 1;
  return { App: () => null };
});
vi.mock("../park/app/ParkApp", () => {
  loaded.park += 1;
  return { default: () => null };
});

import { Root } from "../Root";

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};
const visit = async (path: string) => {
  window.history.pushState({}, "", path);
  const m = mount(<Root />);
  await settle();
  return m;
};

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  vi.restoreAllMocks();
});

describe("WEB_LEGAL_paths: only /privacy and /terms", () => {
  it.each([
    ["/privacy", "privacy"],
    ["/privacy/", "privacy"],
    ["/terms", "terms"],
    ["/terms/", "terms"],
    ["/privacy/x", null],
    ["/terms-of-use", null],
    ["/", null],
  ])("WEB_LEGAL_paths_%s", (path, kind) => {
    expect(legalKind(path)).toBe(kind);
  });
});

describe("WEB_LEGAL_privacy_page", () => {
  it("WEB_LEGAL_privacy_page_renders_without_sign_in", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const m = await visit("/privacy");
    expect(q(m.container, '[data-testid="legal-privacy"]')).toBeTruthy();
    expect(q(m.container, "h1")?.textContent).toBe("Tilo privacy policy");
    expect(qa(m.container, "h2").length).toBeGreaterThanOrEqual(6);
    expect(qa(m.container, '[data-testid="park-not-found"]')).toHaveLength(0);
    expect(loaded.park + loaded.old).toBe(0);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(document.title).toBe("Tilo privacy policy · Tilo");
    vi.unstubAllGlobals();
  });

  it("WEB_LEGAL_privacy_page_has_the_contact_email_the_limited_use_sentence_and_every_scope", async () => {
    const m = await visit("/privacy");
    const text = m.container.textContent ?? "";
    expect(text).toContain("tilotesting@gmail.com");
    expect(
      qa<HTMLAnchorElement>(m.container, "a").some(
        (a) => a.getAttribute("href") === "mailto:tilotesting@gmail.com",
      ),
    ).toBe(true);
    expect(text).toContain(LIMITED_USE);
    expect(text).toContain("Google API Services User Data Policy, including the Limited Use");
    expect(SCOPES.length).toBe(6);
    for (const s of SCOPES) expect(text, s.scope).toContain(s.scope);
    expect(text).toContain("https://myaccount.google.com/permissions");
    expect(text).toContain("asia-southeast1");
    expect(text).toContain("never sees your password");
  });

  it("WEB_LEGAL_privacy_page_scopes_match_config_connectors", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const yaml = readFileSync(resolve(__dirname, "../../../../config/connectors.yaml"), "utf8");
    const declared = new Set(
      (yaml.match(/https:\/\/www\.googleapis\.com\/auth\/[a-z.]+/g) ?? []).map((u) => u.split("/auth/")[1]),
    );
    expect(declared.size).toBe(6);
    expect(new Set(SCOPES.map((s) => s.scope))).toEqual(declared);
  });
});

describe("WEB_LEGAL_terms_page", () => {
  it("WEB_LEGAL_terms_page_renders_without_sign_in_with_headings_and_contact", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const m = await visit("/terms");
    expect(q(m.container, "h1")?.textContent).toBe("Tilo terms of use");
    expect(qa(m.container, "h2").length).toBeGreaterThanOrEqual(5);
    expect(m.container.textContent).toContain("tilotesting@gmail.com");
    expect(m.container.textContent).toContain("as is");
    expect(loaded.park + loaded.old).toBe(0);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("WEB_LEGAL_page_structure_one_h1_one_main_links_have_hrefs", async () => {
    for (const path of ["/privacy", "/terms"]) {
      const m = await visit(path);
      expect(qa(m.container, "h1"), path).toHaveLength(1);
      expect(qa(m.container, "main"), path).toHaveLength(1);
      expect(qa(m.container, "[style]"), "no inline styles (CSP)").toHaveLength(0);
      for (const a of qa<HTMLAnchorElement>(m.container, "a"))
        expect(a.getAttribute("href"), a.textContent ?? "").toBeTruthy();
      m.unmount();
    }
  });
});
