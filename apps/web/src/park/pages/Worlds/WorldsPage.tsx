// The Worlds page (design_handoff_tilo_web_app/design/"Tilo App Worlds.dc.html", ported to React; plan section
// 10). Data comes only from the Api (getWorlds, getDecisions, getPlans for the city art, getConnectors for
// FR-UX-17 Share to Slack); a person moves with app.go and approves with app.decide. Filters are page state.
// No timers: nothing here moves by itself.
import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoutinesClient } from "../../api/live/routines";
import type { Connector, Decision, Plan, World } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
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
import { SampleControls } from "../../sample/SampleControls";
import { hideSample, showSample } from "../../sample/sampleChoice";
import { CityCard, TownCard, VillageCard } from "./Cards";
import { Filters } from "./Filters";
import { Header } from "./Header";
import { RoutinesPanel } from "./RoutinesPanel";
import { CardSkeleton, EmptyBox, LoadingWorlds, Section } from "./Sections";
import { Spotlight } from "./Spotlight";
import { makeArt, makeKit } from "./art";
import "./Worlds.css";
import { type StatusFilter, type TierFilter, countFor, statusOf, visibleWorlds } from "./model";

interface Loaded {
  worlds: World[];
  decisions: Decision[];
  /** The worlds came from tilo-api: only then is there a sample project to hide or show (STARTER-1). */
  live: boolean;
  connectors: Connector[];
}

export function WorldsPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
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
    Promise.all([
      api.getWorlds(dec, added),
      api.getDecisions().catch(() => ({ data: [] as Decision[] })),
      api.getPlans(dec).catch(() => ({ data: {} as Record<string, Plan> })),
      readConnectors,
    ]).then(
      ([w, d, p, c]) => {
        if (!live) return;
        plans.current = p.data;
        setData({
          worlds: w.data,
          live: w.source === "live",
          decisions: d.data,
          connectors: c.data,
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
  const by = (scale: World["tier"]) => list.filter((w) => w.tier === scale);
  const cities = by("City");
  const towns = by("Town");
  const villages = by("Village");
  // Cards are drawn one per task, in page order (the grids are auto-fill, so a card added later moves none).
  const part = useStaged(2 + cities.length + towns.length + villages.length);
  const at = (scale: World["tier"], i: number): number =>
    3 + i + (scale === "City" ? 0 : cities.length + (scale === "Town" ? 0 : towns.length));

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
        <Header
          art={art}
          total={data ? all.length : null}
          query={query}
          onQuery={setQuery}
          onNew={() => app.go("home")}
          slack={slackState}
          onShareSlack={openSlackDialog}
        />
        {routines ? <RoutinesPanel client={routines} /> : null}
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
                  onChange={(e: ChangeEvent<HTMLSelectElement>) => setSlackWorldId(e.target.value)}
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
                  onChange={(e: ChangeEvent<HTMLSelectElement>) => setSlackChannel(e.target.value)}
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
                <button type="button" className="park-worlds-dec__open" onClick={closeSlackDialog}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        ) : null}
        {failed ? (
          <EmptyBox title="Worlds data is unavailable" />
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
            <Filters
              status={status}
              tier={tier}
              count={(f) => countFor(all, query, tier, f)}
              onStatus={setStatus}
              onTier={setTier}
            />
            {/* Keep the decision summary above the grids in place while card art is staged. */}
            <Spotlight
              art={art}
              decisions={data.decisions}
              worldName={all.find((w) => w.id === data.decisions[0]?.world)?.name ?? ""}
              dec={dec}
              needsLeft={needsLeft}
              onDecide={(key) => app.decide(key)}
              onOpen={open}
              slackPending={slackPending}
            />
            {cities.length > 0 ? (
              <Section scale="City" count={cities.length}>
                {cities.map((w, i) =>
                  part(at("City", i)) ? (
                    <CityCard
                      key={w.id}
                      w={w}
                      art={art}
                      status={statusOf(w, needsLeft)}
                      onOpen={open}
                    />
                  ) : (
                    <CardSkeleton key={w.id} scale="City" />
                  ),
                )}
              </Section>
            ) : null}
            {towns.length > 0 ? (
              <Section scale="Town" count={towns.length}>
                {towns.map((w, i) =>
                  part(at("Town", i)) ? (
                    <TownCard
                      key={w.id}
                      w={w}
                      art={art}
                      status={statusOf(w, needsLeft)}
                      onOpen={open}
                    />
                  ) : (
                    <CardSkeleton key={w.id} scale="Town" />
                  ),
                )}
              </Section>
            ) : null}
            {villages.length > 0 ? (
              <Section scale="Village" count={villages.length}>
                {villages.map((w, i) =>
                  part(at("Village", i)) ? (
                    <VillageCard
                      key={w.id}
                      w={w}
                      art={art}
                      status={statusOf(w, needsLeft)}
                      onOpen={open}
                    />
                  ) : (
                    <CardSkeleton key={w.id} scale="Village" />
                  ),
                )}
              </Section>
            ) : null}
            {list.length === 0 ? (
              <EmptyBox
                title={status === "needs" ? "Nothing needs you right now" : "No worlds match"}
                body="Try another filter, or start something new from Home."
              />
            ) : null}
          </>
        ) : (
          <LoadingWorlds />
        )}
      </PageSheet>
    </div>
  );
}
