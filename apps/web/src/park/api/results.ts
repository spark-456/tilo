import type { Api } from "./index";

type ResultReader = (world: string) => Promise<Blob>;
const readers = new WeakMap<Api, ResultReader>();
export function installResultReader(api: Api, reader: ResultReader): void {
  readers.set(api, reader);
}
export function hasResultReader(api: Api): boolean {
  return readers.has(api);
}
export function carryResultReader(from: Api, to: Api, enabled: () => boolean = () => true): Api {
  const reader = readers.get(from);
  if (reader)
    installResultReader(to, (world) => {
      if (!enabled()) return Promise.reject(new Error("Result unavailable"));
      return reader(world);
    });
  return to;
}
export async function downloadResult(api: Api, world: string): Promise<void> {
  const reader = readers.get(api);
  if (!reader) throw new Error("Result unavailable");
  const blob = await reader(world);
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    const extension =
      blob.type === "application/pdf"
        ? ".pdf"
        : blob.type === "application/json"
          ? ".json"
          : blob.type.startsWith("text/")
            ? ".txt"
            : "";
    link.download = `tilo-result-${world}${extension}`;
    document.body.append(link);
    try {
      link.click();
    } finally {
      link.remove();
    }
  } finally {
    URL.revokeObjectURL(url);
  }
}
