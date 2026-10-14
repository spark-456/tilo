import type { Event, Layout } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { levelOf } from "./LevelChip";

const layout = LAYOUT_VILLAGE_BASIC as unknown as Layout;
const first = layout.semantic.levels[0];
const event = (level: string | null) => ({ level }) as unknown as Event;

describe("UX-1 #227 E1: the level chip comes from the event's own level field (HR-1)", () => {
  it("numbers a level by its place in the layout, with its name and a tint", () => {
    const lv = levelOf(layout, event(first?.id ?? ""));
    expect(lv).toMatchObject({ n: 1, name: first?.name });
    expect(lv?.tint).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });

  it("shows no chip for an event with no level, an unknown level, or no layout yet", () => {
    expect(levelOf(layout, event(null))).toBeNull();
    expect(levelOf(layout, event("L_not_in_this_world"))).toBeNull();
    expect(levelOf(null, event(first?.id ?? ""))).toBeNull();
  });
});
