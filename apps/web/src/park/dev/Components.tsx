// /dev/components (WEB-2; PROMPTS step 2): every core component of the Park City design in a day panel and
// a night panel, side by side in one page. Dev build only (routes.tsx); the copy is neutral sample text.
// UX-1: each panel holds exactly one filled primary button. The demos are live (state is local) but start
// no motion and no timers.
import { type ReactNode, createElement, useState } from "react";
import {
  ArtTile,
  Button,
  Card,
  KpiTile,
  ListRow,
  Menu,
  type MenuItem,
  ModalScrim,
  PageSheet,
  SegmentedControl,
  StatusChip,
  SummaryPill,
  Switch,
  Toast,
} from "../components";
import { createKit } from "../engines/kit";
import type { H } from "../engines/types";
import "../tokens/park.css";
import "../tokens/fonts";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));
// One kit for the page (its art is memoised per key).
const kit = createKit(h, { plans: () => ({}) });
const icon = (name: string, size = 16): ReactNode => kit.icon(name, size) as ReactNode;
const agent = (role: string, expr: string, size: number, night: boolean): ReactNode =>
  kit.agent({ role, expr }, size, night) as ReactNode;

const noop = () => undefined;

function Demo({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <div data-demo={id} className="park-dev__demo">
      <h3 className="park-dev__eyebrow">{title}</h3>
      {children}
    </div>
  );
}

