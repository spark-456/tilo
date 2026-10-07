// The Worlds page (design_handoff_tilo_web_app/design/"Tilo App Worlds.dc.html", ported to React; plan section
// 10). Data comes only from the Api (getWorlds, getDecisions, getPlans for the city art); a person moves with
// app.go and approves with app.decide. Filters are page state. No timers: nothing here moves by itself.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Decision, Plan, World } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { useStaged } from "../../app/useStaged";
import { PageSheet } from "../../components";
import { CityCard, TownCard, VillageCard } from "./Cards";
import { Filters } from "./Filters";
import { Header } from "./Header";
import { EmptyBox, Section } from "./Sections";
import { Spotlight } from "./Spotlight";
import { makeArt, makeKit } from "./art";
import "./Worlds.css";
import { type StatusFilter, type TierFilter, countFor, statusOf, visibleWorlds } from "./model";

interface Loaded {
  worlds: World[];
  decisions: Decision[];
}

export function WorldsPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const { dec, added, needsLeft, night } = app;
  const plans = useRef<Record<string, Plan>>({});
  const kit = useMemo(() => makeKit(() => plans.current), []);
  const [data, setData] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [tier, setTier] = useState<TierFilter>("all");
  const [query, setQuery] = useState("");
  // The sections are drawn top to bottom, one task each, so the page never holds the main thread (WEB-MOTION-2).

  useEffect(() => {
    let live = true;
    Promise.all([
      api.getWorlds(dec, added),
      api.getDecisions(),
      api.getPlans(dec).catch(() => ({ data: {} as Record<string, Plan> })),
    ]).then(
      ([w, d, p]) => {
        if (!live) return;
        plans.current = p.data;
        setData({ worlds: w.data, decisions: d.data });
        setFailed(false);
      },
      () => {
        if (live) setFailed(true);
      },
    );
    return () => {
      live = false;
    };
  }, [api, dec, added]);

  // One object per input, so the memoised cards below are not rendered again for nothing.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `data` is when the plans in the ref have arrived
  const art = useMemo(() => makeArt(kit, () => plans.current, dec, night), [kit, dec, night, data]);
  const go = useRef(app.go);
  go.current = app.go;
  const open = useCallback((id: string) => go.current("world", { id }), []);
  const all = data?.worlds ?? [];
  const list = visibleWorlds(all, query, tier, status);
  const by = (scale: World["tier"]) => list.filter((w) => w.tier === scale);
  const cities = by("City");
  const towns = by("Town");
  const villages = by("Village");
  // Cards are drawn one per task, in page order (the grids are auto-fill, so a card added later moves none).
  const part = useStaged(2 + cities.length + towns.length + villages.length);
  const at = (scale: World["tier"], i: number): number =>
    3 + i + (scale === "City" ? 0 : cities.length + (scale === "Town" ? 0 : towns.length));

  return (
    <div data-testid="park-page-worlds">
      <PageSheet>
        <Header
          art={art}
          total={data ? all.length : null}
          query={query}
          onQuery={setQuery}
          onNew={() => app.go("home")}
        />
        {failed ? (
          <EmptyBox title="Not connected yet" />
        ) : data ? (
          <>
            <Filters
              status={status}
              tier={tier}
              count={(f) => countFor(all, query, tier, f)}
              onStatus={setStatus}
              onTier={setTier}
            />
            {part(2) ? (
              <Spotlight
                art={art}
                decisions={data.decisions}
                worldName={all.find((w) => w.id === data.decisions[0]?.world)?.name ?? ""}
                dec={dec}
                needsLeft={needsLeft}
                onDecide={(key) => app.decide(key)}
                onOpen={open}
              />
            ) : null}
            {part(at("City", 0)) && cities.length > 0 ? (
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
                  ) : null,
                )}
              </Section>
            ) : null}
            {part(at("Town", 0)) && towns.length > 0 ? (
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
                  ) : null,
                )}
              </Section>
            ) : null}
            {part(at("Village", 0)) && villages.length > 0 ? (
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
                  ) : null,
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
        ) : null}
      </PageSheet>
    </div>
  );
}
