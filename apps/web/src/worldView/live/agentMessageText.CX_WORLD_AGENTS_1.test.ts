import { describe, expect, it } from "vitest";
import { agentMessageText } from "./agentMessageText";

describe("CX_WORLD_AGENTS_1 handoff chat copy", () => {
  it("extracts a readable sentence from recorded JSON", () => {
    expect(agentMessageText('{"summary":"The draft is ready."}')).toBe("The draft is ready.");
  });
  it("never exposes an unrecognized JSON payload", () => {
    expect(agentMessageText('{"internal_id":"run_123"}')).toBe("Shared a work update.");
  });
  it("keeps recorded plain text", () => {
    expect(agentMessageText("Please review the draft.")).toBe("Please review the draft.");
  });
});
