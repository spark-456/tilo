// The top nav (README "Shell > Nav"; reference `Tilo App.dc.html` header): a fixed glass bar with the logo,
// seven tabs (an amber badge on Needs you while decisions wait, STUDIO-4), the day and night toggle, the bell (an amber dot
// until the notifications are read) and the AM avatar (ringed in the hero colour on Profile and
// Connectors). The 3px progress bar on its bottom edge follows the world loader and the page swap: it fades
// with its opacity and fills with a scaleX (the stylesheet times both).
import { type CSSProperties, type MouseEvent, useState } from "react";
import { PAGE_LABEL, type PageId } from "../app/AppCtx";
import { parkPath } from "../app/router";
import { Menu } from "../components";
import { SampleChip } from "./SampleChip";
import { icon } from "./kit";
import type { Bar } from "./motion";
import { fitTabs } from "./navFit";
import { prefetchPage } from "./prefetch";

const TABS: readonly (readonly [PageId, string])[] = [
  ["home", "Home"],
  ["chat", "Chat"],
  ["worlds", "Worlds"],
  ["skills", "Skills"],
  ["needs", "Needs you"],
  ["ledger", "Ledger"],
  ["agenda", "Agenda"],
  ["team", "Team"],
];

/** The down chevron on the page menu and More buttons. */
function Chevron() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
      <path
        d="M2 4.5 L6 8.5 L10 4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

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
  /** The team's name, for the sample chip's explanation. */
  org: string | null;
  /** The Api is the fixture one, so the chip is coming: keep its place so it moves nothing when it shows. */
  reserveSample: boolean;
  /** The boot splash is up: the nav is laid out but not shown. */
  booting: boolean;
  /** The progress bar: shown or not, and how full (a world opening, or a page change). */
  bar: Bar;
  /** The bar's opacity transition has ended. */
  onBarFaded: () => void;
  go: (page: PageId) => void;
  onToggleTime: () => void;
  onBell: () => void;
  onAvatar: () => void;
  contextOpen?: boolean;
  onContext?: () => void;
  /** QA-DEMO-1 B2: a narrow screen. The six tabs do not fit beside the tools, so one button names the current page
   * and opens a menu of all of them. */
  compact?: boolean;
  /** STUDIO-INT: the window width; the tabs that do not fit beside the tools move into a More menu (0 = all). */
  vw?: number;
}

