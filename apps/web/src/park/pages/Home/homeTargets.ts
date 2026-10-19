import type { PageId, Params } from "../../app/AppCtx";

export interface HomeTargetRef {
  readonly kind: string;
  readonly id: string;
}

export interface HomeTarget {
  readonly page: PageId;
  readonly params: Params;
}

/** Routes only references whose destination exists in the Park app. */
export function homeTarget(ref: HomeTargetRef): HomeTarget | null {
  if (!ref.id.trim()) return null;
  if (ref.kind === "world") return { page: "world", params: { id: ref.id } };
  if (ref.kind === "decision" || ref.kind === "card") {
    return { page: "needs", params: { id: ref.id } };
  }
  if (
    ["calendar_event", "calendar_entry", "work_item", "pinboard_item", "pin", "meeting"].includes(
      ref.kind,
    )
  ) {
    const kind =
      ref.kind === "calendar_event"
        ? "calendar_entry"
        : ref.kind === "pin"
          ? "pinboard_item"
          : ref.kind;
    return { page: "agenda", params: { item: `${kind}:${ref.id}` } };
  }
  return null;
}
