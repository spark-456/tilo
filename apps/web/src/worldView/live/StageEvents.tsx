// TILO-T-WORLD: the stage's event-driven moments that are not an agent walking: the delivery parcel, the confetti when
// the world completes, and the card that says plainly why a world stopped. Each starts only when its recorded event
// ARRIVES while the page is open (never for history that was already there, never on a timer of its own) and names
// that event beside the start (design/tilo-t PROMPT.md section 3, HR-1, HR-3). Under reduced motion the global fallback
// in design/tilo-t/motion.css leaves only a fade.
import type { Event, Layout } from "@tilo/contracts";
import { useEffect, useMemo, useRef, useState } from "react";
import { registerProbe } from "../../world/spotlight";
import "./live.css";

const CONFETTI = 28;
const HOLD_MS = 2400;

/** Events that arrived after the layout did (a stage opened mid-run folds the history in without ceremony). */
export function useArrivals(events: readonly Event[], ready: boolean): readonly Event[] {
  const base = useRef<number | null>(null);
  if (ready && base.current === null) base.current = events[events.length - 1]?.seq ?? 0;
  const from = base.current;
  return useMemo(() => (from === null ? [] : events.filter((e) => e.seq > from)), [events, from]);
}

/** What the failed run did before it stopped, from the record: a person's approval or a sent message means something
 * did happen, so the card never claims otherwise. */
export function failureNote(events: readonly Event[]): string {
  const done = events.filter(
    (e) =>
      e.type === "channel.message_out" ||
      (e.type === "approval.resolved" &&
        (e.data as { option?: unknown } | null)?.option === "approve") ||
      (e.type === "policy.applied" && e.authz?.by === "policy"),
  ).length;
  return done === 0
    ? "Nothing was booked, sent or paid."
    : `${done} approved ${done === 1 ? "action" : "actions"} had already happened before it stopped: see the Story for which.`;
}

const place = (layout: Layout | null, common: string): string | null =>
  layout?.semantic.levels
    .flatMap((l) => l.districts)
    .flatMap((d) => d.buildings)
    .find((b) => b.common_type === common)?.id ?? null;

interface Flight {
  readonly seq: number;
  readonly d: string;
}

export function StageEvents({
  worldId,
  layout,
  events,
}: {
  worldId: string;
  layout: Layout | null;
  events: readonly Event[];
}) {
  const arrivals = useArrivals(events, layout !== null);
  const [flights, setFlights] = useState<Flight[]>([]);
  const [burst, setBurst] = useState<number | null>(null);
  const seen = useRef(new Set<number>());
  const failed = [...events].reverse().find((e) => e.type === "world.failed");

  useEffect(() => {
    for (const e of arrivals) {
      if (seen.current.has(e.seq)) continue;
      seen.current.add(e.seq);
      if (e.type === "world.completed") {
        // triggeredBy: world.completed: the confetti bursts once and never loops.
        setBurst(e.seq);
        setTimeout(() => setBurst((b) => (b === e.seq ? null : b)), HOLD_MS);
      }
      if (e.type === "artifact.delivered") {
        // triggeredBy: artifact.delivered: a parcel arcs from the Meeting Hall to the Delivery Dock.
        const probe = registerProbe.get(worldId);
        const from = probe?.locate(place(layout, "meeting_hall") ?? "");
        const to = probe?.locate(place(layout, "delivery_dock") ?? "");
        if (!from || !to) continue; // no place on the stage for one end: nothing is drawn for it
        const lift = Math.min(from.y, to.y) - 60;
        const d = `M ${from.x} ${from.y} Q ${(from.x + to.x) / 2} ${lift} ${to.x} ${to.y}`;
        setFlights((f) => [...f, { seq: e.seq, d }]);
        setTimeout(() => setFlights((f) => f.filter((x) => x.seq !== e.seq)), HOLD_MS);
      }
    }
  }, [arrivals, layout, worldId]);

  return (
    <>
      {flights.map((f) => (
        <span
          key={f.seq}
          className="tw-parcel"
          style={{ offsetPath: `path("${f.d}")` }}
          aria-hidden="true"
        />
      ))}
      {burst !== null ? (
        <span className="tw-confetti" aria-hidden="true" data-testid="confetti">
          {Array.from({ length: CONFETTI }, (_, i) => {
            const a = (i / CONFETTI) * Math.PI * 2;
            const r = 90 + (i % 5) * 28;
            return (
              <i
                // biome-ignore lint/suspicious/noArrayIndexKey: a fixed ring of pieces, never reordered
                key={i}
                style={
                  {
                    "--cx": `${Math.round(Math.cos(a) * r)}px`,
                    "--cy": `${Math.round(Math.sin(a) * r - 40)}px`,
                    background: ["var(--lime)", "var(--amber)", "var(--pri)", "var(--mint)"][i % 4],
                  } as React.CSSProperties
                }
              />
            );
          })}
        </span>
      ) : null}
      {failed ? (
        <div className="tw-failed tw-pop" data-testid="world-failed-card" role="alert">
          <strong>This run stopped.</strong>
          <span>{failed.summary}</span>
          <span>{failureNote(events)}</span>
        </div>
      ) : null}
    </>
  );
}
