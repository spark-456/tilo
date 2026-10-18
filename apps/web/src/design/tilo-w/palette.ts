// Tilo W agent palette: 7 distinct colours in join order (PROMPT.md, TW-2).
// Same colour on sprite, avatar, chat tint, file dot and card swatch.
// One colour per agent, never reused within a run.

export const AGENT_PALETTE = [
  "#E8643F", // --ag1 Coral
  "#3F7FE0", // --ag2 Blue
  "#2BA3B8", // --ag3 Teal
  "#3E9A7C", // --ag4 Green
  "#A45DB8", // --ag5 Violet
  "#D9588C", // --ag6 Pink
  "#C9982A", // --ag7 Ochre
] as const;

export const AGENT_COLOR_NAMES = [
  "Coral",
  "Blue",
  "Teal",
  "Green",
  "Violet",
  "Pink",
  "Ochre",
] as const;

export const AGENT_COLOR_TOKENS = [
  "--ag1",
  "--ag2",
  "--ag3",
  "--ag4",
  "--ag5",
  "--ag6",
  "--ag7",
] as const;

export type AgentColor = (typeof AGENT_PALETTE)[number];
export type AgentColorName = (typeof AGENT_COLOR_NAMES)[number];
export type AgentColorToken = (typeof AGENT_COLOR_TOKENS)[number];

const hx = (c: string): number[] => [1, 3, 5].map((i) => Number.parseInt(c.slice(i, i + 2), 16));

/** Mixes a hex colour with a target RGB tuple by factor f (0..1). */
export const mixColor = (col: string, t: readonly number[], f: number): string =>
  `#${hx(col)
    .map((v, i) =>
      Math.round(v + ((t[i] ?? 0) - v) * f)
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;

/**
 * Returns the agent color for an agent by its join index (0-indexed).
 * Cycles through the 7 palette colours if more than 7 agents exist.
 */
export function agentColorByOrder(orderIndex: number): AgentColor {
  const idx = Math.max(0, orderIndex) % AGENT_PALETTE.length;
  return AGENT_PALETTE[idx] ?? AGENT_PALETTE[0];
}

/** Returns the agent color name by its join index (0-indexed). */
export function agentColorNameByOrder(orderIndex: number): AgentColorName {
  const idx = Math.max(0, orderIndex) % AGENT_COLOR_NAMES.length;
  return AGENT_COLOR_NAMES[idx] ?? AGENT_COLOR_NAMES[0];
}

/** Returns the CSS variable token name (--ag1..--ag7). */
export function agentColorTokenByOrder(orderIndex: number): AgentColorToken {
  const idx = Math.max(0, orderIndex) % AGENT_COLOR_TOKENS.length;
  return AGENT_COLOR_TOKENS[idx] ?? AGENT_COLOR_TOKENS[0];
}

/**
 * Chat bubble tint: color-mix(in srgb, agent 13%, var(--card)).
 * When CSS color-mix is supported or hex approximation is needed.
 */
export function agentChatTint(col: string): string {
  return `color-mix(in srgb, ${col} 13%, var(--card, #ffffff))`;
}
