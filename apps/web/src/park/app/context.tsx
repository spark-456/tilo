// ParkProvider: one store, one wrapped Api and the viewport for the whole Park app. `useApp()` builds the
// AppCtx a page receives (README "The `app` prop"); `useParkApi()` is the Api a page calls, which notes
// where every result came from so the shell can say whether it shows sample data.
import {
  type ReactNode,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import { API_URL } from "../../api/ClientProvider";
import { API_METHODS, type Api, type ApiMethod } from "../api/index";
import { parkApi } from "../api/select";
import type { ApiResult, Source } from "../api/types";
import type { AppCtx } from "./AppCtx";
import { navigatePark, useParkRoute } from "./router";
import { type ParkStore, type Schedule, createParkStore, realSchedule } from "./store";

export interface ParkProviderProps {
  api?: Api;
  navigate?: (to: string) => void;
  schedule?: Schedule;
  viewport?: Viewport;
  children: ReactNode;
}

interface Held {
  store: ParkStore;
  api: Api;
}

interface Viewport {
  vw: number;
  vh: number;
}

const HeldContext = createContext<Held | null>(null);
const ViewportContext = createContext<Viewport>({ vw: 0, vh: 0 });

type AnyCall = (...args: unknown[]) => Promise<ApiResult<unknown>>;

/** The same Api, each method reporting the `source` of every result it resolves with. */
function noting(api: Api, note: (source: Source) => void): Api {
  const calls = api as unknown as Record<ApiMethod, AnyCall>;
  const wrapped = Object.fromEntries(
    API_METHODS.map((name) => [
      name,
      (...args: unknown[]) =>
        calls[name](...args).then((result) => {
          note(result.source);
          return result;
        }),
    ]),
  );
  return wrapped as unknown as Api;
}

const EMPTY_PINS: AppCtx["pins"] = [];
const windowSize = () => ({ vw: window.innerWidth, vh: window.innerHeight });

export function ParkProvider({ api, navigate, schedule, viewport, children }: ParkProviderProps) {
  const [held] = useState<Held>(() => {
    const raw = api ?? parkApi({ VITE_TILO_API_URL: API_URL });
    let store: ParkStore | null = null;
    const wrapped = noting(raw, (source) => store?.noteSource(source));
    store = createParkStore({
      api: wrapped,
      navigate: navigate ?? navigatePark,
      schedule: schedule ?? realSchedule,
    });
    return { store, api: wrapped };
  });
  const [win, setWin] = useState(windowSize);
  useEffect(() => {
    if (viewport) return;
    const onResize = () =>
      setWin((prev) => {
        const next = windowSize();
        return prev.vw === next.vw && prev.vh === next.vh ? prev : next;
      });
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [viewport]);
  useEffect(() => () => held.store.dismissToast(), [held]); // no timer outlives the app
  const size = viewport ?? win;
  const sized = useMemo(() => ({ vw: size.vw, vh: size.vh }), [size.vw, size.vh]);
  return (
    <HeldContext.Provider value={held}>
      <ViewportContext.Provider value={sized}>{children}</ViewportContext.Provider>
    </HeldContext.Provider>
  );
}

function useHeld(): Held {
  const held = useContext(HeldContext);
  if (!held) throw new Error("ParkProvider is missing");
  return held;
}

export const useParkStore = (): ParkStore => useHeld().store;
export const useParkApi = (): Api => useHeld().api;

export function useApp(): AppCtx {
  const { store } = useHeld();
  const { vw, vh } = useContext(ViewportContext);
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const route = useParkRoute();
  const page = route?.page ?? "home";
  const params = route?.params;
  const { dec, needsLeft, added, time, motion, prefs } = state;
  return useMemo(
    () => ({
      page,
      params: params ?? {},
      go: store.go,
      dec,
      decide: store.decide,
      needsLeft,
      added,
      addWorld: store.addWorld,
      toast: store.toast,
      time,
      night: time === "night",
      motion,
      setPref: store.setPref,
      prefs,
      vw,
      vh,
      pins: EMPTY_PINS,
      ready: true,
    }),
    [store, page, params, dec, needsLeft, added, time, motion, prefs, vw, vh],
  );
}
