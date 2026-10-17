import { useEffect, useState } from "react";

type Brief = { points: { title: string; notes: string[] }[]; carry: string[] };
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

function briefOf(value: unknown, id: string): Brief | null {
  if (
    !object(value) ||
    value.meeting_id !== id ||
    !Array.isArray(value.agenda_points) ||
    !Array.isArray(value.carry_over)
  )
    return null;
  const points = value.agenda_points.flatMap((item) => {
    if (!object(item) || typeof item.title !== "string" || !Array.isArray(item.talk_points))
      return [];
    const notes = item.talk_points.flatMap((note) =>
      object(note) && typeof note.text === "string" ? [note.text] : [],
    );
    return [{ title: item.title, notes }];
  });
  const carry = value.carry_over.flatMap((item) =>
    object(item) && typeof item.text === "string" ? [item.text] : [],
  );
  return points.length || carry.length ? { points, carry } : null;
}

/** GET only; an unprepared or unreadable brief has no card. */
export function MeetingBrief({
  id,
  getJson,
}: {
  id: string;
  getJson: (path: string) => Promise<unknown>;
}) {
  const [brief, setBrief] = useState<Brief | null>(null);
  useEffect(() => {
    if (!/^mt_[A-Za-z0-9_]{1,48}$/.test(id)) return;
    let active = true;
    getJson(`/v1/meetings/${id}/brief`).then(
      (reply) => active && setBrief(briefOf(reply, id)),
      () => active && setBrief(null),
    );
    return () => {
      active = false;
    };
  }, [getJson, id]);
  if (!brief) return null;
  return (
    <section aria-label="Tilo's brief" className="park-agenda-state">
      <h3>Tilo’s brief</h3>
      {brief.points.map((point) => (
        <div key={point.title}>
          <strong>{point.title}</strong>
          {point.notes.length ? (
            <ul>
              {point.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
      {brief.carry.length ? (
        <div>
          <strong>From the last meeting</strong>
          <ul>
            {brief.carry.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
