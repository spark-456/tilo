// WEB-MOTION-1: the sprite cap (park.shell.css, `.park-shell__scene > div > div:nth-of-type(even)`) hides every
// second DIV child of the scene's root div. That is only right while the root's div children are the movers and
// nothing else (the buildings and roads are <img>). This pins that structure.
import { describe, expect, it } from "vitest";
import {
  type Engine,
  type Json,
  type TestH,
  call,
  canon,
  fakeEnv,
  serialiseH,
} from "../../../test-support/park/engineProto";
import { createPark } from "./park";
import { createWorld } from "./world";

type Node = { tag: string; props: Record<string, Json> | null; children: Json[] };
type MakePark = (h: TestH, makeWorld: typeof createWorld, env?: unknown) => Engine;

describe("WEB-MOTION-1 sprite cap structure", () => {
  it("WEB-MOTION-1 every div child of the scene root is a mover layer, and there are several", () => {
    const engine = (createPark as unknown as MakePark)(serialiseH, createWorld, fakeEnv);
    const el = (call(engine, "scene", { w: 1000, h: 700, still: false }) as { el: unknown }).el;
    const root = canon(el) as unknown as Node;
    expect(root.tag).toBe("div");
    const divs = root.children.filter(
      (c): c is Json & Node => !!c && typeof c === "object" && (c as Node).tag === "div",
    );
    expect(divs.length).toBeGreaterThan(3);
    for (const d of divs) {
      const style = (d.props?.style ?? {}) as Record<string, Json>;
      expect(style.willChange, "a non-mover div under the scene root breaks the cap").toBe(
        "transform",
      );
    }
  });
});
