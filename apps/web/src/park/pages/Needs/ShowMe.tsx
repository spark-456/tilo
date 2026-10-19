// STUDIO-4: "Show me" on a gate in Needs you: the item the gate pins, read from the owner-only
// `GET /worlds/{id}/cards/{cid}/item` (src/api/item.ts) only when the person asks, drawn as plain text (never markup).
// A READ: it answers nothing. A refusal is a fixed sentence; the reply's own words are never shown.
import { useId, useRef, useState } from "react";
import type { ItemApi } from "../../../api/item";

type Shown =
  | { kind: "email"; subject: string; body: string }
  | { kind: "calendar_event"; title: string; when: string }
  | { kind: "file"; name: string; type: string }
  | { kind: "unreadable" };

/** Format characters (bidi overrides, zero-width) are removed so a line cannot be made to read as something else. */
const plain = (v: unknown): string | null =>
  typeof v === "string" ? v.replace(/\p{Cf}/gu, "") : null;

export function shownOf(documentText: string): Shown {
  let d: unknown;
  try {
    d = JSON.parse(documentText);
  } catch {
    return { kind: "unreadable" };
  }
  if (typeof d !== "object" || d === null || Array.isArray(d)) return { kind: "unreadable" };
  const r = d as Record<string, unknown>;
  if (r.kind === "email") {
    const subject = plain(r.subject);
    const body = plain(r.body_text);
    return subject === null || body === null
      ? { kind: "unreadable" }
      : { kind: "email", subject, body };
  }
  if (r.kind === "calendar_event") {
    const title = plain(r.title);
    const start = plain(r.start);
    const end = plain(r.end);
    return title === null || start === null || end === null
      ? { kind: "unreadable" }
      : { kind: "calendar_event", title, when: `${start} to ${end}` };
  }
  if (r.kind === "file") {
    const name = plain(r.name);
    const type = plain(r.mime_type);
    return name === null || type === null ? { kind: "unreadable" } : { kind: "file", name, type };
  }
  return { kind: "unreadable" };
}

type State =
  | { kind: "closed" }
  | { kind: "loading" }
  | { kind: "ready"; shown: Shown; to: readonly string[] }
  | { kind: "failed" };

export function ShowMe({ api, cardId }: { api: ItemApi; cardId: string }) {
  const [state, setState] = useState<State>({ kind: "closed" });
  const region = useId();
  const latest = useRef(0);
  const open = () => {
    const mine = ++latest.current;
    setState({ kind: "loading" });
    api.getCardItem(cardId).then(
      (item) =>
        latest.current === mine &&
        setState({ kind: "ready", shown: shownOf(item.document), to: item.recipients }),
      () => latest.current === mine && setState({ kind: "failed" }),
    );
  };
  const shown = state.kind === "ready" || state.kind === "loading";
  return (
    <div className="park-needs-show">
      <button
        type="button"
        className="park-needs-link"
        aria-expanded={shown}
        aria-controls={region}
        disabled={state.kind === "loading"}
        onClick={() => {
          if (state.kind === "ready") {
            latest.current += 1;
            setState({ kind: "closed" });
          } else open();
        }}
      >
        {state.kind === "ready" ? "Hide the full item" : "Show me the full item"}
      </button>
      <div id={region} aria-live="polite">
        {state.kind === "loading" ? (
          <output className="park-needs-note">Loading the item…</output>
        ) : null}
        {state.kind === "failed" ? (
          <p className="park-needs-note" role="alert">
            This item cannot be shown right now. It is not sent unless you approve it.
          </p>
        ) : null}
        {state.kind === "ready" ? <Item shown={state.shown} to={state.to} /> : null}
      </div>
    </div>
  );
}

function Item({ shown, to }: { shown: Shown; to: readonly string[] }) {
  const rows: [string, string][] =
    shown.kind === "email"
      ? [["Subject", shown.subject]]
      : shown.kind === "calendar_event"
        ? [
            ["Event", shown.title],
            ["When", shown.when],
          ]
        : shown.kind === "file"
          ? [
              ["File", shown.name],
              ["Type", shown.type],
            ]
          : [];
  return (
    <div className="park-needs-item">
      {to.length ? (
        <div className="park-needs-item__row">
          <span className="park-needs-item__k">To</span>
          <span>{to.join(", ")}</span>
        </div>
      ) : null}
      {rows.map(([k, v]) => (
        <div key={k} className="park-needs-item__row">
          <span className="park-needs-item__k">{k}</span>
          <span>{v}</span>
        </div>
      ))}
      {shown.kind === "email" ? <p className="park-needs-item__body">{shown.body}</p> : null}
      {shown.kind === "unreadable" ? (
        <p className="park-needs-note">This item is not in a form Tilo can show here.</p>
      ) : null}
    </div>
  );
}
