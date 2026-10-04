import { describe, expect, it } from "vitest";
import { TiloApiError } from "../api/http";
import { describeError } from "./remote";

describe("CL-INT-3 PRD 18.4: an error says only what is known", () => {
  it("a retryable failure on a write says it could not be confirmed, never 'Nothing was changed'", () => {
    for (const status of [null, 503]) {
      const text = describeError("approve the budget", new TiloApiError("x", status, true, true));
      expect(text).toContain("We could not confirm it. Check before trying again.");
      expect(text).not.toContain("Nothing was changed");
    }
  });

  it("a 4xx on a write keeps 'Nothing was changed' and the reason", () => {
    const text = describeError(
      "approve the budget",
      new TiloApiError("That cannot be done right now.", 409, false, true),
    );
    expect(text).toBe(
      "Could not approve the budget: That cannot be done right now. Nothing was changed. You can try again.",
    );
  });

  it("a retryable failure on a read still says nothing was changed", () => {
    const text = describeError("load the cards", new TiloApiError("x", 503, true, false));
    expect(text).toContain("Nothing was changed.");
  });

  it("any other error keeps the existing wording", () => {
    expect(describeError("load the world", new Error("the network is down"))).toBe(
      "Could not load the world: the network is down. Nothing was changed. You can try again.",
    );
  });
});
