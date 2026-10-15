export const MAX_EVENTS = 200;

const SECRET = /(?:bearer\s+|api[_-]?key\s*[:=]\s*|password\s*[:=]\s*)\S+|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b\d{12,19}\b/gi;
const KINDS = new Set(["navigate", "click", "type", "scroll", "download", "submit"]);

export function safeText(value, limit = 200) {
  if (typeof value !== "string") return "";
  return value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(SECRET, "[masked]").trim().slice(0, limit);
}

export function safeUrl(value) {
  try {
    const url = new URL(value);
    if (!new Set(["http:", "https:"]).has(url.protocol)) return "";
    url.username = "";
    url.password = "";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return "";
  }
}

export function canonicalEvent(input, sequence) {
  if (!input || !KINDS.has(input.kind)) return null;
  const url = safeUrl(input.url);
  if (!url) return null;
  const event = {
    sequence,
    kind: input.kind,
    url,
    target: safeText(input.target),
    selector: safeText(input.selector),
    value: null,
    observation: safeText(input.observation),
    destination: safeText(input.destination, 512) || null,
  };
  if (input.kind === "type" && input.safe_text === true) event.value = safeText(input.value, 500);
  return event;
}

export function appendEvent(events, input) {
  if (events.length >= MAX_EVENTS) return events;
  const event = canonicalEvent(input, events.length + 1);
  return event ? [...events, event] : events;
}
