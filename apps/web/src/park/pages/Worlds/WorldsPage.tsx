// The Worlds page (STUDIO-3, design/studio-v2 "Tilo S Worlds.dc.html"; earlier "Tilo App Worlds.dc.html"): all of
// a person's worlds in one town, the filters, one card per world and the routines that run on a schedule. Data
// comes only from the Api (getWorlds, getDecisions, getPlans for the city art, getConnectors for FR-UX-17 Share to
// Slack, getLedger for the spend so far) and the routines client; a person moves with app.go and approves with
// app.decide. Filters are page state. No timers: nothing here moves by itself.
import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ErrorState, StateAction } from "../../../design/tilo-t";
import { createRoutinesClient } from "../../api/live/routines";
import type { Connector, Decision, Ledger, Plan, World } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { money } from "../../app/ledgerKpis";
import {
  SLACK_NOTE_MAX,
  type SlackShareRequest,
  capSlackNote,
  focusablesIn,
  handleSlackDialogKeyDown,
  slackConnectorState,
} from "../../app/slackShare";
import { useStaged } from "../../app/useStaged";
import { PageSheet } from "../../components";
import { FirstRunOverview } from "../../sample/FirstRunOverview";
import { SampleControls } from "../../sample/SampleControls";
import { hideSample, showSample } from "../../sample/sampleChoice";
import { useFirstRunPreview } from "../../sample/useFirstRunPreview";
import { WorldCard } from "./Cards";
import { Filters } from "./Filters";
import { Header } from "./Header";
import { RoutinesPanel } from "./RoutinesPanel";
import { CardSkeleton, EmptyBox, LoadingWorlds, Section, TownHero } from "./Sections";
import { Spotlight } from "./Spotlight";
import { makeArt, makeKit } from "./art";
import "./Worlds.css";
import {
  type StatusFilter,
  type TierFilter,
  countFor,
  statusOf,
  townCounts,
  visibleWorlds,
} from "./model";

interface Loaded {
  worlds: World[];
  decisions: Decision[];
  /** The worlds came from tilo-api: only then is there a sample project to hide or show (STARTER-1). */
  live: boolean;
  connectors: Connector[];
  /** The ledger's total, in its own currency; null when the read failed or is not built. */
  spent: string | null;
}

