import { useState } from "react";
import { TiloApiError, displayApiError } from "../../../api/http";
import type { DraftCard, MeetingMinutesApi, MinutesView } from "../../api/live/meetingMinutes";

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
  if (hidden || !["ended", "minuted"].includes(status)) return null;
  const run = async (action: () => Promise<void>, wrapUp = false) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      if (wrapUp && e instanceof TiloApiError && [403, 404, 409].includes(e.status ?? 0))
        setError("Meeting minutes are switched off");
      else if (e instanceof TiloApiError && e.status === 404) setHidden(true);
      else setError(displayApiError(e));
    } finally {
      setBusy(false);
    }
  };
  const read = async () => {
    const result = await api.read(id);
    setMinutes(result.minutes);
    setConfirmed(result.confirmed);
  };
  return (
    <div aria-label="Meeting minutes">
      {!minutes && (
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              if (status === "ended") await api.analyze(id);
              await read();
            }, status === "ended")
          }
        >
          {status === "ended" ? (busy ? "Writing the minutes..." : "Wrap up") : "Review minutes"}
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
      {busy && (minutes || status !== "ended") && <output>Working…</output>}
      {error && (
        <>
          <p role="alert">{error}</p>
          {!minutes && status !== "ended" && (
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
