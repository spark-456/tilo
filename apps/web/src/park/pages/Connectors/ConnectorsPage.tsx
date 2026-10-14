// Park Connectors page (WEB-11; design `Tilo App Connectors.dc.html`, inventory.md). Data comes through
// useParkApi(); navigation only through app.go; toasts through app.toast with the design's exact copy.
//
// Live data uses a read-only list with unavailable facts labelled (CX-W1-1). In the demo, Connect, Reconnect,
// Disconnect, the access level and Sync now change nothing and say so (W6 honesty: no OAuth ran, so no tool
// may be shown or announced as connected). The S-08 consent hand-off belongs to live mode, when the Api has
// a connect endpoint. The "Sample data" chip belongs to the shell.
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import type { ConnectFlow } from "../../../api/connect";
import { liveConnectFlow } from "../../../api/connectEnv";
import type { Connector, ConnectorTerms, Skill, World } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { PageSheet } from "../../components";
import "./Connectors.css";
import { AttentionBanner, AvailableRow, ConnectedTile } from "./ConnectorParts";
import { Drawer } from "./Drawer";
import { GoogleAccess } from "./GoogleAccess";
import { LiveConnectors } from "./LiveConnectors";
import { MeetingHostAccess } from "./MeetingHostAccess";
import { icon } from "./icons";
import { type Overrides, type UsedRow, isOn, matches, merge, usedBy } from "./view";

type Load =
  | { kind: "loading" }
  | { kind: "live"; connectors: Connector[] }
  | {
      kind: "ready";
      connectors: Connector[];
      skills: Skill[];
      worlds: World[];
      terms: ConnectorTerms;
    }
  | { kind: "unavailable" };

/** The demo changes no connector, so nothing overrides the loaded list. */
const NO_OVERRIDES: Overrides = { st: {}, lvl: {} };

/** The shell's page contract: one `park-page-<id>` root holding the sheet (as the Placeholder does). */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div data-testid="park-page-connectors">
      <PageSheet>{children}</PageSheet>
    </div>
  );
}

function Heading({ count, children }: { count?: string; children?: ReactNode }) {
  return (
    <div className="park-connectors-top">
      <div className="park-connectors-titles">
        <div className="park-connectors-titlerow">
          <h1 className="park-connectors-h1">Connectors</h1>
          {count ? <span className="park-connectors-count">{count}</span> : null}
        </div>
        <p className="park-connectors-sub">
          The tools your agents can use, and how far each one can go.
        </p>
      </div>
      {children}
    </div>
  );
}

/**
 * `now` is the clock the sign-in warning reads (FR-ACC-04); a test fixes it. The warning needs a connector's
 * `expires`, so a tool with none is never flagged here.
 */
