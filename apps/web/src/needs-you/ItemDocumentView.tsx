// ADR-0035 L6c (FR-CON-02): "Show me" for a live item document. Everything is rendered as text nodes (React escapes
// them); no HTML, link or image is ever created from a document. An email shows its subject, the recipients the gate
// card names (the document itself holds none) and its body; a file shows its name and type and its text, or says
// "binary file, N bytes"; an event shows its title, times and zone.
import { SHOW_MAX, decodeItemDocument, plain } from "./itemDocument";

export function ItemDocumentView({
  document: raw,
  recipients = [],
}: {
  /** The pinned item's JSON text. */
  document: string;
  /** From the gate card: who the entry reaches. */
  recipients?: readonly string[];
}) {
  const doc = decodeItemDocument(raw);
  if (doc.kind === "unreadable") {
    return (
      <p className="section-note">
        This item cannot be shown here. It is not sent unless you approve it.
      </p>
    );
  }
  if (doc.kind === "calendar_event") {
    return (
      <dl className="gate-facts" aria-label="Event">
        <div>
          <dt>Title</dt>
          <dd>{doc.title}</dd>
        </div>
        <div>
          <dt>Starts</dt>
          <dd>{doc.start}</dd>
        </div>
        <div>
          <dt>Ends</dt>
          <dd>{doc.end}</dd>
        </div>
        <div>
          <dt>Time zone</dt>
          <dd>{doc.zone}</dd>
        </div>
      </dl>
    );
  }
  if (doc.kind === "email") {
    return (
      <>
        <dl className="gate-facts" aria-label="Email">
          <div>
            <dt>Subject</dt>
            <dd>{doc.subject}</dd>
          </div>
          <div>
            <dt>To</dt>
            <dd>{recipients.length > 0 ? recipients.map(plain).join(", ") : "No one yet"}</dd>
          </div>
        </dl>
        <pre className="item-text" aria-label="Email text">
          {doc.body.slice(0, SHOW_MAX)}
        </pre>
        {doc.body.length > SHOW_MAX && (
          <p className="section-note">Only the first {SHOW_MAX} characters are shown.</p>
        )}
      </>
    );
  }
  return (
    <>
      <dl className="gate-facts" aria-label="File">
        <div>
          <dt>Name</dt>
          <dd>{doc.name}</dd>
        </div>
        <div>
          <dt>Type</dt>
          <dd>{doc.mimeType}</dd>
        </div>
      </dl>
      {doc.text === null ? (
        <p className="section-note">{`binary file, ${doc.bytes} bytes`}</p>
      ) : (
        <>
          <pre className="item-text" aria-label="File text">
            {doc.text.slice(0, SHOW_MAX)}
          </pre>
          {doc.text.length > SHOW_MAX && (
            <p className="section-note">Only the first {SHOW_MAX} characters are shown.</p>
          )}
        </>
      )}
    </>
  );
}