export function WorldsPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const preview = useFirstRunPreview();
  const [routines] = useState(createRoutinesClient);
  const { dec, added, needsLeft, night } = app;
  const plans = useRef<Record<string, Plan>>({});
  const kit = useMemo(() => makeKit(() => plans.current), []);
  const [data, setData] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [tier, setTier] = useState<TierFilter>("all");
  const [query, setQuery] = useState("");
  const [reload, setReload] = useState(0); // STARTER-1: Hide / Show sample project read the list again
  const [slackOpen, setSlackOpen] = useState(false);
  const [slackWorldId, setSlackWorldId] = useState("");
  const [slackChannel, setSlackChannel] = useState("");
  const [slackNote, setSlackNote] = useState("");
  const [slackPending, setSlackPending] = useState<SlackShareRequest | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `reload` only asks for the list again (Hide / Show sample project)
  useEffect(() => {
    let live = true;
    const readConnectors =
      typeof api.getConnectors === "function"
        ? api.getConnectors().catch(() => ({ data: [] as Connector[] }))
        : Promise.resolve({ data: [] as Connector[] });
    const readLedger =
      typeof api.getLedger === "function"
        ? api.getLedger().then(
            (r) => r.data,
            () => null,
          )
        : Promise.resolve<Ledger | null>(null);
    Promise.all([
      api.getWorlds(dec, added),
      api.getDecisions().catch(() => ({ data: [] as Decision[] })),
      api.getPlans(dec).catch(() => ({ data: {} as Record<string, Plan> })),
      readConnectors,
      readLedger,
    ]).then(
      ([w, d, p, c, l]) => {
        if (!live) return;
        plans.current = p.data;
        setData({
          worlds: w.data,
          live: w.source === "live",
          decisions: d.data,
          connectors: c.data,
          spent: l && Number.isFinite(l.spent) ? money(l, l.spent) : null,
        });
        setFailed(false);
      },
      () => {
        if (live) setFailed(true);
      },
    );
    return () => {
      live = false;
    };
  }, [api, dec, added, reload]);

  useEffect(() => {
    if (!slackOpen) return;
    const first = focusablesIn(dialogRef.current)[0];
    first?.focus();
  }, [slackOpen]);

  // One object per input, so the memoised cards below are not rendered again for nothing.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `data` is when the plans in the ref have arrived
  const art = useMemo(() => makeArt(kit, () => plans.current, dec, night), [kit, dec, night, data]);
  const go = useRef(app.go);
  go.current = app.go;
  const open = useCallback((id: string) => go.current("world", { id }), []);
  const all = data?.worlds ?? [];
  const slackState = useMemo(
    () => (data ? slackConnectorState(data.connectors) : undefined),
    [data],
  );
  const list = visibleWorlds(all, query, tier, status);
  const counts = useMemo(() => townCounts(all), [all]);
  // Cards are drawn one per task, in page order (the grid is fixed per width, so a card added later moves none).
  const part = useStaged(2 + list.length);

  const openSlackDialog = (trigger: HTMLButtonElement) => {
    if (!slackState?.connected) return;
    triggerRef.current = trigger;
    const defaultWorld = all[0]?.id ?? "";
    setSlackWorldId((cur) => (cur && all.some((w) => w.id === cur) ? cur : defaultWorld));
    setSlackChannel((cur) =>
      cur && slackState.channels.includes(cur) ? cur : (slackState.channels[0] ?? ""),
    );
    setSlackNote("");
    setSlackOpen(true);
  };

  const closeSlackDialog = () => {
    setSlackOpen(false);
    triggerRef.current?.focus();
  };

  const submitSlackApproval = () => {
    if (!data || !slackState) return;
    const targetWorld = all.find((w) => w.id === slackWorldId) ?? all[0];
    if (!targetWorld) return;
    const channel = slackChannel || slackState.channels[0];
    if (!channel) return;
    setSlackPending({
      worldId: targetWorld.id,
      worldName: targetWorld.name,
      channel,
      note: capSlackNote(slackNote),
      sample: !data.live,
    });
    setSlackOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div data-testid="park-page-worlds">
      <PageSheet>
        <div className="park-worlds-stack">
          <Header
            art={art}
            total={data ? all.length : null}
            onNew={() => app.go("home")}
            slack={slackState}
            onShareSlack={openSlackDialog}
          />
          {preview ? <FirstRunOverview page="worlds" app={app} /> : null}
          {slackOpen && slackState ? (
            <div className="park-worlds-slackbackdrop">
              <div
                ref={dialogRef}
                // biome-ignore lint/a11y/useSemanticElements: custom modal dialog with focus trap and role="dialog"
                role="dialog"
                aria-modal="true"
                aria-label="Share to Slack"
                className="park-worlds-slackdialog"
                onKeyDown={(e) => handleSlackDialogKeyDown(e, dialogRef.current, closeSlackDialog)}
              >
                <div className="park-worlds-slackhead">
                  <div className="park-worlds-slacktitle">Share to Slack</div>
                  <div className="park-worlds-slacksub">{slackState.account}</div>
                </div>
                <label className="park-worlds-slackfield">
                  <span className="park-worlds-slacklabel">World</span>
                  <select
                    aria-label="World to share"
                    className="park-worlds-slackselect"
                    value={slackWorldId}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) =>
                      setSlackWorldId(e.target.value)
                    }
                  >
                    {all.map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="park-worlds-slackfield">
                  <span className="park-worlds-slacklabel">Channel</span>
                  <select
                    aria-label="Slack channel"
                    className="park-worlds-slackselect"
                    value={slackChannel}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) =>
                      setSlackChannel(e.target.value)
                    }
                  >
                    {slackState.channels.map((ch) => (
                      <option key={ch} value={ch}>
                        {ch}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="park-worlds-slackfield">
                  <span className="park-worlds-slacklabel">
                    {`Note (optional, up to ${SLACK_NOTE_MAX} characters)`}
                  </span>
                  <textarea
                    aria-label="Optional note"
                    className="park-worlds-slacknote"
                    rows={3}
                    maxLength={SLACK_NOTE_MAX}
                    value={slackNote}
                    onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
                      setSlackNote(capSlackNote(e.target.value))
                    }
                  />
                </label>
                <div className="park-worlds-slackactions">
                  <button
                    type="button"
                    className="park-worlds-dec__yes"
                    onClick={submitSlackApproval}
                  >
                    Ask for approval
                  </button>
                  <button
                    type="button"
                    className="park-worlds-dec__open"
                    onClick={closeSlackDialog}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          ) : null}
          {failed ? (
            <ErrorState
              title="Worlds data is unavailable"
              body="We couldn't load your worlds. Try again."
              action={
                <StateAction
                  icon="refresh"
                  onClick={() => {
                    setData(null);
                    setFailed(false);
                    setReload((n) => n + 1);
                  }}
                >
                  Try again
                </StateAction>
              }
            />
          ) : data ? (
            <>
              {data.live ? (
                <SampleControls
                  listed={all.some((w) => w.sample)}
                  onHide={() => {
                    hideSample();
                    setReload((n) => n + 1);
                  }}
                  onShow={() => {
                    showSample();
                    setReload((n) => n + 1);
                  }}
                />
              ) : null}
              <TownHero counts={counts} night={night} spent={data.spent} />
              {/* Keep the decision summary above the grid in place while card art is staged. */}
              <Spotlight
                art={art}
                decisions={data.decisions}
                worldName={all.find((w) => w.id === data.decisions[0]?.world)?.name ?? ""}
                dec={dec}
                needsLeft={needsLeft}
                onDecide={(key, text, option) =>
                  text === undefined && option === undefined
                    ? app.decide(key)
                    : app.decide(key, text, option)
                }
                onOpen={open}
                slackPending={slackPending}
              />
              <Filters
                art={art}
                status={status}
                tier={tier}
                query={query}
                count={(f) => countFor(all, query, tier, f)}
                onStatus={setStatus}
                onTier={setTier}
                onQuery={setQuery}
              />
              {list.length > 0 ? (
                <Section count={list.length}>
                  {list.map((w, i) =>
                    part(3 + i) ? (
                      <WorldCard
                        key={w.id}
                        w={w}
                        art={art}
                        status={statusOf(w, needsLeft)}
                        onOpen={open}
                      />
                    ) : (
                      <CardSkeleton key={w.id} />
                    ),
                  )}
                </Section>
              ) : (
                <EmptyBox
                  title={status === "needs" ? "Nothing needs you right now" : "No worlds match"}
                  body="Try another filter, or start something new from Home."
                />
              )}
            </>
          ) : (
            <LoadingWorlds />
          )}
          <RoutinesPanel client={routines} />
        </div>
      </PageSheet>
    </div>
  );
}
