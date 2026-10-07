// @vitest-environment happy-dom
// WEB-MOTION-2: a heavy page draws itself in parts so no commit holds the main thread (4x CPU, no long task while
// pages change). Where the browser runs CSS animations the first part is drawn at once and each next part one
// scheduler task later, top to bottom; in the DOM stand-in every part is drawn at the first render.
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, qa } from "../../../test-support/park/componentsHarness";
import { mountShell } from "../../../test-support/park/shellHarness";
import { useStaged } from "./useStaged";

const g = globalThis as unknown as { CSSAnimation?: unknown };
const had = "CSSAnimation" in g;
afterEach(() => {
  if (!had) Reflect.deleteProperty(g, "CSSAnimation");
  cleanup();
});

function Page({ parts }: { parts: number }) {
  const part = useStaged(parts);
  return (
    <>
      {Array.from({ length: parts }, (_, i) => i + 1).map((n) =>
        part(n) ? <p key={n} data-part={n} /> : null,
      )}
    </>
  );
}
const drawn = () => qa(document.body, "[data-part]").map((e) => e.getAttribute("data-part"));

describe("WEB-MOTION-2 staged: a heavy page draws in parts, top to bottom, one task each", () => {
  it("WEB-MOTION-2 staged: in a browser with CSS animations part 1 is drawn at once and each timer adds the next part", () => {
    g.CSSAnimation = class {};
    const { sch } = mountShell(<Page parts={4} />);
    expect(drawn()).toEqual(["1"]);
    for (let n = 2; n <= 4; n++) {
      act(() => sch.fire(sch.live()[0]));
      expect(drawn()).toEqual(Array.from({ length: n }, (_, i) => String(i + 1)));
    }
    expect(sch.live()).toHaveLength(0);
  });

  it("WEB-MOTION-2 staged: without CSS animations (the DOM stand-in) every part is drawn at the first render and no timer is armed", () => {
    const { sch } = mountShell(<Page parts={4} />);
    expect(drawn()).toEqual(["1", "2", "3", "4"]);
    expect(sch.live()).toHaveLength(0);
  });
});
