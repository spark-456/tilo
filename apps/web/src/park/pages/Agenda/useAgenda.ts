// Loads the Agenda through the Park Api and keeps its `source` (HR-1..HR-7): a NotBuilt rejection (the live
// Api before its endpoint exists) is its own state, and the page shows "Not connected yet", never sample
// pins. `useAgendaUi` holds the page's own UI state (the reference's `state`), seeded from the Api data.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "../../api/index";
import { NotBuilt } from "../../api/liveApi";
import type { Agenda, AgendaPin, AgendaSlot, Source } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { type BoardKey, type Flags, addPin, blockFocus, bookedPins } from "./model";

export type AgendaState =
  | { status: "loading" }
  | { status: "ready"; data: Agenda; source: Source }
  | { status: "not-built" }
  | { status: "error" };

export function useAgenda(api: Api): AgendaState {
  const [state, setState] = useState<AgendaState>({ status: "loading" });
  useEffect(() => {
    let live = true;
    api.getAgenda().then(
      (r) => live && setState({ status: "ready", data: r.data, source: r.source }),
      (e: unknown) => live && setState({ status: e instanceof NotBuilt ? "not-built" : "error" }),
    );
    return () => {
      live = false;
    };
  }, [api]);
  return state;
}

export function useAgendaUi(A: Agenda, app: AppCtx, api: Api) {
  const [style, setStyle] = useState<"cork" | "soft">("cork");
  const [newVal, setNewVal] = useState<Record<BoardKey, string>>({ team: "", me: "" });
  const [pins, setPins] = useState<AgendaPin[]>(A.pins);
  const [cals, setCals] = useState<Record<string, boolean>>({
    work: true,
    personal: true,
    tilo: true,
  });
  const [weekend, setWeekend] = useState(false);
  const [sel, setSel] = useState("sync");
  const [finding, setFinding] = useState(false);
  const [booked, setBooked] = useState<AgendaSlot | null>(null);
  const [flags, setFlags] = useState<Flags>({});
  const [briefed, setBriefed] = useState<Record<string, boolean>>({});
  const [done, setDone] = useState<Record<string, boolean>>({});
  const counter = useRef(0);

  const findTime = useCallback(() => {
    if (booked) app.toast(`Already booked for ${booked.l}`);
    else setFinding(true);
  }, [booked, app]);

  return {
    style,
    setStyle,
    newVal,
    setNewVal: (key: BoardKey, v: string) => setNewVal((s) => ({ ...s, [key]: v })),
    pins,
    cals,
    toggleCal: (k: string) => setCals((c) => ({ ...c, [k]: !c[k] })),
    weekend,
    toggleWeekend: () => setWeekend((w) => !w),
    sel,
    select: setSel,
    finding,
    cancelFind: () => setFinding(false),
    findTime,
    booked,
    flags,
    briefed,
    done,
    setDone: (id: string, on: boolean) => setDone((d) => ({ ...d, [id]: on })),
    dismiss: (id: string) => setPins((ps) => ps.filter((q) => q.id !== id)),
    add: (key: BoardKey) => {
      const v = newVal[key].trim();
      if (!v) return;
      counter.current += 1;
      setPins((ps) => addPin(ps, key, v, `n${counter.current}`));
      setNewVal((s) => ({ ...s, [key]: "" }));
    },
    block: (id: string) => {
      setPins((ps) => blockFocus(ps, id));
      app.toast("Blocked 09:30–11:30 on Monday in Google Calendar");
    },
    book: (s: AgendaSlot) =>
      api.bookSlot(s).then(
        () => {
          setPins((ps) => bookedPins(ps, s));
          setFinding(false);
          setBooked(s);
          setSel("gate");
          app.toast(`Booked ${s.l}. Invites sent from Google Calendar`);
        },
        () => app.toast("Not connected yet"),
      ),
    flip: (id: string, k: "join" | "pins" | "brief", cur: boolean, title: string) => {
      setFlags((f) => ({ ...f, [`${id}:${k}`]: !cur }));
      if (k === "join") app.toast(cur ? "Tilo won’t join this one" : `Tilo will join ${title}`);
    },
    askBrief: (id: string, title: string) => {
      setBriefed((b) => ({ ...b, [id]: true }));
      app.toast(`Tilo will brief you 15 minutes before ${title}`);
    },
  };
}

export type AgendaUi = ReturnType<typeof useAgendaUi>;
