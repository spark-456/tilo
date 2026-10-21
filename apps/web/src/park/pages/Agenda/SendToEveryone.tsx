import { useState } from "react";
import { TiloApiError } from "../../../api/http";
import { type DraftCard, type MeetingMinutesApi, isMailbox } from "../../api/live/meetingMinutes";

interface Row {
  readonly key: number;
  readonly name: string;
  readonly email: string;
}

/** MINUTES-ALL (owner, 21 Oct): the Owner reviews who gets ONE minutes email, edits, removes or adds each address,
 * then drafts it. The draft is a T3 card: nothing is sent until the Owner approves it in Needs you. An address is
 * never guessed from a name; someone with none on record says "no email on file" and is left out unless typed. */
export function SendToEveryone({
  id,
  api,
  onCards,
}: { id: string; api: MeetingMinutesApi; onCards: (cards: DraftCard[]) => void }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [transcriptOk, setTranscriptOk] = useState(false);
  const [withTranscript, setWithTranscript] = useState(true);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [nextKey, setNextKey] = useState(0);

  const open = async () => {
    setBusy(true);
    setNote("");
    try {
      const list = await api.sendList(id);
      setRows(list.people.map((p, key) => ({ key, name: p.name, email: p.email ?? "" })));
      setNextKey(list.people.length);
      setTranscriptOk(list.transcript);
    } catch {
      setNote("The send list could not be loaded. Try again.");
    } finally {
      setBusy(false);
    }
  };
  const edit = (key: number, email: string) =>
    setRows((current) => current?.map((r) => (r.key === key ? { ...r, email } : r)) ?? null);
  const remove = (key: number) =>
    setRows((current) => current?.filter((r) => r.key !== key) ?? null);
  const add = () => {
    setRows((current) => [...(current ?? []), { key: nextKey, name: "", email: "" }]);
    setNextKey((n) => n + 1);
  };
  const draft = async () => {
    const filled = (rows ?? []).filter((r) => r.email.trim());
    const wrong = filled.find((r) => !isMailbox(r.email.trim().toLowerCase()));
    if (wrong) {
      setNote(
        `Check the address for ${wrong.name || "the added person"}: one address, like name@example.com.`,
      );
      return;
    }
    const addresses = [...new Set(filled.map((r) => r.email.trim().toLowerCase()))];
    if (!addresses.length) {
      setNote("Add at least one address.");
      return;
    }
    setBusy(true);
    setNote("");
    try {
      onCards(await api.draftToAll(id, addresses, transcriptOk && withTranscript));
    } catch (e) {
      setNote(
        e instanceof TiloApiError && e.code === "transcript_unavailable"
          ? "The transcript has not passed the safety check, so it cannot go with this email. Untick it and try again."
          : "The email could not be drafted. Nothing was sent. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };
  const missing = (rows ?? []).filter((r) => !r.email.trim() && r.name).map((r) => r.name);

  return (
    <section aria-label="Send to everyone who joined">
      {!rows ? (
        <button type="button" disabled={busy} onClick={() => void open()}>
          Send to everyone who joined
        </button>
      ) : (
        <>
          <h3>Send to everyone who joined</h3>
          <p>
            One email with the minutes. Check every address; nothing is sent until you approve it in
            Needs you.
          </p>
          <ul>
            {rows.map((row) => (
              <li key={row.key}>
                <label>
                  {row.name || "Added person"}{" "}
                  <input
                    type="email"
                    aria-label={`Email for ${row.name || "added person"}`}
                    value={row.email}
                    placeholder="no email on file"
                    onChange={(e) => edit(row.key, e.target.value)}
                  />
                </label>
                {!row.email.trim() ? <span> no email on file</span> : null}{" "}
                <button
                  type="button"
                  aria-label={`Remove ${row.name || "this address"}`}
                  onClick={() => remove(row.key)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={add}>
            Add an address
          </button>
          <label>
            <input
              type="checkbox"
              checked={transcriptOk && withTranscript}
              disabled={!transcriptOk}
              onChange={(e) => setWithTranscript(e.target.checked)}
            />
            Include the transcript
          </label>
          {!transcriptOk ? (
            <p>The transcript has not passed the safety check, so it cannot go with this email.</p>
          ) : null}
          {missing.length ? <p>Left out, no email on file: {missing.join(", ")}.</p> : null}
          <button type="button" disabled={busy} onClick={() => void draft()}>
            Draft one email
          </button>
        </>
      )}
      {note ? <p role="alert">{note}</p> : null}
    </section>
  );
}
