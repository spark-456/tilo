// UI-STUDIO-2: display state the person chooses (the Chat scene, the bubble's place). Browser storage only, every
// read and write in try/catch: a private window or blocked storage falls back to the default, never an error.
export const SCENES = ["office", "balcony", "beach", "room"] as const;
export type SceneId = (typeof SCENES)[number];
export const SCENE_LABEL: Readonly<Record<SceneId, string>> = {
  office: "Office",
  balcony: "Balcony",
  beach: "Beach",
  room: "Cosy room",
};

const SCENE_KEY = "tilo.chat.scene";
const BUBBLE_KEY = "tilo.bubble.pos";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // storage blocked: the choice lasts this visit only
  }
}

export function readScene(): SceneId {
  const v = read(SCENE_KEY);
  return SCENES.find((s) => s === v) ?? "office";
}
export const writeScene = (scene: SceneId): void => write(SCENE_KEY, scene);

/** The bubble's offset from the bottom-right corner, in px (0, 0 = the default place). */
export interface BubblePos {
  readonly right: number;
  readonly bottom: number;
}

export function readBubblePos(): BubblePos | null {
  const raw = read(BUBBLE_KEY);
  if (raw === null) return null;
  try {
    const v = JSON.parse(raw) as { right?: unknown; bottom?: unknown };
    const ok = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n >= 0;
    return ok(v.right) && ok(v.bottom) ? { right: v.right, bottom: v.bottom } : null;
  } catch {
    return null;
  }
}
export const writeBubblePos = (pos: BubblePos | null): void =>
  write(BUBBLE_KEY, pos === null ? null : JSON.stringify(pos));
