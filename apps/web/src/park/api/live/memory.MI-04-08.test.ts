import { describe, expect, it, vi } from "vitest";
import { memoryApi } from "./memory";

const item = {
  id: "mem_1",
  org_id: "org_1",
  owner: "user_1",
  text: "I prefer mornings",
  kind: "preference",
  source: "user",
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
};

describe("MI-04 MI-08 memory client", () => {
  it("MI-08 reads, creates, edits and deletes only through the memory routes", async () => {
    const http = {
      getJson: vi.fn(async () => ({ items: [item] })),
      postJson: vi.fn(async () => item),
      sendJson: vi.fn(async (method: string) =>
        method === "PATCH" ? { ...item, text: "New" } : undefined,
      ),
    };
    const api = memoryApi(http);
    expect(await api.list()).toEqual([item]);
    expect(await api.create({ text: item.text, kind: "preference", source: "user" })).toEqual(item);
    expect(await api.update(item.id, { text: "New" })).toMatchObject({ text: "New" });
    await api.remove(item.id);
    expect(http.getJson).toHaveBeenCalledWith("/v1/memory");
    expect(http.postJson).toHaveBeenCalledWith("/v1/memory", {
      text: item.text,
      kind: "preference",
      source: "user",
    });
    expect(http.sendJson).toHaveBeenCalledWith("PATCH", "/v1/memory/mem_1", { text: "New" });
    expect(http.sendJson).toHaveBeenCalledWith("DELETE", "/v1/memory/mem_1");
  });
  it("MI-08 rejects an unreadable reply instead of reporting a saved note", async () => {
    const api = memoryApi({
      getJson: async () => ({}),
      postJson: async () => ({}),
      sendJson: async () => ({}),
    });
    await expect(api.list()).rejects.toThrow();
    await expect(api.create({ text: "A", kind: "fact", source: "user" })).rejects.toThrow();
  });
});
