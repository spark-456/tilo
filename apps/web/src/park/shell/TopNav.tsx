// The top nav (README "Shell > Nav"; reference `Tilo App.dc.html` header): a fixed glass bar with the logo,
// six tabs (an amber badge on Worlds while decisions wait), the day and night toggle, the bell (an amber dot
// until the notifications are read) and the AM avatar (ringed in the hero colour on Profile and
// Connectors). The 3px progress bar on its bottom edge follows the world loader and is static.
import type { MouseEvent } from "react";
import type { PageId } from "../app/AppCtx";
import { parkPath } from "../app/router";
import { SampleChip } from "./SampleChip";
import { icon } from "./kit";

const TABS: readonly (readonly [PageId, string])[] = [
  ["home", "Home"],
  ["worlds", "Worlds"],
  ["skills", "Skills"],
  ["ledger", "Ledger"],
  ["agenda", "Agenda"],
  ["team", "Team"],
];

/** A plain left click; anything else (new tab, new window, download) is left to the browser. */
const plain = (e: MouseEvent): boolean =>
  e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;

export interface TopNavProps {
  /** The page the address shows, or null on an address that is not a page. */
  page: PageId | null;
  needsLeft: number;
  night: boolean;
  menu: "notif" | "acct" | null;
  unread: boolean;
  initials: string;
  sample: boolean;
  /** The Api is the fixture one, so the chip is coming: keep its place so it moves nothing when it shows. */
  reserveSample: boolean;
  /** The boot splash is up: the nav is laid out but not shown. */
  booting: boolean;
  /** Where the world loader has got to as a percentage, or null when no world is opening. */
  progress: number | null;
  go: (page: PageId) => void;
  onToggleTime: () => void;
  onBell: () => void;
  onAvatar: () => void;
}

export function TopNav(p: TopNavProps) {
  const link = (page: PageId) => (e: MouseEvent) => {
    if (!plain(e)) return;
    e.preventDefault();
    p.go(page);
  };
  const timeLabel = p.night ? "Switch to day" : "Switch to night";
  const ringed = p.menu === "acct" || p.page === "profile" || p.page === "connectors";
  return (
    <header className={`park-shell__nav ${p.booting ? "park-shell__booting" : ""}`}>
      <a
        href={parkPath("home")}
        aria-label="Tilo home"
        className="park-shell__logo"
        onClick={link("home")}
      >
        <div className="park-shell__logomark">
          <div className="park-shell__visor">
            <div className="park-shell__eye" />
            <div className="park-shell__eye" />
          </div>
        </div>
        <div className="park-shell__wordmark">tilo</div>
      </a>
      <nav aria-label="Main" className="park-shell__tabs">
        {TABS.map(([id, label]) => {
          const on = p.page === id || (id === "worlds" && p.page === "world");
          return (
            <a
              key={id}
              href={parkPath(id)}
              aria-current={on ? "page" : undefined}
              className={`park-shell__tab ${on ? "park-shell__tab--on" : ""}`}
              onClick={link(id)}
            >
              {label}
              {id === "worlds" && p.needsLeft > 0 ? (
                <span className="park-shell__badge">{p.needsLeft}</span>
              ) : null}
            </a>
          );
        })}
      </nav>
      <div className="park-shell__tools">
        {p.sample ? <SampleChip /> : p.reserveSample ? <SampleChip ghost /> : null}
        <button
          type="button"
          aria-label={timeLabel}
          title={timeLabel}
          className="park-shell__iconbtn"
          onClick={p.onToggleTime}
        >
          {icon(p.night ? "sun" : "moon", 18)}
        </button>
        <button
          type="button"
          aria-label="Notifications"
          aria-expanded={p.menu === "notif"}
          aria-haspopup="dialog"
          className={`park-shell__iconbtn park-shell__bell ${p.menu === "notif" ? "park-shell__iconbtn--on" : ""}`}
          onClick={p.onBell}
        >
          {icon("bell", 19)}
          {p.unread ? <span className="park-shell__unread" /> : null}
        </button>
        <button
          type="button"
          aria-label="Account menu"
          aria-expanded={p.menu === "acct"}
          aria-haspopup="menu"
          className={`park-shell__avatar ${ringed ? "park-shell__avatar--ring" : ""}`}
          onClick={p.onAvatar}
        >
          {p.initials}
        </button>
      </div>
      <div
        aria-hidden="true"
        className="park-shell__bar"
        style={{ opacity: p.progress === null ? 0 : 1 }}
      >
        <div className="park-shell__barfill" style={{ width: `${p.progress ?? 0}%` }} />
      </div>
    </header>
  );
}
