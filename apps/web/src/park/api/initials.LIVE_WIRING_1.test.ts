import { describe, expect, it } from "vitest";
import { userOf } from "./liveApi";

describe("FR_UX_10 LIVE_WIRING_1 account initials", () => {
  it.each([
    ["🦊 Ana ✨ Silva", "AS"],
    ["123 Zoë 456 García", "ZG"],
    ["🌟 李 明", "李明"],
    ["-- Élodie --", "ÉL"],
    ["🦊 123 !!!", "?"],
  ])("FR_UX_10 LIVE_WIRING_1 %s uses letter initials %s", (name, initials) => {
    expect(userOf({ name, email: "person@example.test" })?.initials).toBe(initials);
  });
});
