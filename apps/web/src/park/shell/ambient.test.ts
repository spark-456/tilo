// WEB-MOTION-1: the city's ambient-motion flag is on by default and any unrecognised value turns it off.
import { describe, expect, it } from "vitest";
import { ambientOn } from "./ambient";

describe("WEB-MOTION-1 ambient flag", () => {
  it("WEB-MOTION-1 unset, empty, 1, true and on (any case, padded) keep the motion on", () => {
    for (const v of [undefined, "", " ", "1", "true", "TRUE", "on", " On "]) {
      expect(ambientOn(v), String(v)).toBe(true);
    }
  });

  it("WEB-MOTION-1 0, false, off and any unrecognised value turn it off", () => {
    for (const v of ["0", "false", "off", "no", "disabled", "of", "2", "yes"]) {
      expect(ambientOn(v), v).toBe(false);
    }
  });
});