export function ConnectorsPage({
  app,
  now = Date.now,
  flow,
}: { app: AppCtx; now?: () => number; flow?: ConnectFlow | null }) {
  const api = useParkApi();
  // ADR-0035 L4: the live Google connect flow, or null (fixture world, demo session): then the page is exactly as before.
  const live = useMemo(() => (flow === undefined ? liveConnectFlow() : flow), [flow]);
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    // Worlds only feed the "Used by" list: a failed read leaves the skills and drops the worlds.
    void api
      .getConnectors()
      .then(async (c) => {
        if (!live) return;
        if (c.source === "live") {
          setLoad({ kind: "live", connectors: c.data });
          return;
        }
        const worlds = api.getWorlds(app.dec, app.added).then(
          (w) => w.data,
          () => [] as World[],
        );
        const [s, t, w] = await Promise.all([api.getSkills(), api.getConnectorTerms(), worlds]);
        if (live)
          setLoad({ kind: "ready", connectors: c.data, skills: s.data, worlds: w, terms: t.data });
      })
      .catch(() => live && setLoad({ kind: "unavailable" }));
    return () => {
      live = false;
    };
  }, [api, app.dec, app.added]);

  const close = useCallback(() => setOpen(null), []);

  if (load.kind === "live") {
    return (
      <Frame>
        <Heading />
        {live ? <GoogleAccess flow={live} /> : null}
        <MeetingHostAccess flow={live} />
        <LiveConnectors connectors={load.connectors} />
      </Frame>
    );
  }

  if (load.kind === "unavailable") {
    return (
      <Frame>
        <Heading />
        {live ? <GoogleAccess flow={live} /> : null}
        {live ? <MeetingHostAccess flow={live} /> : null}
        <div className="park-connectors-empty">
          <span className="park-connectors-empty-glyph">{icon("plug", 22)}</span>
          <div className="park-connectors-empty-title">Not connected yet</div>
          <div className="park-connectors-empty-line">
            Your tools will show here once this workspace is connected.
          </div>
        </div>
      </Frame>
    );
  }
  if (load.kind === "loading") {
    return (
      <Frame>
        <Heading />
      </Frame>
    );
  }

  const all = merge(load.connectors, NO_OVERRIDES, now());
  const on = all.filter((c) => isOn(c) && matches(c, q));
  const avail = all.filter((c) => !isOn(c) && matches(c, q));
  const attn = all.filter((c) => c.st === "attention");
  const cur = all.find((c) => c.id === open);
  const nOn = `${on.length} connected`;

  // Demo: nothing is stored or sent, so each action is a plain toast and the lists stay as loaded.
  const sample = (c: Connector, what: string) =>
    app.toast(`Sample data: ${c.name} was not ${what}. Sign in to use your own tools.`);
  const openUsed = (row: UsedRow) => {
    setOpen(null);
    if (row.kind === "skill" && row.id) app.go("skills", { id: row.id });
    else if (row.kind === "world" && row.id) app.go("world", { id: row.id });
    else app.go("agenda");
  };

  return (
    <Frame>
      <Heading count={nOn}>
        <div className="park-connectors-search">
          {icon("search", 16)}
          <input
            className="park-connectors-search-input"
            aria-label="Search connectors"
            placeholder="Search 60+ tools"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </Heading>

      {live ? <GoogleAccess flow={live} /> : null}
      {live ? <MeetingHostAccess flow={live} /> : null}

      {attn.map((c) => (
        <AttentionBanner
          key={c.id}
          c={c}
          waiting={false}
          onReconnect={() => sample(c, "reconnected")}
        />
      ))}

      <section className="park-connectors-section" aria-label="Connected">
        <div className="park-connectors-sechead">
          <span className="park-connectors-sectitle">Connected</span>
          <span className="park-connectors-count">{nOn}</span>
        </div>
        <div className="park-connectors-grid">
          {on.map((c) => (
            <ConnectedTile key={c.id} c={c} onOpen={() => setOpen(c.id)} />
          ))}
        </div>
      </section>

      <section className="park-connectors-section" aria-label="Available">
        <div className="park-connectors-sechead">
          <span className="park-connectors-sectitle">Add a tool</span>
          <span className="park-connectors-count">
            Sign in with the tool. Tilo never sees your password.
          </span>
        </div>
        <div className="park-connectors-availgrid">
          {avail.map((c) => (
            <AvailableRow key={c.id} c={c} busy={false} onConnect={() => sample(c, "connected")} />
          ))}
        </div>
      </section>

      {cur ? (
        <Drawer
          c={cur}
          used={usedBy(cur, load.skills, load.worlds)}
          syncing={false}
          reconnecting={false}
          onReconnect={() => sample(cur, "reconnected")}
          onClose={close}
          onLevel={() => sample(cur, "changed")}
          onUsed={openUsed}
          onDisconnect={() => {
            setOpen(null);
            sample(cur, "disconnected");
          }}
          onSync={() => sample(cur, "synced")}
        />
      ) : null}
    </Frame>
  );
}
