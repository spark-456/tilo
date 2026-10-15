import { useEffect, useState } from "react";
import { TiloApiError } from "../../../api/http";
import type {
  BriefDocument,
  BriefMeeting,
  BriefSource,
  MeetingBriefApi,
} from "../../api/live/meetingBrief";

const generationError = (error: unknown): string => {
  if (error instanceof TiloApiError && error.status === 429)
    return "Your brief allowance is used up. Try again when it resets.";
  if (error instanceof TiloApiError && error.status === 503)
    return "Tilo could not make the brief. Try again in a moment.";
  return "The brief could not be made. Try again in a moment.";
};
const sourceText = (brief: BriefDocument, source: BriefSource): string => {
  if (source.kind === "agenda")
    return `Agenda point ${(source.index ?? 0) + 1}: ${brief.agenda_points[source.index ?? -1]?.title ?? "Unknown point"}`;
  const item = brief.carry_over.find(
    (c) => c.from_meeting === source.meeting_id && c.item === source.item,
  );
  return item?.text ?? `Prior meeting ${source.meeting_id}, item ${source.item}`;
};
function Switch({
  label,
  on,
  note,
  busy,
  flip,
}: {
  label: string;
  on: boolean;
  note: string;
  busy: boolean;
  flip: () => void;
}) {
  return (
    <div>
      <button
        type="button"
        role="switch"
        aria-label={label}
        aria-checked={on}
        disabled={busy}
        onClick={flip}
      >
        {label}
      </button>
      <p>{note}</p>
    </div>
  );
}

/** MB-T2: a brief is read on open, and made only by the owner's explicit click. */
export function MeetingBrief({ id, api }: { id: string; api: MeetingBriefApi }) {
  const [meeting, setMeeting] = useState<BriefMeeting | null>(null);
  const [brief, setBrief] = useState<BriefDocument | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all([api.meeting(id), api.read(id)])
      .then(
        ([m, b]) => {
          if (live) {
            setMeeting(m);
            setBrief(b);
          }
        },
        () => {
          if (live) setError("The meeting brief could not load.");
        },
      )
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [api, id]);
  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      setBrief(await api.generate(id));
    } catch (cause) {
      setError(generationError(cause));
    } finally {
      setBusy(false);
    }
  };
  const flip = async (key: "brief_requested" | "auto_report") => {
    if (!meeting) return;
    const before = meeting;
    const field = key === "brief_requested" ? "briefRequested" : "autoReport";
    const next = !before[field];
    setMeeting({ ...before, [field]: next });
    setBusy(true);
    setError("");
    try {
      setMeeting({ ...before, ...(await api.switch(id, key, next)) });
    } catch {
      setMeeting(before);
      setError("This switch could not be saved. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="park-agenda-brief" aria-label="Tilo's brief">
      <div className="park-agenda-briefhead">
        <span className="park-agenda-briefname">TILO’S BRIEF</span>
      </div>
      {loading ? <p>Loading brief…</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {!loading && meeting ? (
        <>
          {brief ? (
            <>
              {brief.flagged ? (
                <output>This brief was flagged for review. Talk points were removed.</output>
              ) : null}
              <ul>
                {brief.agenda_points.map((point, index) => (
                  <li key={`${index}:${point.title}`}>
                    <strong>{point.title}</strong>
                    {point.minutes !== null ? ` · ${point.minutes} minutes` : ""}
                    <ul>
                      {point.talk_points.map((talk, n) => (
                        <li key={`${n}:${talk.text}`}>
                          {talk.text}{" "}
                          <small>
                            Source:{" "}
                            {talk.evidence.map((source) => sourceText(brief, source)).join("; ")}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
              {brief.carry_over.length ? (
                <section aria-label="Carry-over">
                  <h3>Carry-over</h3>
                  <ul>
                    {brief.carry_over.map((item) => (
                      <li key={`${item.from_meeting}:${item.item}`}>{item.text}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </>
          ) : (
            <p>No brief yet. A brief is made only when you ask.</p>
          )}
          <button type="button" disabled={busy} onClick={() => void generate()}>
            {busy ? "Working…" : "Ask Tilo for a brief"}
          </button>
          <div className="park-agenda-toggles">
            <Switch
              label="Brief before it starts"
              on={meeting.briefRequested}
              busy={busy}
              flip={() => void flip("brief_requested")}
              note="This switch has no automatic effect until the before-meeting sweep is available."
            />
            <Switch
              label="Email me a wrap-up report"
              on={meeting.autoReport}
              busy={busy}
              flip={() => void flip("auto_report")}
              note="A report goes only to your digest if your email policy allows it."
            />
          </div>
        </>
      ) : null}
    </section>
  );
}
