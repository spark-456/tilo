// @vitest-environment happy-dom
// NFR-01 (PRD 17.1), ticket NFR-01-LANDING: while an app chunk is still arriving, Root shows a neutral shell
// frame, not an empty page (the Suspense fallback was null for both apps, so a cold chunk left the page blank
// for about half a second). The frame is a plain element: no text, no animation, no control, painted in the
// colour the page that follows starts with (the Park boot splash's paper, the old app's surface), and fixed
// to the viewport so the real page arriving moves nothing (CLS 0).
// Pinned surface: `[data-testid="root-frame"]` with `data-app="park"` or `data-app="kept"`.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, qa } from "../test-support/park/componentsHarness";

// Both chunks stay pending for as long as the test runs: the import never settles.
vi.mock("./App", () => new Promise(() => undefined));
vi.mock("./park/app/ParkApp", () => new Promise(() => undefined));

import { Root } from "./Root";

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const visit = (path: string) => {
  window.history.pushState({}, "", path);
  return mount(<Root />);
};

describe("NFR_01_LANDING_root: a neutral frame while a chunk arrives", () => {
  it("NFR_01_LANDING_root_the_landing_shows_the_park_frame_not_a_blank_page", () => {
    const m = visit("/");
    const frames = qa(m.container, '[data-testid="root-frame"]');
    expect(frames).toHaveLength(1);
    expect(frames[0]?.getAttribute("data-app")).toBe("park");
    expect(m.container.innerHTML).not.toBe("");
  });

  it("NFR_01_LANDING_root_a_kept_screen_shows_the_kept_frame", () => {
    const m = visit("/more");
    const frames = qa(m.container, '[data-testid="root-frame"]');
    expect(frames).toHaveLength(1);
    expect(frames[0]?.getAttribute("data-app")).toBe("kept");
  });

  it("NFR_01_LANDING_root_the_frame_has_no_text_no_control_and_is_hidden_from_assistive_technology", () => {
    for (const path of ["/", "/more"]) {
      const m = visit(path);
      const frame = qa(m.container, '[data-testid="root-frame"]')[0] as HTMLElement;
      expect(frame.textContent, path).toBe("");
      expect(frame.querySelector("*"), path).toBeNull();
      expect(frame.getAttribute("aria-hidden"), path).toBe("true");
      expect(frame.style.animation, path).toBe("");
      m.unmount();
    }
  });
});
