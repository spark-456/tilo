// UI-STUDIO-5: "Your Tilo hangs out in" (design/studio-v2 "Tilo S Settings"), the scene behind the helper in Chat.
// Display state only, never an event: browser storage, every read and write in try/catch, so a private window or
// blocked storage falls back to the office and never throws. The key and the stored words are the ones the Chat
// scene (UI-STUDIO-2) reads, so a choice made in Settings shows in Chat and back: "cosy" is stored as "room".
export const SCENE_IDS = ["office", "balcony", "beach", "cosy"] as const;
export type SceneId = (typeof SCENE_IDS)[number];

export const SCENE_NAMES: Readonly<Record<SceneId, string>> = {
  office: "Office",
  balcony: "Balcony",
  beach: "Beach",
  cosy: "Cosy room",
};

export const SCENE_KEY = "tilo.chat.scene";
const STORED: Readonly<Record<SceneId, string>> = {
  office: "office",
  balcony: "balcony",
  beach: "beach",
  cosy: "room",
};

/** The chosen scene; the office when nothing (or nothing readable) is stored. */
export function getScene(): SceneId {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(SCENE_KEY);
  } catch {
    raw = null;
  }
  return SCENE_IDS.find((id) => STORED[id] === raw || id === raw) ?? "office";
}

/** Remembers the scene; with storage blocked the choice lasts only while the page is open. */
export function setScene(scene: SceneId): void {
  try {
    window.localStorage.setItem(SCENE_KEY, STORED[scene]);
  } catch {
    // storage blocked: nothing to do
  }
}
