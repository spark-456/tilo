import { API_URL, appCheckToken, authToken } from "../../api/ClientProvider";
import type { Turn } from "./useQuickChat";

export interface SavedChat {
  readonly id: string;
  readonly title: string;
  readonly updatedAt: number;
  readonly turns: readonly Turn[];
}

const key = (owner: string) => `tilo.chat.v1.${owner.toLowerCase()}`;

export function readChats(owner: string | null): SavedChat[] {
  if (!owner || typeof localStorage === "undefined") return [];
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key(owner)) ?? "[]");
    if (!Array.isArray(raw)) return [];
    const unique = new Map<string, SavedChat>();
    for (const item of raw) {
      if (
        !item ||
        typeof item.id !== "string" ||
        typeof item.title !== "string" ||
        typeof item.updatedAt !== "number" ||
        !Array.isArray(item.turns)
      )
        continue;
      const turns = item.turns.filter(
        (turn: unknown) =>
          !!turn &&
          typeof turn === "object" &&
          typeof (turn as Turn).id === "number" &&
          typeof (turn as Turn).question === "string" &&
          (turn as Turn).state !== "asking",
      );
      if (turns.length === 0) continue;
      const prior = unique.get(item.id);
      if (!prior || prior.updatedAt <= item.updatedAt)
        unique.set(item.id, { id: item.id, title: item.title, updatedAt: item.updatedAt, turns });
    }
    return [...unique.values()].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 100);
  } catch {
    return [];
  }
}

export function saveChats(owner: string | null, chats: readonly SavedChat[]): void {
  if (!owner || typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(key(owner), JSON.stringify(chats));
  } catch {
    // Storage can be disabled or full; the live conversation still works.
  }
}

async function headers(): Promise<Headers | null> {
  const token = await authToken?.();
  if (!token) return null;
  const result = new Headers({ Authorization: `Bearer ${token}` });
  const check = await appCheckToken?.();
  if (check) result.set("X-Firebase-AppCheck", check);
  return result;
}

export async function loadServerChats(): Promise<SavedChat[]> {
  if (!API_URL) return [];
  const auth = await headers();
  if (!auth) return [];
  const response = await fetch(`${API_URL.replace(/\/$/, "")}/v1/me/chats`, { headers: auth });
  if (!response.ok) throw new Error("Chat history could not be loaded");
  const data: { chats?: Array<{ id: string; title: string; updated_at: number; turns: Turn[] }> } =
    await response.json();
  return (data.chats ?? []).map((item) => ({
    id: item.id,
    title: item.title,
    updatedAt: Math.floor(item.updated_at / 1_000_000),
    turns: item.turns,
  }));
}

export async function saveServerChat(chat: SavedChat): Promise<void> {
  if (!API_URL) return;
  const auth = await headers();
  if (!auth) return;
  auth.set("Content-Type", "application/json");
  const response = await fetch(
    `${API_URL.replace(/\/$/, "")}/v1/me/chats/${encodeURIComponent(chat.id)}`,
    {
      method: "PUT",
      headers: auth,
      body: JSON.stringify({ title: chat.title, turns: chat.turns }),
    },
  );
  if (!response.ok) throw new Error("Chat history could not be saved");
}
