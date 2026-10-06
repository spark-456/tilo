// THROWAWAY (WEB-3b validation only): stand-in for the WEB-3a context.
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import { API_METHODS, type Api } from "../api/index";
import { parkApi } from "../api/select";
import type { AppCtx } from "./AppCtx";
import { parseParkPath } from "./router";
import { type ParkStore, type Schedule, createParkStore, realSchedule } from "./store";

interface Ctx {
  store: ParkStore;
  api: Api;
  vw: number;
  vh: number;
  route: { page: AppCtx["page"]; params: AppCtx["params"] } | null;
}
const C = createContext<Ctx | null>(null);
const need = (): Ctx => {
  const c = useContext(C);
  if (!c) throw new Error("no ParkProvider");
  return c;
};

const listeners = new Set<() => void>();
const defaultNavigate = (to: string) => {
  window.history.pushState({}, "", to);
  for (const l of listeners) l();
};
const subLoc = (l: () => void) => {
  listeners.add(l);
  window.addEventListener("popstate", l);
  return () => {
    listeners.delete(l);
    window.removeEventListener("popstate", l);
  };
};

export function ParkProvider(props: {
  api?: Api;
  navigate?: (to: string) => void;
  schedule?: Schedule;
  viewport?: { vw: number; vh: number };
  children: ReactNode;
}) {
  const [{ store, api }] = useState(() => {
    const raw = props.api ?? parkApi(import.meta.env);
    let store!: ParkStore;
    const wrapped = {} as Record<string, unknown>;
    for (const m of API_METHODS) {
      const fn = raw[m] as (...a: never[]) => Promise<{ data: unknown; source: "fixture" | "live" }>;
      wrapped[m] = (...a: never[]) =>
        fn(...a).then((r) => {
          store.noteSource(r.source);
          return r;
        });
    }
    store = createParkStore({
      api: raw,
      navigate: props.navigate ?? defaultNavigate,
      schedule: props.schedule ?? realSchedule,
    });
    return { store, api: wrapped as unknown as Api };
  });
  const [win, setWin] = useState({ vw: window.innerWidth, vh: window.innerHeight });
  useEffect(() => {
    if (props.viewport) return;
    const on = () => setWin({ vw: window.innerWidth, vh: window.innerHeight });
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, [props.viewport]);
  const pathname = useSyncExternalStore(subLoc, () => window.location.pathname + window.location.search);
  const route = useMemo(() => {
    const [p, s] = pathname.split("?");
    return parseParkPath(p ?? "", s ? `?${s}` : "");
  }, [pathname]);
  const v = props.viewport ?? win;
  const value = useMemo(() => ({ store, api, vw: v.vw, vh: v.vh, route }), [store, api, v.vw, v.vh, route]);
  return <C.Provider value={value}>{props.children}</C.Provider>;
}

export const useParkStore = (): ParkStore => need().store;
export const useParkApi = (): Api => need().api;

export function useApp(): AppCtx {
  const { store, vw, vh, route } = need();
  const s = useSyncExternalStore(store.subscribe, store.getState);
  const go = useCallback((page: AppCtx["page"], params?: AppCtx["params"]) => store.go(page, params), [store]);
  return useMemo(
    () => ({
      page: route?.page ?? "home",
      params: route?.params ?? {},
      go,
      dec: s.dec,
      decide: store.decide,
      needsLeft: s.needsLeft,
      added: [...s.added],
      addWorld: store.addWorld,
      toast: store.toast,
      time: s.time,
      night: s.time === "night",
      motion: s.motion,
      setPref: store.setPref,
      prefs: { ...s.prefs },
      vw,
      vh,
      pins: s.pins.map((p) => ({ x: p.x, y: p.y })),
      ready: true,
    }),
    [store, go, route, s.dec, s.needsLeft, s.added, s.time, s.motion, s.prefs, s.pins, vw, vh],
  );
}
