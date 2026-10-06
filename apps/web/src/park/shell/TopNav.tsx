// THROWAWAY (WEB-3b validation only).
import { type MouseEvent, type ReactNode, useState, useSyncExternalStore } from "react";
import type { PageId } from "../app/AppCtx";
import { useApp, useParkStore } from "../app/context";
import { Popover, StatusChip } from "../components";
import { getKit } from "./kit";

const NAV: [PageId, string][] = [
  ["home", "Home"],
  ["worlds", "Worlds"],
  ["skills", "Skills"],
  ["ledger", "Ledger"],
  ["agenda", "Agenda"],
  ["team", "Team"],
];

export function TopNav() {
  const app = useApp();
  const store = useParkStore();
  const s = useSyncExternalStore(store.subscribe, store.getState);
  const [chip, setChip] = useState(false);
  const K = getKit();
  const link = (page: PageId) => (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    app.go(page);
  };
  const ring = s.menu === "acct" || app.page === "profile" || app.page === "connectors";
  const label = app.night ? "Switch to day" : "Switch to night";
  return (
    <header className="park-nav">
      <a className="park-nav__logo" href="/park/home" aria-label="Tilo home" onClick={link("home")}>
        <div className="park-nav__tile">
          <div className="park-nav__visor">
            <span className="park-nav__eye" />
            <span className="park-nav__eye" />
          </div>
        </div>
        <div className="park-nav__word">tilo</div>
      </a>
      <nav className="park-nav__tabs" aria-label="Main">
        {NAV.map(([p, text]) => {
          const on = app.page === p || (p === "worlds" && app.page === "world");
          return (
            <a
              key={p}
              href={`/park/${p}`}
              className={`park-nav__tab${on ? " park-nav__tab--on" : ""}`}
              aria-current={on ? "page" : undefined}
              onClick={link(p)}
            >
              {text}
              {p === "worlds" && app.needsLeft > 0 ? (
                <span className="park-nav__badge">{app.needsLeft}</span>
              ) : null}
            </a>
          );
        })}
      </nav>
      <div className="park-nav__right">
        {s.sources.fixture ? (
          <>
            <button
              type="button"
              className="park-nav__chip"
              aria-haspopup="dialog"
              aria-expanded={chip}
              onClick={() => setChip((v) => !v)}
            >
              <StatusChip tone="neutral" size="sm">
                Sample data
              </StatusChip>
            </button>
            {chip ? (
              <Popover label="Sample data" onClose={() => setChip(false)}>
                <p className="park-nav__chip-text">
                  Northwind Ops is a fictional team. Amounts are examples (£), dates are September 2026.
                </p>
              </Popover>
            ) : null}
          </>
        ) : null}
        <button
          type="button"
          className="park-nav__icon"
          aria-label={label}
          title={label}
          onClick={() => app.setPref("time", app.night ? "day" : "night")}
        >
          {K.icon(app.night ? "sun" : "moon", 18) as ReactNode}
        </button>
        <button
          type="button"
          className="park-nav__icon"
          aria-label="Notifications"
          aria-expanded={s.menu === "notif"}
          onClick={() => store.toggleMenu("notif")}
        >
          {K.icon("bell", 19) as ReactNode}
          {!s.read && app.needsLeft > 0 ? <span className="park-nav__unread" /> : null}
        </button>
        <button
          type="button"
          className={`park-nav__avatar${ring ? " park-nav__avatar--ring" : ""}`}
          aria-label="Account menu"
          aria-expanded={s.menu === "acct"}
          onClick={() => store.toggleMenu("acct")}
        >
          AM
        </button>
      </div>
      <div className="park-nav__bar" aria-hidden="true" />
    </header>
  );
}
