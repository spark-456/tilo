import { useState } from "react";
import { TiloApiError } from "../../../api/http";
import type {
  DraftCard,
  MeetingMinutesApi,
  MinutesView,
  TranscriptView,
} from "../../api/live/meetingMinutes";

/** MINUTES-SCREEN: the server's stable refusal word, said in plain words; anything else keeps the general sentence. */
const REFUSALS: Readonly<Record<string, string>> = {
  transcript_unavailable:
    "Tilo could not use this meeting's transcript: it has not passed the safety check yet, or it is no longer kept. Try again in a minute.",
  analysis_failed: "Tilo could not write minutes from this transcript. Try again.",
  // MINUTES-TIME: the server stops waiting for a slow model after about a minute and a half
  analysis_timed_out:
    "Tilo could not write the minutes in time: the model service is slow right now. Try again in a minute.",
  allowance_capped: "Today's allowance for meeting minutes is used up. Try again tomorrow.",
  version_conflict: "The meeting changed while Tilo was working. Try again.",
  not_publishable: "Minutes for this meeting were already made. Review the stored minutes.",
  analysis_inputs_unavailable:
    "This meeting has no start time recorded, so Tilo cannot make minutes for it.",
};
const SCREENING_NOTES: Readonly<Record<string, string>> = {
  flagged: "The safety check flagged this transcript, so Tilo makes no minutes from it.",
  unscreened:
    "The safety check has not passed this transcript yet. Analyze minutes checks it again.",
};
const clock = (ms: number) => {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
};

