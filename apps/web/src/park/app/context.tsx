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
import { API_URL, appCheckToken, authToken } from "../../api/ClientProvider";
export { endSession } from "../../api/signOut"; // FR-UX-10: the shell's Sign out, through the one api seam
import { API_METHODS, type Api, type ApiMethod } from "../api/index";
import { parkApi } from "../api/select";
import type { ApiResult, Source } from "../api/types";
import type { AppCtx } from "./AppCtx";
import { type Pin, screenPins } from "./pins";
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
  schedule: Schedule;
  /** The default Api is the fixture one, so every page will read sample data (no injected Api, no url). */
  expectsSample: boolean;
}

interface Viewport {
  vw: number;
  vh: number;
}

interface PinsChannel {
  raw: readonly Pin[];
  set: (pins: readonly Pin[]) => void;
}

const HeldContext = createContext<Held | null>(null);
// The backdrop (shell/CityBackdrop) reports the scene's pin points here; useApp turns them into `pins`.
const PinsContext = createContext<PinsChannel | null>(null);
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
const NO_RAW_PINS: readonly Pin[] = [];
const windowSize = () => ({ vw: window.innerWidth, vh: window.innerHeight });

export function ParkProvider({ api, navigate, schedule, viewport, children }: ParkProviderProps) {
  const [held] = useState<Held>(() => {
    // SEC-10, SEC-15: the live Api's requests carry the App Check token and the sign-in token; none on local hosts or in fixture mode.
    const raw = api ?? parkApi({ VITE_TILO_API_URL: API_URL }, appCheckToken, authToken);
    let store: ParkStore | null = null;
    const wrapped = noting(raw, (source) => store?.noteSource(source));
    const timer = schedule ?? realSchedule;
    store = createParkStore({
      api: wrapped,
      navigate: navigate ?? navigatePark,
      schedule: timer,
    });
    return { store, api: wrapped, schedule: timer, expectsSample: api === undefined && !API_URL };
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
  useEffect(() => () => held.store.dispose(), [held]); // no timer outlives the app
  const size = viewport ?? win;
  const sized = useMemo(() => ({ vw: size.vw, vh: size.vh }), [size.vw, size.vh]);
  const [raw, setRaw] = useState<readonly Pin[]>(NO_RAW_PINS);
  const channel = useMemo(() => ({ raw, set: setRaw }), [raw]);
  return (
    <HeldContext.Provider value={held}>
      <ViewportContext.Provider value={sized}>
        <PinsContext.Provider value={channel}>{children}</PinsContext.Provider>
      </ViewportContext.Provider>
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
/** The provider's timer: a page that waits (the Home composer's 900 ms) goes through it, never setTimeout. */
export const useSchedule = (): Schedule => useHeld().schedule;

/** True when the Sample data chip is going to show (the fixture Api is the default), so its place can be kept. */
export const useExpectsSample = (): boolean => useHeld().expectsSample;

/** For the city backdrop: where the three map pins sit on the scene (1600x1000). */
export function useReportPins(): (pins: readonly Pin[]) => void {
  const channel = useContext(PinsContext);
  if (!channel) throw new Error("ParkProvider is missing");
  return channel.set;
}

export function useApp(): AppCtx {
  const { store } = useHeld();
  const { vw, vh } = useContext(ViewportContext);
  const rawPins = useContext(PinsContext)?.raw ?? NO_RAW_PINS;
  const pins = useMemo(
    () => (rawPins.length === 0 ? EMPTY_PINS : screenPins(rawPins, vw, vh)),
    [rawPins, vw, vh],
  );
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
      pins,
      ready: true,
    }),
    [store, page, params, dec, needsLeft, added, time, motion, prefs, vw, vh, pins],
  );
}

/**
 * The `app` a page receives: `useApp()` with `go` sending a world through the loader first (README: opening
 * a world always runs the WorldLoader), everything else (a world without an id too: the worlds list) straight to its page. `useApp().go` itself stays
 * immediate, so the shell has one way to jump without the loader.
 */
export function usePageApp(): AppCtx {
  const app = useApp();
  const { store } = useHeld();
  return useMemo(
    () => ({
      ...app,
      go: (page, params) =>
        page === "world" && params?.id ? store.openWorld(params.id) : store.go(page, params),
    }),
    [app, store],
  );
}
