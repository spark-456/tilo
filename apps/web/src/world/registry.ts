// HR-5: "Unknown event types appear in the Trace only." KNOWN_EVENT_TYPES is generated at build
// time from contracts/events/registry.yaml (apps/web/scripts/generate-registry.mjs); never
// hand-copy the list here.
import { KNOWN_EVENT_TYPES } from "./registry.generated";

const KNOWN = new Set(KNOWN_EVENT_TYPES);

export function isKnownType(type: string): boolean {
  return KNOWN.has(type);
}