/** Explicit owner actions only. Confirmation and drafting are separate person decisions. */
export function MeetingMinutes({
  id,
  status,
  api,
}: { id: string; status: string; api: MeetingMinutesApi }) {
  const [minutes, setMinutes] = useState<MinutesView | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recipients, setRecipients] = useState<string[]>([]);
  const [cards, setCards] = useState<DraftCard[]>([]);
  const [hidden, setHidden] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptView | null>(null);
  const [transcriptNote, setTranscriptNote] = useState("");
  // MINUTES-ME: the transcript loads on its own, so a long analysis never holds it (21 Oct: 8 minutes of "Working…")
  const [loadingTranscript, setLoadingTranscript] = useState(false);
  const [working, setWorking] = useState("Working…");
  if (hidden || !["ended", "minuted"].includes(status)) return null;
  const run = async (action: () => Promise<void>, note = "Working…") => {
    setBusy(true);
    setWorking(note);
    setError("");
    try {
      await action();
    } catch (e) {
      if (e instanceof TiloApiError && e.status === 404) setHidden(true);
      else
        setError(
          (e instanceof TiloApiError && e.code && REFUSALS[e.code]) ||
            (e instanceof TiloApiError && e.status === 502 && REFUSALS.analysis_failed) ||
            "This step could not finish. Review the current meeting before trying again.",
        );
    } finally {
      setBusy(false);
    }
  };
  const toggleTranscript = async () => {
    if (transcript) {
      setTranscript(null);
      return;
    }
    setLoadingTranscript(true);
    setTranscriptNote("");
    try {
      setTranscript(await api.transcript(id));
    } catch (e) {
      setTranscriptNote(
        e instanceof TiloApiError && e.status === 404
          ? "No transcript is kept for this meeting."
          : "The transcript could not be loaded. Try again.",
      );
    } finally {
      setLoadingTranscript(false);
    }
  };
  const read = async () => {
    const result = await api.read(id);
    setMinutes(result.minutes);
    setConfirmed(result.confirmed);
    // MINUTES-ME: with nobody else linked, the Owner's own address ("Me") is the one choice: picked for them
    if (result.minutes.recipients.length === 1 && result.minutes.recipients[0]?.self)
      setRecipients([result.minutes.recipients[0].id]);
  };
  const analyze = () =>
    void run(
      async () => {
        if (status === "ended") await api.analyze(id);
        await read();
      },
      status === "ended"
        ? "Writing the minutes. This takes up to a minute and a half; the transcript stays open meanwhile."
        : "Working…",
    );
  return (
    <div className="park-agenda-minutes" aria-label="Meeting minutes">
      {!minutes && (
        <button type="button" disabled={busy} onClick={analyze}>
          {status === "ended" ? "Analyze minutes" : "Review minutes"}
        </button>
      )}
      {minutes && (
        <>
          {(
            [
              ["Summary", minutes.summary],
              ["Decisions", minutes.decisions],
              ["Action items", minutes.actions],
            ] as const
          ).map(([title, rows]) => (
            <section key={title} aria-label={title}>
              <h3>{title}</h3>
              <ul>
                {rows.map((text, i) => (
                  <li key={`${i}:${text}`}>{text}</li>
                ))}
              </ul>
            </section>
          ))}
          {!confirmed ? (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await api.confirm(id);
                  await read();
                })
              }
            >
              Confirm these minutes
            </button>
          ) : (
            <>
              <p>Minutes confirmed. Drafting waits for your request; sending waits for approval.</p>
              <fieldset>
                <legend>Choose recipients</legend>
                {minutes.recipients.map((person) => (
                  <label key={person.id}>
                    <input
                      type="checkbox"
                      checked={recipients.includes(person.id)}
                      onChange={(e) =>
                        setRecipients((current) =>
                          e.target.checked
                            ? [...current, person.id]
                            : current.filter((id) => id !== person.id),
                        )
                      }
                    />
                    {person.name}
                  </label>
                ))}
              </fieldset>
              {!minutes.recipients.length && (
                <p>No meeting attendees have a linked person record. Add them before drafting.</p>
              )}
              <button
                type="button"
                disabled={busy || !recipients.length}
                onClick={() =>
                  void run(async () => {
                    setCards([]);
                    setCards(await api.draft(id, recipients));
                  })
                }
              >
                Draft follow-up
              </button>
            </>
          )}
        </>
      )}
      <button
        type="button"
        disabled={loadingTranscript}
        aria-expanded={transcript !== null}
        onClick={() => void toggleTranscript()}
      >
        {transcript ? "Hide transcript" : "Show transcript"}
      </button>
      {loadingTranscript && <output>Loading the transcript…</output>}
      {transcriptNote && <output>{transcriptNote}</output>}
      {transcript && (
        <section aria-label="Transcript">
          <h3>Transcript</h3>
          {SCREENING_NOTES[transcript.screening] ? (
            <p>{SCREENING_NOTES[transcript.screening]}</p>
          ) : null}
          {transcript.lines.length ? (
            <ol>
              {transcript.lines.map((line) => (
                <li key={line.id}>
                  <span>{clock(line.atMs)}</span> <strong>{line.speaker ?? "Someone"}</strong>:{" "}
                  {line.text}
                </li>
              ))}
            </ol>
          ) : (
            <p>Nobody was heard speaking in this meeting.</p>
          )}
        </section>
      )}
      {busy && <output>{working}</output>}
      {error && (
        <>
          <p role="alert">{error}</p>
          {!minutes && status === "ended" && (
            <button type="button" disabled={busy} onClick={analyze}>
              Try again
            </button>
          )}
          {!minutes && (
            <button type="button" disabled={busy} onClick={() => void run(read)}>
              Review stored minutes
            </button>
          )}
        </>
      )}
      {cards.map((card) => (
        <section key={card.cardId} aria-label="T3 approval card">
          <h3>{card.subject}</h3>
          <p>Needs your approval · nothing sent</p>
          <p>To: {card.recipients.join(", ")}</p>
          <p style={{ whiteSpace: "pre-wrap" }}>{card.body}</p>
          <p>Review this card in Needs you to approve or decline.</p>
        </section>
      ))}
    </div>
  );
}
