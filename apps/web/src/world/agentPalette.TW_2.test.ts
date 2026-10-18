import { describe, expect, it } from "vitest";
import {
  AGENT_COLOR_NAMES,
  AGENT_COLOR_TOKENS,
  AGENT_PALETTE,
  agentChatTint,
  agentColorByOrder,
  agentColorNameByOrder,
  agentColorTokenByOrder,
  mixColor,
} from "../design/tilo-w";

describe("TW-2 agent palette specification", () => {
  it("provides 7 distinct colors in join order", () => {
    expect(AGENT_PALETTE).toHaveLength(7);
    expect(AGENT_PALETTE[0]).toBe("#E8643F"); // Coral
    expect(AGENT_PALETTE[1]).toBe("#3F7FE0"); // Blue
    expect(AGENT_PALETTE[2]).toBe("#2BA3B8"); // Teal
    expect(AGENT_PALETTE[3]).toBe("#3E9A7C"); // Green
    expect(AGENT_PALETTE[4]).toBe("#A45DB8"); // Violet
    expect(AGENT_PALETTE[5]).toBe("#D9588C"); // Pink
    expect(AGENT_PALETTE[6]).toBe("#C9982A"); // Ochre

    // Colors must all be unique
    const unique = new Set(AGENT_PALETTE);
    expect(unique.size).toBe(7);
  });

  it("maps order index to color, name, and token", () => {
    expect(agentColorByOrder(0)).toBe("#E8643F");
    expect(agentColorNameByOrder(0)).toBe("Coral");
    expect(agentColorTokenByOrder(0)).toBe("--ag1");

    expect(agentColorByOrder(1)).toBe("#3F7FE0");
    expect(agentColorNameByOrder(1)).toBe("Blue");
    expect(agentColorTokenByOrder(1)).toBe("--ag2");

    expect(agentColorByOrder(6)).toBe("#C9982A");
    expect(agentColorNameByOrder(6)).toBe("Ochre");
    expect(agentColorTokenByOrder(6)).toBe("--ag7");

    // Cycles cleanly after 7
    expect(agentColorByOrder(7)).toBe("#E8643F");
    expect(agentColorNameByOrder(7)).toBe("Coral");
  });

  it("mixes color correctly with mixColor", () => {
    // Coral mixed with white 0.3
    const mixed = mixColor("#E8643F", [255, 255, 255], 0.3);
    expect(mixed).toMatch(/^#[0-9a-f]{6}$/i);
    expect(mixed).not.toBe("#E8643F");
  });

  it("computes chat bubble tint with agentChatTint", () => {
    const lightTint = agentChatTint(0, false);
    const darkTint = agentChatTint(0, true);
    expect(lightTint).toContain("color-mix");
    expect(darkTint).toContain("color-mix");
  });
});
