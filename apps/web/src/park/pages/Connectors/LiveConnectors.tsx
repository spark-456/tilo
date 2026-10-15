import { useState } from "react";
import type { Connector } from "../../api/types";
import { levelLabel } from "./ToolAccess";

/** UI-STUDIO-5: two letters for the app's tile, from its own name (never a brand mark). */
export function monogram(name: string): string {
  const words = name.trim().split(/\s+/);
  const two =
    words.length > 1 ? `${words[0]?.[0] ?? ""}${words[1]?.[0] ?? ""}` : name.trim().slice(0, 2);
  return two.charAt(0).toUpperCase() + two.charAt(1).toLowerCase();
}
export const toneOf = (c: Connector): "on" | "warn" | "off" =>
  !c.live?.stateKnown ? "off" : c.st === "attention" ? "warn" : c.st === "connected" ? "on" : "off";
export const stateText = (c: Connector): string =>
  !c.live?.stateKnown
    ? "Connection state not available yet"
    : c.st === "attention"
      ? "Needs attention"
      : c.st === "connected"
        ? "Connected"
        : "Available";
/** The grant facts the list serves, said the same way on the card and in the manage panel. */
export const scopesText = (c: Connector): string =>
  !c.live?.stateKnown
    ? "Not available yet"
    : c.live.scopes.length
      ? c.live.scopes.join(", ")
      : "None recorded";
export const expiryText = (c: Connector): string =>
  !c.live?.stateKnown ? "Not available yet" : (c.expires ?? "No expiry recorded");

/** Each app's access level (GET /v1/team tools[].level, the Owner's route): loading, known, or why it is not shown. */
export type ToolLevels =
  | { kind: "loading" }
  | { kind: "known"; byId: Record<string, string> }
  | { kind: "not_owner" }
  | { kind: "unknown" };

export function accessLine(levels: ToolLevels, id: string): string {
  if (levels.kind === "loading") return "Access level: Loading…";
  if (levels.kind === "not_owner") return "Access level: Set by the workspace owner";
  const level = levels.kind === "known" ? levels.byId[id] : undefined;
  return level === undefined
    ? "Access level not available yet"
    : `Access level: ${levelLabel(level)}`;
}

/** FR-ACC-01/03/04: a live list; unsupported facts and writes never use demo defaults. Manage opens the panel. */
export function LiveConnectors({
  connectors,
  levels = { kind: "unknown" },
  selected = null,
  onManage,
}: {
  connectors: Connector[];
  levels?: ToolLevels;
  selected?: string | null;
  onManage?: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const rows = connectors.filter(
    (c) =>
      !(c.id === "meeting_host" && c.live?.notConfigured) &&
      c.name.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <>
      <div className="park-connectors-search">
        <input
          className="park-connectors-search-input"
          aria-label="Search connectors"
          placeholder="Search tools"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <p className="park-connectors-note">What Tilo may do in each app is set beside this list.</p>
      {rows.length === 0 ? (
        <p>{connectors.length ? "No matching connectors" : "No connectors available yet"}</p>
      ) : null}
      <section className="park-connectors-section" aria-label="Tools">
        <div className="park-connectors-grid">
          {rows.map((c) => (
            <article
              className={
                selected === c.id
                  ? "park-connectors-tile park-connectors-live park-connectors-live--sel"
                  : "park-connectors-tile park-connectors-live"
              }
              key={c.id}
              aria-label={c.name}
            >
              <div className="park-connectors-livehead">
                <span className="park-connectors-avail-mono" aria-hidden="true">
                  {monogram(c.name)}
                </span>
                <h2 className="park-connectors-tile-name">{c.name}</h2>
              </div>
              <p className={`park-connectors-livestate park-connectors-livestate--${toneOf(c)}`}>
                {stateText(c)}
              </p>
              {!c.live?.stateKnown ? <p>Needs setup by the workspace owner</p> : null}
              <p>{accessLine(levels, c.id)}</p>
              <p>Granted scopes: {scopesText(c)}</p>
              <p>Grant expiry: {expiryText(c)}</p>
              {onManage ? (
                <button
                  type="button"
                  id={`manage-${c.id}`}
                  className="park-connectors-manage-btn"
                  aria-label={`Manage ${c.name}`}
                  aria-pressed={selected === c.id}
                  onClick={() => onManage(c.id)}
                >
                  Manage
                </button>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