function ThemePanel({ time }: { time: "day" | "night" }) {
  const night = time === "night";
  const [entry, setEntry] = useState("all");
  const [level, setLevel] = useState("read");
  const [notes, setNotes] = useState(true);
  const [pins, setPins] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [said, setSaid] = useState("Nothing chosen yet");

  const menuItems: MenuItem[] = [
    { id: "profile", label: "Profile and settings", icon: icon("pen"), onSelect: noop },
    { id: "connectors", label: "Connectors", icon: icon("plug"), hint: "6 on", onSelect: noop },
    { id: "team", label: "Team and roles", icon: icon("shield"), onSelect: noop },
    { id: "mobile", label: "Mobile app", icon: icon("phone"), hint: "Concept", onSelect: noop },
    { id: "signout", label: "Sign out", icon: icon("logout"), onSelect: noop },
  ];
  const liveItems: MenuItem[] = menuItems.map((m) => ({
    ...m,
    onSelect: () => setSaid(`Chose ${m.label}`),
  }));

  return (
    <section
      data-park=""
      data-time={time}
      data-testid={`panel-${time}`}
      className="park-dev__panel"
    >
      <h2 className="park-dev__heading">{night ? "Night" : "Day"}</h2>
      <div className="park-dev__grid">
        <Demo id="button-primary" title="Button, primary">
          <div className="park-dev__row">
            <Button variant="primary">Start a task</Button>
          </div>
        </Demo>

        <Demo id="button-secondary" title="Button, secondary">
          <div className="park-dev__row">
            <Button variant="secondary">Teach another</Button>
            <Button variant="secondary" size="sm">
              Keep learning
            </Button>
            <Button variant="secondary" icon={icon("download")}>
              Export CSV
            </Button>
            <Button variant="secondary" disabled>
              Save changes
            </Button>
          </div>
        </Demo>

        <Demo id="button-needs" title="Button, needs you">
          <div className="park-dev__row">
            <Button variant="needs">Approve £3,420</Button>
            <Button variant="needs" size="sm">
              Add a backup
            </Button>
          </div>
        </Demo>

        <Demo id="seg-plain" title="Segmented control">
          <div className="park-dev__row">
            <SegmentedControl
              label="Entry type"
              options={[
                { value: "all", label: "All" },
                { value: "waiting", label: "Waiting" },
                { value: "spend", label: "Spend" },
                { value: "approvals", label: "Approvals" },
              ]}
              value={entry}
              onChange={setEntry}
            />
          </div>
        </Demo>

        <Demo id="seg-sliding" title="Segmented control, sliding thumb">
          <div className="park-dev__row">
            <SegmentedControl
              label="Tool access"
              options={[
                { value: "off", label: "Off" },
                { value: "read", label: "Read" },
                { value: "draft", label: "Draft" },
                { value: "act", label: "Act" },
              ]}
              value={level}
              onChange={setLevel}
              sliding
              itemWidth={64}
            />
          </div>
        </Demo>

        <Demo id="switch" title="Switch">
          <div className="park-dev__stack">
            <div className="park-dev__label">
              <Switch label="Tilo joins and takes notes" checked={notes} onChange={setNotes} />
              <span>Tilo joins and takes notes</span>
            </div>
            <div className="park-dev__label">
              <Switch label="Turn action items into pins" checked={pins} onChange={setPins} />
              <span>Turn action items into pins</span>
            </div>
          </div>
        </Demo>

        <Demo id="chip" title="Status chip">
          <div className="park-dev__row">
            <StatusChip tone="ok">Trusted</StatusChip>
            <StatusChip tone="hero">Learning</StatusChip>
            <StatusChip tone="amber">Needs an answer</StatusChip>
            <StatusChip tone="neutral">Paused</StatusChip>
          </div>
        </Demo>

        <Demo id="pill" title="Summary pill">
          <div className="park-dev__row">
            <SummaryPill tone="ok">3 trusted</SummaryPill>
            <SummaryPill tone="hero">2 learning</SummaryPill>
            <SummaryPill tone="amber">1 needs your help</SummaryPill>
            <SummaryPill>Nothing waiting</SummaryPill>
          </div>
        </Demo>

        <Demo id="kpi" title="KPI tile">
          <div className="park-dev__kpis">
            <KpiTile label="Spent so far" value="£2,412" sub="30% of £8,000" />
            <KpiTile
              label="Waiting on you"
              value="£3,420"
              sub="Laptop Depot sign-off"
              tone="amber"
              onClick={() => setSaid("Opened the waiting tile")}
            />
            <KpiTile label="Waiting on you" value="£0" sub="Laptop Depot approved" tone="ok" />
            <KpiTile
              label="Hours handed back"
              value="46 h"
              sub="About 6 working days"
              tone="hero"
            />
          </div>
        </Demo>

        <Demo id="list-row" title="List row">
          <div className="park-dev__stack">
            <ListRow
              lead={<ArtTile>{agent("builder", "neutral", 40, night)}</ArtTile>}
              trail={<StatusChip tone="ok">Trusted</StatusChip>}
            >
              <span className="park-row__title">Invoice run</span>
              <span className="park-row__sub">Routine · 3 agents</span>
            </ListRow>
            <ListRow
              lead={<ArtTile tint="amber">{agent("research", "needs", 40, night)}</ArtTile>}
              trail={<StatusChip tone="amber">Needs you</StatusChip>}
              onClick={() => setSaid("Opened Laptop Depot")}
            >
              <span className="park-row__title">Laptop Depot</span>
              <span className="park-row__sub">City · 5 agents</span>
            </ListRow>
            <ListRow
              lead={<ArtTile tint="hero">{agent("builder", "focused", 40, night)}</ArtTile>}
              trail={<StatusChip tone="hero">Learning</StatusChip>}
              selected
              onClick={() => setSaid("Opened Supplier brief")}
            >
              <span className="park-row__title">Supplier brief</span>
              <span className="park-row__sub">Village · 1 agent</span>
            </ListRow>
          </div>
        </Demo>

        <Demo id="art-tile" title="Agent and art tile">
          <div className="park-dev__row">
            <ArtTile>{agent("builder", "neutral", 40, night)}</ArtTile>
            <ArtTile size={58} radius={16} tint="amber">
              {agent("research", "needs", 54, night)}
            </ArtTile>
            <ArtTile size={60} radius={18} tint="hero">
              {agent("builder", "delighted", 56, night)}
            </ArtTile>
            <ArtTile tint="green">{agent("research", "focused", 40, night)}</ArtTile>
          </div>
        </Demo>

        <Demo id="card" title="Card">
          <Card>
            <h4 className="park-dev__title">Cost per run</h4>
            <p className="park-dev__text">
              Each run costs about £0.40 and takes around a minute. Tilo stops to ask before the
              third step.
            </p>
          </Card>
        </Demo>

        <Demo id="page-sheet" title="Page sheet">
          <PageSheet>
            <h4 className="park-dev__title">Ledger</h4>
            <p className="park-dev__text">
              A page sheet holds the sections of one page, with the same gap between them.
            </p>
          </PageSheet>
        </Demo>

        <Demo id="toast" title="Toast">
          <Toast
            inline
            message="Approved £3,420 for Laptop Depot"
            actionLabel="Undo"
            onDismiss={noop}
          />
        </Demo>

        <Demo id="menu-static" title="Menu">
          <Menu inline label="Account example" width={300} items={menuItems} onClose={noop} />
        </Demo>

        <Demo id="menu-live" title="Menu, live (Escape or a click outside closes it)">
          <div className="park-dev__stack">
            <div className="park-dev__row">
              <Button
                variant="secondary"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen(true)}
              >
                Open the menu
              </Button>
              <span className="park-dev__text" aria-live="polite">
                {said}
              </span>
            </div>
            {menuOpen ? (
              <Menu
                label="Account"
                width={300}
                items={liveItems}
                onClose={() => setMenuOpen(false)}
              />
            ) : null}
          </div>
        </Demo>

        <Demo id="scrim" title="Modal scrim">
          <ModalScrim inline>
            <Card>
              <h4 className="park-dev__title">Opening the world</h4>
              <p className="park-dev__text">The scrim dims what is behind a modal.</p>
            </Card>
          </ModalScrim>
        </Demo>
      </div>
    </section>
  );
}

export function Components() {
  return (
    <div
      data-testid="dev-components"
      style={{ display: "flex", flexDirection: "column", gap: 24, padding: 12 }}
    >
      <h1 style={{ margin: 0 }}>Park City components</h1>
      <ThemePanel time="day" />
      <ThemePanel time="night" />
    </div>
  );
}
