// The level an event was recorded in, as a chip: "L1", "L2" ... in the colour of its level, with the
// level's name for a screen reader (PRD 18.3 Story lens; colour never carries it alone). The level
// is the event's own `level` field matched to the layout's levels, in the layout's order: an event
// without one, or one the layout does not know, shows no chip rather than a guess (HR-1).
import type { Event, Layout } from "@tilo/contracts";
import tokens from "../design/tokens";

// The same six-tint pool the world draws its districts with (world/frame.ts).
const TINTS = Object.values(tokens.color.district).slice(0, 6);

export interface LevelRef {
  readonly n: number;
  readonly name: string;
  readonly tint: string;
}

export function levelOf(layout: Layout | null, e: Event): LevelRef | null {
  if (!layout || !e.level) return null;
  const i = layout.semantic.levels.findIndex((l) => l.id === e.level);
  const level = layout.semantic.levels[i];
  return level ? { n: i + 1, name: level.name, tint: TINTS[i % TINTS.length] as string } : null;
}

export function LevelChip({ level }: { level: LevelRef }) {
  return (
    <span
      className="level-chip"
      role="img"
      aria-label={`Level ${level.name}`}
      style={{ "--level-tint": level.tint } as React.CSSProperties}
    >
      L{level.n}
    </span>
  );
}
