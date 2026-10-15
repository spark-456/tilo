// @vitest-environment happy-dom
// STUDIO-6: the other signed-out screens still render, now in the Studio theme: the sign-up question and the
// under-construction notice (SEC-15), the access check that failed, the legal pages and the OAuth callback. Their
// behaviour is covered by their own SEC-15, WEB-LEGAL and ADR-0035 tests; this checks they render and are Studio.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q, qa } from "../../test-support/park/componentsHarness";
import { AccessLayer } from "../access/AccessLayer";
import { SignUpDeclaration } from "../access/SignUpDeclaration";
import { UnderConstruction } from "../access/UnderConstruction";
import LegalPage from "../legal/LegalPage";
import CallbackPage from "../oauth/CallbackPage";

afterEach(cleanup);

const studio = () => q<HTMLElement>(document.body, '[data-park][data-theme="studio"]');

describe("STUDIO_6 the signed-out screens render in Studio", () => {
  it.each([
    ["declaration", () => <SignUpDeclaration onSubmit={() => undefined} />, "sign-up-declaration"],
    ["under construction", () => <UnderConstruction />, "under-construction"],
    ["privacy", () => <LegalPage kind="privacy" />, "legal-privacy"],
    ["terms", () => <LegalPage kind="terms" />, "legal-terms"],
    [
      "oauth callback",
      () => <CallbackPage params={null} flow={() => null} back={() => undefined} />,
      "oauth-callback",
    ],
  ])("STUDIO_6 %s still renders, in the Studio theme, with the tilo logo", (_, ui, testid) => {
    mount(ui());
    expect(q(document.body, `[data-testid="${testid}"]`)).not.toBeNull();
    expect(studio()).not.toBeNull();
    expect(["day", "night"]).toContain(studio().dataset.time);
    expect(q(document.body, '[aria-label^="tilo"]')).not.toBeNull();
    expect(qa(document.body, "h1")).toHaveLength(1);
    expect(qa(document.body, "input[type=password]")).toHaveLength(0);
  });

  it("STUDIO_6 a failed access check is a Studio card with its one Try again", async () => {
    const http = {
      getJson: vi.fn(() => Promise.reject(new Error("offline"))),
      postJson: vi.fn(),
    };
    mount(
      <AccessLayer http={http}>
        <div data-testid="app" />
      </AccessLayer>,
    );
    await act(async () => undefined);
    expect(q(document.body, '[data-testid="access-failed"]')).not.toBeNull();
    expect(studio()).not.toBeNull();
    expect(document.querySelector('[data-testid="app"]')).toBeNull();
    const tryAgain = qa<HTMLButtonElement>(document.body, "button").filter(
      (b) => b.textContent === "Try again",
    );
    expect(tryAgain).toHaveLength(1);
  });
});
