import { describe, expect, it } from "vitest";
import { roleColor } from "../design/tilo-t/role";
import { agentRoleColor, agentRoleOf } from "./agentRole";

describe("CX_WORLD_AGENTS_1 agent colours", () => {
  it("uses the same role colour for the map and Buddy avatars", () => {
    for (const [rank, role] of [
      ["director", "director"],
      ["lead", "delivery"],
      ["specialist", "research"],
      ["writer", "designer"],
      ["verifier", "tester"],
      ["narrator", "finance"],
    ] as const) {
      expect(agentRoleOf(rank)).toBe(role);
      expect(agentRoleColor(rank)).toBe(roleColor(role));
    }
  });
});
