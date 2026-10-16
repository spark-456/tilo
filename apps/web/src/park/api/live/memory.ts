import type { MemoryItem, MemoryItemCreate, MemoryItemUpdate } from "@tilo/contracts";
import type { HttpClient } from "../../../api/http";

const object = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const kinds = ["preference", "fact", "person"];
const sources = ["user", "tilo_suggested"];
const itemOf = (v: unknown): v is MemoryItem =>
  object(v) &&
  /^mem_[0-9A-Za-z_]{1,48}$/.test(String(v.id)) &&
  typeof v.org_id === "string" &&
  typeof v.owner === "string" &&
  typeof v.text === "string" &&
  v.text.length > 0 &&
  v.text.length <= 280 &&
  kinds.includes(String(v.kind)) &&
  sources.includes(String(v.source)) &&
  typeof v.created_at === "string" &&
  typeof v.updated_at === "string";
const unreadable = () => new Error("Tilo sent a memory reply this page could not read.");
const checked = (v: unknown): MemoryItem => {
  if (!itemOf(v)) throw unreadable();
  return v;
};

/** Signed-in HTTP client supplied by ParkProvider; the server scopes every route to the caller. */
export function memoryApi(http: Pick<HttpClient, "getJson" | "postJson" | "sendJson">) {
  return {
    async list(): Promise<MemoryItem[]> {
      const body = await http.getJson("/v1/memory");
      if (
        !object(body) ||
        !Array.isArray(body.items) ||
        body.items.length > 100 ||
        !body.items.every(itemOf)
      )
        throw unreadable();
      return body.items;
    },
    create(body: MemoryItemCreate): Promise<MemoryItem> {
      return http.postJson("/v1/memory", body).then(checked);
    },
    update(id: string, body: MemoryItemUpdate): Promise<MemoryItem> {
      return http.sendJson("PATCH", `/v1/memory/${encodeURIComponent(id)}`, body).then(checked);
    },
    async remove(id: string): Promise<void> {
      await http.sendJson("DELETE", `/v1/memory/${encodeURIComponent(id)}`);
    },
  };
}
export type MemoryApi = ReturnType<typeof memoryApi>;
