// Park Connectors page (WEB-11; design `Tilo App Connectors.dc.html`, inventory.md). Data comes through
// useParkApi(); navigation only through app.go; toasts through app.toast with the design's exact copy.
//
// The Api has no connector write yet (README lists connector reconnect/sync as a call to add), so Connect,
// Reconnect, Disconnect and the access level are page-local state, as in the design. The design waits 1.4 s
// and 1.5 s on timers; page code holds no timer before WEB-3b, so the wait is one awaited step: the busy
// label shows at once and the result lands on the promise continuation. The S-08 consent hand-off belongs to
// live mode, when the Api has a connect endpoint. The "Sample data" chip belongs to the shell.
import { type ReactNode, useCallback, useEffect, useState } from "react";
import type { Connector, ConnectorTerms, Skill } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { PageSheet } from "../../components";
import "./Connectors.css";
import { useLiveTeam } from "../Team/LiveTeam";
import { AttentionBanner, AvailableRow, ConnectedTile } from "./ConnectorParts";
import { Drawer } from "./Drawer";
import { ToolAccess } from "./ToolAccess";
import { icon } from "./icons";
import { type Overrides, isOn, matches, merge } from "./view";

type Load =
  | { kind: "loading" }
  | { kind: "ready"; connectors: Connector[]; skills: Skill[]; terms: ConnectorTerms }
  | { kind: "unavailable" };

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

export function ConnectorsPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [over, setOver] = useState<Overrides>({ st: {}, lvl: {} });
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [reconnecting, setReconnecting] = useState(false);

  // TEAM-WEB: a live server answers with the team's tool levels; the sample Api (null) and an unbuilt one (a
  // rejection that is not a server answer) leave the page below as it was.
  const lt = useLiveTeam(api);
  const sample = lt.state.phase === "fixture";
  useEffect(() => {
    if (!sample) return;
    let live = true;
    Promise.all([api.getConnectors(), api.getSkills(), api.getConnectorTerms()]).then(
      ([c, s, t]) =>
        live && setLoad({ kind: "ready", connectors: c.data, skills: s.data, terms: t.data }),
      () => live && setLoad({ kind: "unavailable" }),
    );
    return () => {
      live = false;
    };
  }, [api, sample]);

  const close = useCallback(() => setOpen(null), []);

  if (lt.state.phase === "ready" || lt.state.phase === "error") {
    return (
      <Frame>
        <Heading />
        {lt.state.phase === "ready" ? (
          <ToolAccess live={lt} view={lt.state.view} toast={app.toast} />
        ) : (
          <div className="park-connectors-empty">
            <span className="park-connectors-empty-glyph">{icon("plug", 22)}</span>
            <div className="park-connectors-empty-title">Not connected yet</div>
            <div className="park-connectors-empty-line">{lt.state.text}</div>
          </div>
        )}
      </Frame>
    );
  }
  if (load.kind === "unavailable") {
    return (
      <Frame>
        <Heading />
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

  const all = merge(load.connectors, over);
  const on = all.filter((c) => isOn(c) && matches(c, q));
  const avail = all.filter((c) => !isOn(c) && matches(c, q));
  const attn = all.find((c) => c.st === "attention");
  const cur = all.find((c) => c.id === open);
  const nOn = `${on.length} connected`;
  const skillIds = new Map(load.skills.map((s) => [s.name, s.id]));

  const settle = (id: string, level: number) =>
    setOver((o) => ({ st: { ...o.st, [id]: "connected" }, lvl: { ...o.lvl, [id]: level } }));
  const connect = (c: Connector) => {
    setBusy((b) => ({ ...b, [c.id]: true }));
    void Promise.resolve().then(() => {
      setBusy((b) => ({ ...b, [c.id]: false }));
      settle(c.id, 1);
      app.toast(`${c.name} connected with Read access`);
    });
  };
  const reconnect = (c: Connector) => {
    if (reconnecting) return;
    setReconnecting(true);
    void Promise.resolve().then(() => {
      setReconnecting(false);
      setOver((o) => ({ ...o, st: { ...o.st, [c.id]: "connected" } }));
      app.toast(`${c.name} reconnected for ${load.terms.reconnectDays} days`);
    });
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

      {attn ? (
        <AttentionBanner c={attn} waiting={reconnecting} onReconnect={() => reconnect(attn)} />
      ) : null}

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
            <AvailableRow key={c.id} c={c} busy={!!busy[c.id]} onConnect={() => connect(c)} />
          ))}
        </div>
      </section>

      {cur ? (
        <Drawer
          c={cur}
          skillIds={skillIds}
          onClose={close}
          onLevel={(level, sub) => {
            setOver((o) => ({ ...o, lvl: { ...o.lvl, [cur.id]: level } }));
            app.toast(`${cur.name}: agents can now ${sub.toLowerCase()}`);
          }}
          onUsed={(name) => {
            setOpen(null);
            const id = skillIds.get(name);
            if (id) app.go("skills", { id });
            else app.go("agenda");
          }}
          onDisconnect={() => {
            setOpen(null);
            setOver((o) => ({ ...o, st: { ...o.st, [cur.id]: "available" } }));
            app.toast(`${cur.name} disconnected. Skills that use it will pause`);
          }}
          onSync={() => app.toast(`Syncing ${cur.name}…`)}
        />
      ) : null}
    </Frame>
  );
}
