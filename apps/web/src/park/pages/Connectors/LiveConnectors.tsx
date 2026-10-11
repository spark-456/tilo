import { useState } from "react";
import type { Connector } from "../../api/types";

/** FR-ACC-01/03/04: a read-only live list; unsupported facts and writes never use demo defaults. */
export function LiveConnectors({ connectors }: { connectors: Connector[] }) {
  const [query, setQuery] = useState("");
  const rows = connectors.filter((c) => c.name.toLowerCase().includes(query.toLowerCase()));
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
        Connecting, reconnecting and changing access are not available here yet.
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
              <h2 className="park-connectors-tile-name">{c.name}</h2>
              <p>
                {!c.live?.stateKnown
                  ? "Connection state not available yet"
                  : c.st === "attention"
                    ? "Needs attention"
                    : c.st === "connected"
                      ? "Connected"
                      : "Available"}
              </p>
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
