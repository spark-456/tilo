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

/** Reads the run's delivered output (the owner route); rejects when none can be read. */
export function readResult(api: Api, world: string): Promise<Blob> {
  const reader = readers.get(api);
  return reader ? reader(world) : Promise.reject(new Error("Result unavailable"));
}

/** Saves a result already read; the file name follows its type. */
export function saveResult(blob: Blob, world: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    const extension =
      blob.type === "application/pdf"
        ? ".pdf"
        : blob.type === "application/json"
          ? ".json"
          : blob.type === "text/markdown"
            ? ".md"
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

/** Opens a result already read in a new tab. Text opens as plain text, never as a page that could run. */
export function openResult(blob: Blob): void {
  const shown = blob.type.startsWith("text/") ? new Blob([blob], { type: "text/plain" }) : blob;
  const url = URL.createObjectURL(shown);
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  document.body.append(link);
  try {
    link.click();
  } finally {
    link.remove();
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000); // the new tab needs the address for a while
}

export async function downloadResult(api: Api, world: string): Promise<void> {
  saveResult(await readResult(api, world), world);
}
