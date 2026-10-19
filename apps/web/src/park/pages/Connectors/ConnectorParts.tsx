// Connectors page-local parts (plan section 4 "ConnectorTile"): the attention banner, a Connected tile and an
// Add-a-tool row. Local stand-ins with no call behind them show the saved still Tilo frame (HR-1).
import type { Connector } from "../../api/types";
import { ThinkingTilo } from "../../shared/ThinkingTilo";
import { BrandIcon } from "./BrandIcon";
import { icon } from "./icons";
import { LEVEL_LABEL, type Merged, bannerText, syncLine, usedLine } from "./view";

export function monoColor(col: string | undefined): string {
  if (!col || col.toLowerCase() === "#2b2a33" || col.toLowerCase() === "#1f1d2b") {
    return "var(--ink)";
  }
  return col;
}

export function Spin({ still = false }: { still?: boolean }) {
  return <ThinkingTilo label="Working on connector" size={20} still={still} />;
}

export function AttentionBanner({
  c,
  waiting,
  onReconnect,
}: { c: Merged; waiting: boolean; onReconnect: () => void }) {
  const { title, sub } = bannerText(c);
  const expired = c.exp === "expired";
  return (
    <div
      className={
        expired
          ? "park-connectors-banner park-connectors-banner--expired"
          : "park-connectors-banner"
      }
      role={expired ? "alert" : "status"}
    >
      <span className="park-connectors-banner-icon">{icon("plug", 18)}</span>
      <div className="park-connectors-banner-text">
        <div className="park-connectors-banner-title">{title}</div>
        <div className="park-connectors-banner-sub">{sub}</div>
      </div>
      <button type="button" className="park-connectors-reconnect" onClick={onReconnect}>
        {waiting ? <Spin still /> : null}
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
        <span className="park-connectors-mono" style={{ color: monoColor(c.col) }}>
          <BrandIcon id={c.id} mono={c.mono} />
        </span>
        <span className="park-connectors-tile-names">
          <span className="park-connectors-tile-name">{c.name}</span>
          <span className="park-connectors-tile-acct">{c.acct || "Account not available"}</span>
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
        <span className="park-connectors-manage">Manage</span>
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
      <span className="park-connectors-avail-mono" style={{ color: monoColor(c.col) }}>
        <BrandIcon id={c.id} mono={c.mono} />
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

export function RealConnectedCard({
  c,
  onOpen,
  onConnect,
  onReconnect,
}: {
  c: Merged;
  onOpen: () => void;
  onConnect: () => void;
  onReconnect: () => void;
}) {
  const attn = c.st === "attention";
  const on = c.st === "connected";
  const avail = c.st === "available";

  return (
    <article
      className={
        attn
          ? "park-connectors-tile park-connectors-card park-connectors-tile--attn"
          : "park-connectors-tile park-connectors-card"
      }
      data-connector-card={c.id}
    >
      <button type="button" className="park-connectors-card-main" onClick={onOpen}>
        <div className="park-connectors-tile-head">
          <span className="park-connectors-mono">
            <BrandIcon id={c.id} mono={c.mono} />
          </span>
          <div className="park-connectors-tile-names">
            <span className="park-connectors-tile-name">{c.name}</span>
            <span className="park-connectors-tile-acct">
              {c.acct || (avail ? "Not connected yet" : "Account not available")}
            </span>
          </div>
          <span className={`park-connectors-level park-connectors-level--${c.level}`}>
            {LEVEL_LABEL[c.level] || (avail ? "Available" : "Connected")}
          </span>
        </div>
        <div className="park-connectors-tile-foot">
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
            {avail ? "Not connected" : syncLine(c)}
          </span>
          <span className="park-connectors-used">{avail ? "No active worlds" : usedLine(c)}</span>
          <span className="park-connectors-manage">Manage</span>
        </div>
      </button>
      <div className="park-connectors-card-actions">
        {attn ? (
          <button
            type="button"
            className="park-connectors-action-btn park-connectors-action-btn--reconnect"
            onClick={(e) => {
              e.stopPropagation();
              onReconnect();
            }}
          >
            Reconnect
          </button>
        ) : on ? (
          <button
            type="button"
            className="park-connectors-action-btn park-connectors-action-btn--reconnect"
            onClick={(e) => {
              e.stopPropagation();
              onReconnect();
            }}
          >
            Reconnect
          </button>
        ) : (
          <button
            type="button"
            className="park-connectors-action-btn park-connectors-action-btn--connect"
            onClick={(e) => {
              e.stopPropagation();
              onConnect();
            }}
          >
            Connect
          </button>
        )}
      </div>
    </article>
  );
}