export function TopNav(p: TopNavProps) {
  const link = (page: PageId) => (e: MouseEvent) => {
    if (!plain(e)) return;
    e.preventDefault();
    p.go(page);
  };
  const [pagesOpen, setPagesOpen] = useState(false);
  // STUDIO-INT: the More menu opens under its button; its left edge is read when it opens.
  const [moreAt, setMoreAt] = useState<number | null>(null);
  const current = TABS.find(([id]) => p.page === id || (id === "worlds" && p.page === "world"));
  // The page's own name, also for Profile and Connectors, which have no tab.
  const shown = current ? current[1] : p.page ? PAGE_LABEL[p.page] : "Pages";
  const timeLabel = p.night ? "Switch to day" : "Switch to night";
  const fit = fitTabs(TABS, p.compact ? 0 : (p.vw ?? 0), {
    sample: p.sample || p.reserveSample,
    badge: p.needsLeft > 0,
  });
  const moreOn = fit.more.find(([id]) => id === current?.[0]);
  const moreWaiting = p.needsLeft > 0 && fit.more.some(([id]) => id === "needs");
  const waitingWords = `${p.needsLeft} decision${p.needsLeft === 1 ? "" : "s"}`;
  const items = (tabs: readonly (readonly [PageId, string])[]) =>
    tabs.map(([id, label]) => {
      const on = current?.[0] === id;
      const waiting = id === "needs" && p.needsLeft > 0 ? waitingWords : "";
      const hint = [on ? "Current page" : "", waiting].filter(Boolean).join(" · ");
      return { id, label, ...(hint ? { hint } : {}), onSelect: () => p.go(id) };
    });
  const ringed = p.menu === "acct" || p.page === "profile" || p.page === "connectors";
  return (
    <>
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
        {p.compact ? (
          <nav aria-label="Main" className="park-shell__pages">
            <button
              type="button"
              className="park-shell__pagebtn"
              aria-haspopup="menu"
              aria-expanded={pagesOpen}
              aria-label={`Pages, now on ${shown}${
                p.needsLeft > 0
                  ? `, ${p.needsLeft} decision${p.needsLeft === 1 ? "" : "s"} waiting`
                  : ""
              }`}
              onClick={() => setPagesOpen(true)}
            >
              <span className="park-shell__pagelabel">{shown}</span>
              {p.needsLeft > 0 ? <span className="park-shell__pagedot" aria-hidden="true" /> : null}
              <Chevron />
            </button>
          </nav>
        ) : (
          <nav aria-label="Main" className="park-shell__tabs">
            {fit.shown.map(([id, label]) => {
              const on = p.page === id || (id === "worlds" && p.page === "world");
              return (
                <a
                  key={id}
                  href={parkPath(id)}
                  aria-current={on ? "page" : undefined}
                  className={`park-shell__tab ${on ? "park-shell__tab--on" : ""}`}
                  onClick={link(id)}
                  onPointerEnter={() => prefetchPage(id)}
                  onFocus={() => prefetchPage(id)}
                >
                  {label}
                  {id === "needs" && p.needsLeft > 0 ? (
                    <span className="park-shell__badge">{p.needsLeft}</span>
                  ) : null}
                </a>
              );
            })}
            {fit.more.length > 0 ? (
              <button
                type="button"
                className={`park-shell__tab park-shell__more ${moreOn ? "park-shell__tab--on" : ""}`}
                aria-haspopup="menu"
                aria-expanded={moreAt !== null}
                aria-label={`More pages${moreOn ? `, now on ${moreOn[1]}` : ""}${
                  moreWaiting ? `, ${waitingWords} waiting` : ""
                }`}
                onClick={(e) => setMoreAt(e.currentTarget.getBoundingClientRect().left)}
              >
                {moreOn ? moreOn[1] : "More"}
                {moreWaiting ? <span className="park-shell__pagedot" aria-hidden="true" /> : null}
                <Chevron />
              </button>
            ) : null}
          </nav>
        )}
        <div className="park-shell__tools">
          {p.onContext && (
            <button
              type="button"
              className="park-shell__iconbtn"
              aria-label="Your context"
              title="Your context (Alt+Shift+C)"
              aria-expanded={p.contextOpen}
              aria-haspopup="dialog"
              onClick={p.onContext}
            >
              {icon("grid", 18)}
            </button>
          )}
          {p.sample ? <SampleChip org={p.org} /> : p.reserveSample ? <SampleChip ghost /> : null}
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
      </header>
      {/* Outside the header: its backdrop-filter would make a fixed panel position against the nav (B2). */}
      {p.compact && pagesOpen ? (
        <Menu
          label="Pages"
          className="park-shell__pagemenu"
          width={240}
          onClose={() => setPagesOpen(false)}
          items={items(TABS)}
        />
      ) : null}
      {!p.compact && moreAt !== null && fit.more.length > 0 ? (
        // The menu is fixed; the variable carries the More button's left edge to it.
        <div style={{ "--park-more-left": `${Math.round(moreAt)}px` } as CSSProperties}>
          <Menu
            label="More pages"
            className="park-shell__pagemenu park-shell__moremenu"
            width={240}
            onClose={() => setMoreAt(null)}
            items={items(fit.more)}
          />
        </div>
      ) : null}
      {/* Over the nav's bottom edge but not inside it: the nav's glass blur must not sit under a moving layer. */}
      <div
        aria-hidden="true"
        className="park-shell__bar"
        style={{ opacity: p.bar.on ? 1 : 0 }}
        onTransitionEnd={(e) => {
          if (e.target === e.currentTarget && e.propertyName === "opacity") p.onBarFaded();
        }}
      >
        <div
          className={`park-shell__barfill ${p.bar.pct === 0 || p.bar.snap ? "park-shell__barfill--rest" : ""}`}
          style={{ transform: `scaleX(${p.bar.pct / 100})` }}
        />
      </div>
    </>
  );
}
