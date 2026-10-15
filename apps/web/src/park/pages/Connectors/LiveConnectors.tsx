import { useState } from "react";
import type { Connector } from "../../api/types";

/** UI-STUDIO-5: two letters for the app's tile, from its own name (never a brand mark). */
function monogram(name: string): string {
  const words = name.trim().split(/\s+/);
  const two =
    words.length > 1 ? `${words[0]?.[0] ?? ""}${words[1]?.[0] ?? ""}` : name.trim().slice(0, 2);
  return two.charAt(0).toUpperCase() + two.charAt(1).toLowerCase();
}
const toneOf = (c: Connector): "on" | "warn" | "off" =>
  !c.live?.stateKnown ? "off" : c.st === "attention" ? "warn" : c.st === "connected" ? "on" : "off";

/** FR-ACC-01/03/04: a read-only live list; unsupported facts and writes never use demo defaults. */
export function LiveConnectors({ connectors }: { connectors: Connector[] }) {
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
      <p className="park-connectors-note">
        Connecting and reconnecting these apps is not available here yet. What Tilo may do in each
        app is set beside this list.
      </p>
      {rows.length === 0 ? (
        <p>{connectors.length ? "No matching connectors" : "No connectors available yet"}</p>
      ) : null}
      <section className="park-connectors-section" aria-label="Tools">
        <div className="park-connectors-grid">
          {rows.map((c) => (
            <article
              className="park-connectors-tile park-connectors-live"
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
                {!c.live?.stateKnown
                  ? "Connection state not available yet"
                  : c.st === "attention"
                    ? "Needs attention"
                    : c.st === "connected"
                      ? "Connected"
                      : "Available"}
              </p>
              {!c.live?.stateKnown ? <p>Needs setup by the workspace owner</p> : null}
              <p>Access level not available yet</p>
              <p>Usage not available yet</p>
              <p>Sync history not available yet</p>
              <p>
                Granted scopes:{" "}
                {c.live?.stateKnown && c.live.scopes.length
                  ? c.live.scopes.join(", ")
                  : "Not available yet"}
              </p>
              <p>
                Grant expiry: {c.live?.stateKnown && c.expires ? c.expires : "Not available yet"}
              </p>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
