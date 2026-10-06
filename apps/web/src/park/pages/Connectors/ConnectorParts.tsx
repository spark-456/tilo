// Connectors page-local parts (plan section 4 "ConnectorTile"): the attention banner, a Connected tile and an
// Add-a-tool row. Built from the design's markup (Tilo App Connectors.dc.html). The design's spinner turns;
// here it is a still ring (motion arrives with WEB-3b, BQ-WEB-3) and the label says the state.
import type { Connector } from "../../api/types";
import { icon } from "./icons";
import { LEVEL_LABEL, type Merged, bannerText, syncLine, usedLine } from "./view";

export function Spin({ onRed }: { onRed?: boolean }) {
  return (
    <span
      className={onRed ? "park-connectors-spin park-connectors-spin--red" : "park-connectors-spin"}
      aria-hidden="true"
    />
  );
}

export function AttentionBanner({
  c,
  waiting,
  onReconnect,
}: { c: Connector; waiting: boolean; onReconnect: () => void }) {
  const { title, sub } = bannerText(c);
  return (
    <div className="park-connectors-banner">
      <span className="park-connectors-banner-icon">{icon("plug", 18)}</span>
      <div className="park-connectors-banner-text">
        <div className="park-connectors-banner-title">{title}</div>
        <div className="park-connectors-banner-sub">{sub}</div>
      </div>
      <button type="button" className="park-connectors-reconnect" onClick={onReconnect}>
        {waiting ? <Spin onRed /> : null}
        {waiting ? `Waiting for ${c.name}` : "Reconnect"}
      </button>
    </div>
  );
}

export function ConnectedTile({ c, onOpen }: { c: Merged; onOpen: () => void }) {
  const attn = c.st === "attention";
  return (
    <button
      type="button"
      className={attn ? "park-connectors-tile park-connectors-tile--attn" : "park-connectors-tile"}
      onClick={onOpen}
    >
      <span className="park-connectors-tile-head">
        <span className="park-connectors-mono" style={{ color: c.col }}>
          {c.mono}
        </span>
        <span className="park-connectors-tile-names">
          <span className="park-connectors-tile-name">{c.name}</span>
          <span className="park-connectors-tile-acct">{c.acct || "Connected just now"}</span>
        </span>
        <span className={`park-connectors-level park-connectors-level--${c.level}`}>
          {LEVEL_LABEL[c.level]}
        </span>
      </span>
      <span className="park-connectors-tile-foot">
        <span
          className={
            attn ? "park-connectors-sync park-connectors-sync--attn" : "park-connectors-sync"
          }
        >
          <span
            className={
              attn ? "park-connectors-dot park-connectors-dot--attn" : "park-connectors-dot"
            }
          />
          {syncLine(c)}
        </span>
        <span className="park-connectors-used">{usedLine(c)}</span>
      </span>
    </button>
  );
}

export function AvailableRow({
  c,
  busy,
  onConnect,
}: { c: Connector; busy: boolean; onConnect: () => void }) {
  return (
    <div className="park-connectors-avail">
      <span className="park-connectors-avail-mono" style={{ color: c.col }}>
        {c.mono}
      </span>
      <span className="park-connectors-avail-names">
        <span className="park-connectors-avail-name">{c.name}</span>
        <span className="park-connectors-avail-blurb">{c.blurb}</span>
      </span>
      <button type="button" className="park-connectors-connect" disabled={busy} onClick={onConnect}>
        {busy ? <Spin /> : null}
        {busy ? "Signing in" : "Connect"}
      </button>
    </div>
  );
}
