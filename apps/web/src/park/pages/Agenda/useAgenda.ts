// Loads the Agenda through the Park Api and keeps its `source` (HR-1..HR-7): a NotBuilt rejection (the live
// Api before its endpoint exists) is its own state, and the page shows "Not connected yet", never sample
// pins. `useAgendaUi` holds the page's own UI state (the reference's `state`), seeded from the Api data.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "../../api/index";
import { NotBuilt } from "../../api/liveApi";
import type { Agenda, AgendaPin, AgendaSlot, Decision, Source } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import {
  type BoardKey,
  DEFAULT_RULE,
  type Flags,
  acceptPin,
  addPin,
  bookedPins,
  defaultEventId,
  findRuleOf,
  indexDecisions,
  ruleOf,
} from "./model";

export type AgendaState =
  | { status: "loading" }
  | { status: "ready"; data: Agenda; decisions: Decision[]; source: Source }
  | { status: "not-built" }
  | { status: "error" };

export function useAgenda(api: Api): AgendaState {
  const [state, setState] = useState<AgendaState>({ status: "loading" });
  useEffect(() => {
    let live = true;
    // The decisions carry the world to open and the words of a taken one; without them (a live Api that
    // does not serve them yet) the page still shows the Agenda, with no world links.
    const decisions = api.getDecisions().then(
      (r) => r.data,
      () => [],
    );
    Promise.all([api.getAgenda(), decisions]).then(
      ([r, d]) =>
        live && setState({ status: "ready", data: r.data, decisions: d, source: r.source }),
      (e: unknown) => live && setState({ status: e instanceof NotBuilt ? "not-built" : "error" }),
    );
    return () => {
      live = false;
    };
  }, [api]);
  return state;
}

export function useAgendaUi(A: Agenda, decisions: Decision[], app: AppCtx, api: Api) {
  const [style, setStyle] = useState<"cork" | "soft">("cork");
  const [newVal, setNewVal] = useState<Record<BoardKey, string>>({ team: "", me: "" });
  const [pins, setPins] = useState<AgendaPin[]>(A.pins);
  const [cals, setCals] = useState<Record<string, boolean>>({
    work: true,
    personal: true,
    tilo: true,
  });
  const [weekend, setWeekend] = useState(false);
  const [sel, setSel] = useState(defaultEventId(A));
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
    decisions: indexDecisions(decisions),
    ruleOf: (pin: AgendaPin) => ruleOf(A, pin),
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
    accept: (pin: AgendaPin) => {
      const rule = ruleOf(A, pin);
      setPins((ps) => acceptPin(ps, pin.id, rule));
      app.toast(rule.toast ?? DEFAULT_RULE.toast ?? "");
    },
    book: (s: AgendaSlot) =>
      api.bookSlot(s).then(
        () => {
          setPins((ps) => bookedPins(ps, s, A));
          setFinding(false);
          setBooked(s);
          setSel(findRuleOf(A)?.find?.event.id ?? defaultEventId(A));
          app.toast(
            `Booked ${s.l} on your Agenda. Invites go out from Google Calendar once it's connected and you approve`,
          );
        },
        () => app.toast("Not connected yet"),
      ),
    flip: (id: string, k: "join" | "pins" | "brief", cur: boolean, title: string) => {
      setFlags((f) => ({ ...f, [`${id}:${k}`]: !cur }));
      if (k === "join") app.toast(cur ? "Tilo won’t join this one" : `Tilo will join ${title}`);
      if (k === "brief")
        app.toast(
          cur ? `No brief before ${title}` : `Tilo will brief you 15 minutes before ${title}`,
        );
    },
    askBrief: (id: string, title: string) => {
      setBriefed((b) => ({ ...b, [id]: true }));
      setFlags((f) => ({ ...f, [`${id}:brief`]: true }));
      app.toast(`Tilo will brief you 15 minutes before ${title}`);
    },
  };
}

export type AgendaUi = ReturnType<typeof useAgendaUi>;
