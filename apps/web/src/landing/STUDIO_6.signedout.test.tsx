// @vitest-environment happy-dom
// STUDIO-6: the other signed-out screens still render, now in the Studio theme: the legal pages and the OAuth callback.
// (The visitor-or-judge sign-up question, the under-construction notice and the access check were removed by
// OPEN-ACCESS, 16 Oct 2026.) Their behaviour is covered by their own WEB-LEGAL and ADR-0035 tests; this checks they
// render and are Studio.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, mount, q, qa } from "../../test-support/park/componentsHarness";
import LegalPage from "../legal/LegalPage";
import CallbackPage from "../oauth/CallbackPage";

afterEach(cleanup);

const studio = () => q<HTMLElement>(document.body, '[data-park][data-theme="studio"]');

describe("STUDIO_6 the signed-out screens render in Studio", () => {
  it.each([
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
});
