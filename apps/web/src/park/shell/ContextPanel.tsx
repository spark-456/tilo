import { type ReactNode, useCallback, useEffect, useState } from "react";
import type { Api } from "../api";
import type { AgendaData, ApiResult, WorldState } from "../api/types";
import { useApp, useParkApi } from "../app/context";
import { useParkRoute } from "../app/router";
import { Button, Popover } from "../components";
import "./ContextPanel.css";
const memory = new Map<string, boolean>();
function keyOf(person: string): string {
  let hash = 0x811c9dc5;
  for (const c of person.trim().toLowerCase()) hash = Math.imul(hash ^ c.charCodeAt(0), 0x01000193);
  return `tilo.park.context.${(hash >>> 0).toString(16)}`;
}
function read(key: string): boolean {
  try {
    const v = window.localStorage.getItem(key);
    if (v !== null) return v === "1";
  } catch {
    /* blocked storage */
  }
  return memory.get(key) ?? false;
}
export function useContextChoice(person: string): readonly [boolean, () => void] {
  const key = keyOf(person);
  const [choice, setChoice] = useState(() => ({ key, open: read(key) }));
  const open = choice.key === key ? choice.open : read(key);
  const toggle = useCallback(() => {
    const next = !open;
    memory.set(key, next);
    try {
      window.localStorage.setItem(key, next ? "1" : "0");
    } catch {
      /* page memory remains */
    }
    setChoice({ key, open: next });
  }, [key, open]);
  useEffect(() => {
    const shortcut = (e: KeyboardEvent) => {
      const target = e.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || target.closest("input, textarea, select"))
      )
        return;
      if (e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey && e.key.toLowerCase() === "c") {
        e.preventDefault();
        toggle();
      }
    };
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, [toggle]);
  return [open, toggle];
}
type Reads = Pick<
  Api,
  | "getWorlds"
  | "getDecisions"
  | "getAgenda"
  | "getTeam"
  | "getConnectors"
  | "getSkills"
  | "getLedger"
>;
type Data = { [K in keyof Reads]?: Awaited<ReturnType<Reads[K]>> | null };
function Rows<T>({
  label,
  result,
  rows,
}: { label: string; result: ApiResult<T> | null | undefined; rows: (data: T) => string[] }) {
  const values = result
    ? rows(result.data).filter(Boolean)
    : [`${label}: ${result === null ? "not available" : "Loading…"}`];
  return (
    <div>
      <h3>{`${label}${result?.source === "fixture" ? " · Sample data" : ""}`}</h3>
      <ul>
        {(values.length ? values : ["No recorded items."]).map((v, i) => (
          <li key={`${i}:${v}`}>{v}</li>
        ))}
      </ul>
    </div>
  );
}
export function agendaRows(a: AgendaData, future: boolean): string[] {
  if ("plate" in a)
    return [...a.plate.rows, ...(future ? a.plate.parked : [])]
      .filter((r) => {
        const day = (r.ref.kind === "calendar_entry" ? r.at : r.due)?.slice(0, 10) ?? "";
        return future ? day > a.plate.today : day <= a.plate.today;
      })
      .map((r) => [r.title ?? r.ref.kind, r.at ?? r.due].filter(Boolean).join(" · "));
  return a.events
    .filter((e) => !e.past && (future ? e.d > a.today : e.d === a.today))
    .map((e) => e.t);
}
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
export function ContextPanel({ onClose }: { onClose: () => void }) {
  const api = useParkApi();
  const app = useApp();
  const route = useParkRoute();
  const [data, setData] = useState<Data>({});
  const worldId = route?.page === "world" ? route.params.id : null;
  const worlds = (label: string, state: WorldState) => (
    <Rows
      label={label}
      result={data.getWorlds}
      rows={(ws) =>
        ws
          .filter((w) => w.st === state)
          .map((w) => [w.name, w.nextL, w.nextV].filter(Boolean).join(" · "))
      }
    />
  );
  useEffect(() => {
    let current = true;
    setData({});
    const calls = {
      getWorlds: () => api.getWorlds(app.dec, app.added),
      getDecisions: () => api.getDecisions(),
      getAgenda: () => api.getAgenda(),
      getTeam: () => api.getTeam(),
      getConnectors: () => api.getConnectors(),
      getSkills: () => api.getSkills(),
      getLedger: () => api.getLedger(),
    };
    for (const [name, call] of Object.entries(calls))
      call()
        .then((r) => {
          if (current) setData((d) => ({ ...d, [name]: r }));
        })
        .catch(() => {
          if (current) setData((d) => ({ ...d, [name]: null }));
        });
    return () => {
      current = false;
    };
  }, [api, app.dec, app.added]);
  return (
    <Popover label="Your context" className="park-context" onClose={onClose}>
      <header>
        <h2>Your context</h2>
        <Button variant="secondary" size="sm" onClick={onClose}>
          Close context
        </Button>
      </header>
      <Section title="Now">
        {worlds("Runs", "running")}
        <Rows
          label="Waiting for you"
          result={data.getDecisions}
          rows={(ds) => ds.filter((d) => !app.dec[d.k]).map((d) => d.title)}
        />
        <Rows
          label="Today's work and meetings"
          result={data.getAgenda}
          rows={(a) => agendaRows(a, false)}
        />
      </Section>
      <Section title="This project">
        <p>{worldId ? "Recorded project details" : "Open a project to see its context."}</p>
        {worldId && (
          <Rows
            label="Project"
            result={data.getWorlds}
            rows={(ws) =>
              ws
                .filter((w) => w.id === worldId)
                .flatMap((w) => [
                  w.name,
                  w.st,
                  `Recorded spend: ${w.spend}`,
                  w.plan || "Goal and plan are not available.",
                  w.out || "Artifacts are not available.",
                ])
            }
          />
        )}
        {worldId && (
          <Rows
            label="Project decisions"
            result={data.getDecisions}
            rows={(ds) => ds.filter((d) => d.world === worldId).map((d) => d.title)}
          />
        )}
        <p>Agent details and sources used are not available here yet.</p>
      </Section>
      <Section title="Workspace">
        <Rows
          label="Team"
          result={data.getTeam}
          rows={(t) => t.people.map((p) => [p.name, p.role].filter(Boolean).join(" · "))}
        />
        <Rows
          label="Connected tools"
          result={data.getConnectors}
          rows={(cs) =>
            cs.map(
              (c) => `${c.name} · ${c.live?.stateKnown === false ? "state not available" : c.st}`,
            )
          }
        />
        <Rows
          label="Skills"
          result={data.getSkills}
          rows={(ss) => ss.map((s) => `${s.name} · ${s.st}`)}
        />
      </Section>
      <Section title="Past">
        {worlds("Finished runs", "finished")}
        <Rows
          label="Recorded activity"
          result={data.getLedger}
          rows={(l) => l.activity.map((a) => `${a.day} · ${a.what}`)}
        />
        <p>Memory explanations are not available yet.</p>
      </Section>
      <Section title="Future">
        {worlds("Planned work", "scheduled")}
        <Rows
          label="Calendar and agenda"
          result={data.getAgenda}
          rows={(a) => agendaRows(a, true)}
        />
        <p>Routine next-run times and forecasts are not available here yet.</p>
      </Section>
      <Section title="What Tilo knows">
        <p>Knowledge items are not available yet.</p>
      </Section>
      {data.getAgenda && "plate" in data.getAgenda.data && data.getAgenda.data.plate.truncated && (
        <p>This agenda is a partial list. Open Agenda for more.</p>
      )}
    </Popover>
  );
}
