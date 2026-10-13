// The connector detail panel (design: a right-hand drawer, role="dialog" named by the tool). The scrim and
// Escape close it; focus goes to Close on open and back to the opener on close.
import { useEffect, useRef } from "react";
import { Spin, monoColor } from "./ConnectorParts";
import { icon } from "./icons";
import {
  DEFAULT_SCOPES,
  LEVEL_LABEL,
  type Merged,
  type UsedRow,
  ceilingOf,
  drawerSync,
} from "./view";

export interface DrawerProps {
  c: Merged;
  /** The skills and worlds that touch the tool (FR-ACC-03), from `usedBy`. */
  used: readonly UsedRow[];
  /** A sync of this tool is in flight: the only time the spinner shows. */
  syncing: boolean;
  /** A reconnect of this tool is in flight. */
  reconnecting: boolean;
  onClose: () => void;
  onLevel: (level: number, sub: string) => void;
  onUsed: (row: UsedRow) => void;
  onReconnect: () => void;
  onDisconnect: () => void;
  onSync: () => void;
}

const USED_ICON = { skill: "bolt", world: "globe", other: "calendar" } as const;
const USED_TITLE = {
  skill: "Opens the skill",
  world: "Opens the world",
  other: "Opens the agenda",
} as const;

export function Drawer({
  c,
  used,
  syncing,
  reconnecting,
  onClose,
  onLevel,
  onUsed,
  onReconnect,
  onDisconnect,
  onSync,
}: DrawerProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });
  useEffect(() => {
    const opener = document.activeElement;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);
  const attn = c.st === "attention";
  return (
    <>
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: a click-away layer; the keyboard way out is Escape and Close */}
      <div className="park-connectors-scrim" onClick={onClose} />
      {/* biome-ignore lint/a11y/useSemanticElements: the design's side panel is an aside with role="dialog" */}
      <aside className="park-connectors-drawer" role="dialog" aria-label={c.name}>
        <div className="park-connectors-drawer-head">
          <span className="park-connectors-drawer-mono" style={{ color: monoColor(c.col) }}>
            {c.mono}
          </span>
          <div className="park-connectors-drawer-title">
            <div className="park-connectors-drawer-name">{c.name}</div>
            <div className="park-connectors-drawer-meta">
              {c.cat} · {c.acct || "Connected just now"}
            </div>
          </div>
          <button
            type="button"
            ref={closeRef}
            className="park-connectors-close"
            aria-label="Close"
            onClick={onClose}
          >
            {icon("x", 15)}
          </button>
        </div>
        <div className="park-connectors-drawer-body">
          <div
            className={
              attn ? "park-connectors-band park-connectors-band--attn" : "park-connectors-band"
            }
          >
            <span
              className={
                attn
                  ? "park-connectors-band-dot park-connectors-band-dot--attn"
                  : "park-connectors-band-dot"
              }
            />
            {syncing ? <Spin /> : null}
            <span>{syncing ? "Syncing now…" : drawerSync(c)}</span>
            {attn ? (
              <button
                type="button"
                className="park-connectors-band-action"
                disabled={reconnecting}
                onClick={onReconnect}
              >
                {reconnecting ? <Spin /> : null}
                {reconnecting ? `Waiting for ${c.name}` : "Reconnect"}
              </button>
            ) : null}
          </div>
          <div
            className="park-connectors-group"
            role="radiogroup"
            aria-label="How far agents can go"
          >
            <h3 className="park-connectors-h3">How far agents can go</h3>
            {(c.scopes ?? DEFAULT_SCOPES).map(([sub, lv]) => {
              const on = c.level === lv;
              return (
                <button
                  type="button"
                  // biome-ignore lint/a11y/useSemanticElements: the design's level rows are buttons with role="radio"
                  role="radio"
                  aria-checked={on}
                  key={lv}
                  className={
                    on ? "park-connectors-lvrow park-connectors-lvrow--on" : "park-connectors-lvrow"
                  }
                  onClick={() => onLevel(lv, sub)}
                >
                  <span
                    className={
                      on ? "park-connectors-ring park-connectors-ring--on" : "park-connectors-ring"
                    }
                  >
                    <span
                      className={
                        on
                          ? "park-connectors-radio-dot park-connectors-radio-dot--on"
                          : "park-connectors-radio-dot"
                      }
                    />
                  </span>
                  <span className="park-connectors-lvtext">
                    <span className="park-connectors-lvlabel">{LEVEL_LABEL[lv]}</span>
                    <span className="park-connectors-lvsub">{sub}</span>
                  </span>
                </button>
              );
            })}
            <div className="park-connectors-ceiling">{ceilingOf(c.level)}</div>
          </div>
          <div className="park-connectors-group">
            <h3 className="park-connectors-h3">Used by</h3>
            {used.map((row) => (
              <button
                type="button"
                key={`${row.kind}:${row.name}`}
                className="park-connectors-usedrow"
                title={USED_TITLE[row.kind]}
                onClick={() => onUsed(row)}
              >
                <span className="park-connectors-usedicon">{icon(USED_ICON[row.kind], 14)}</span>
                <span className="park-connectors-usedname">{row.name}</span>
                {icon("chevR", 12)}
              </button>
            ))}
          </div>
          <div className="park-connectors-note">
            Access uses the tool’s own sign-in. You can revoke it here or from {c.name} at any time.
            Team rules for spend and sharing still apply on top.
          </div>
          {attn ? (
            <div className="park-connectors-note">
              You sign in on {c.name}’s own page. Tilo never sees your password.
            </div>
          ) : null}
        </div>
        <div className="park-connectors-drawer-foot">
          <button type="button" className="park-connectors-disconnect" onClick={onDisconnect}>
            Disconnect
          </button>
          <button
            type="button"
            className="park-connectors-sync-now"
            disabled={syncing || attn}
            title={attn ? "Reconnect first" : undefined}
            onClick={onSync}
          >
            {icon("refresh", 15)}Sync now
          </button>
        </div>
      </aside>
    </>
  );
}
